"""Manual WB identity approval; preserve master products and historical snapshots."""
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel
from sqlalchemy.orm import Session

from backend.auth.security import require_current_user
from backend.dependencies import get_db
from backend.models.master_product import MasterProduct
from backend.models.product import Product
from backend.models.wb_identity import WBIdentityLink, WBIdentityReview
from backend.services.marketplace_clients import get_wb_client
from backend.services.wb_identity_service import observe, org_id

router = APIRouter(prefix='/product-attention', tags=['Товары — требует внимания'])

# Retired WB cards remain in products, with their original article preserved
# in WBIdentityReview.stored_article / observed_article for the archived nmID.
RETIRED_PREFIX = 'WB_RETIRED:'


def owner_only(request: Request):
    user = require_current_user(request)
    if user.role != 'OWNER':
        raise HTTPException(403, 'Подтверждать связи может только владелец')
    return user


class Approve(BaseModel):
    master_id: int
    observed_article: str
    nm_id: str


@router.get('')
def reviews(db: Session = Depends(get_db)):
    entries = db.query(WBIdentityReview).order_by(
        WBIdentityReview.status.asc(), WBIdentityReview.last_seen_at.desc()
    ).all()
    return [dict(
        id=e.id, marketplace='WB', nm_id=e.nm_id,
        article=e.observed_article, old_article=e.stored_article,
        reason=e.reason, status=e.status, title=e.title, barcodes=e.barcodes,
        master_id=e.master_id,
        last_seen_at=e.last_seen_at.isoformat() if e.last_seen_at else None,
    ) for e in entries]


@router.post('/scan')
def scan(request: Request, db: Session = Depends(get_db)):
    owner_only(request)
    try:
        cards = get_wb_client(db).get_products().get('cards') or []
        seen = set()
        for card in cards:
            nm = str(card.get('nmID') or '').strip()
            if not nm or nm in seen:
                continue
            seen.add(nm)
            observe(db, card)
        db.commit()
    except Exception as err:
        db.rollback()
        raise HTTPException(status_code=502, detail='WB sync check failed; see backend logs') from err
    return {
        'scanned': len(seen),
        'attention': db.query(WBIdentityReview).filter(WBIdentityReview.status == 'OPEN').count(),
    }


@router.post('/{review_id}/approve')
def approve(review_id: int, payload: Approve, request: Request, db: Session = Depends(get_db)):
    user = owner_only(request)
    tenant = org_id(db)
    review = db.query(WBIdentityReview).filter(
        WBIdentityReview.id == review_id,
        WBIdentityReview.organization_id == tenant,
    ).with_for_update().first()
    if not review:
        raise HTTPException(404, 'Not found')
    if review.status != 'OPEN':
        raise HTTPException(409, 'Already processed')
    if review.nm_id != payload.nm_id or review.observed_article != payload.observed_article:
        raise HTTPException(409, 'Observed identity changed; scan again')
    master = db.query(MasterProduct).filter(
        MasterProduct.id == payload.master_id,
        MasterProduct.organization_id == tenant,
    ).first()
    if not master:
        raise HTTPException(404, 'Master product not found')
    if master.seller_article != review.observed_article:
        raise HTTPException(409, 'Choose a master product with the matching article')

    # Re-read ALL currently published WB cards before changing the identity.
    try:
        cards = get_wb_client(db).get_products().get('cards') or []
    except Exception as err:
        raise HTTPException(502, 'Unable to verify current WB cards') from err
    card_by_nm = {}
    for card in cards:
        nm = str(card.get('nmID') or '').strip()
        if nm in card_by_nm:
            raise HTTPException(409, 'Duplicate nmID in WB API; cannot approve')
        card_by_nm[nm] = card
    current = card_by_nm.get(review.nm_id)
    if not current or str(current.get('vendorCode') or '').strip() != review.observed_article:
        raise HTTPException(409, 'WB card changed; refresh attention queue')
    # Reject two simultaneously published WB cards using the same vendorCode.
    if any(
        nm != review.nm_id and str(card.get('vendorCode') or '').strip() == review.observed_article
        for nm, card in card_by_nm.items()
    ):
        raise HTTPException(409, 'Multiple live WB cards have this article; manual audit required')

    existing = db.query(Product).filter(
        Product.organization_id == tenant,
        Product.marketplace == 'WB',
        Product.nm_id == review.nm_id,
    ).with_for_update().all()
    if len(existing) > 1:
        raise HTTPException(409, 'Duplicate local nmID; manual audit required')
    local = existing[0] if existing else None

    collisions = db.query(Product).filter(
        Product.organization_id == tenant,
        Product.marketplace == 'WB',
        Product.seller_article == review.observed_article,
        Product.nm_id != review.nm_id,
    ).with_for_update().all()
    if len(collisions) > 1:
        raise HTTPException(409, 'Multiple stored cards share article; manual audit required')

    # An old card can be retired only when absent from live WB catalogue and
    # not already explicitly linked to a master product. No DELETE is performed.
    old = collisions[0] if collisions else None
    if old:
        if old.nm_id in card_by_nm:
            raise HTTPException(409, 'Conflicting card is still published on WB')
        old_link = db.query(WBIdentityLink).filter(
            WBIdentityLink.organization_id == tenant,
            WBIdentityLink.nm_id == old.nm_id,
        ).with_for_update().first()
        if old_link:
            raise HTTPException(409, 'Conflicting nmID has a confirmed link; manual audit required')
        retired_article = RETIRED_PREFIX + str(old.nm_id)
        if db.query(Product).filter(
            Product.organization_id == tenant,
            Product.marketplace == 'WB',
            Product.seller_article == retired_article,
            Product.id != old.id,
        ).first():
            raise HTTPException(409, 'Retired article marker already exists')
        old_review = db.query(WBIdentityReview).filter(
            WBIdentityReview.organization_id == tenant,
            WBIdentityReview.nm_id == old.nm_id,
        ).with_for_update().first()
        if old_review and old_review.status == 'OPEN':
            raise HTTPException(409, 'Conflicting card has a pending review; resolve it first')
        if not old_review:
            old_review = WBIdentityReview(
                organization_id=tenant, nm_id=old.nm_id,
                first_seen_at=datetime.utcnow(),
            )
            db.add(old_review)
        # Audit of the original seller article is retained in the review table.
        old_review.stored_article = old.seller_article
        old_review.observed_article = old.seller_article
        old_review.reason = 'RETIRED_ARTICLE_COLLISION'
        old_review.status = 'ARCHIVED'
        old_review.title = old.name
        old_review.barcodes = old.barcode or ''
        old_review.last_seen_at = datetime.utcnow()
        old_review.reviewed_at = datetime.utcnow()
        old_review.reviewed_by = str(user.id)
        old.seller_article = retired_article
        old.updated_at = datetime.utcnow()
        # The database has an immediate UNIQUE constraint on seller_article.
        # Flush the retirement UPDATE first, before reusing HS219 on the live card.
        # This is still the SAME transaction: if approval later fails, it rolls back.
        db.flush()

    # Keep the original Product ID for the long-lived nmID. Never rewrite
    # stock_history, sales, analytics, or MasterProduct records.
    sizes = current.get('sizes') or []
    first = sizes[0] if sizes else {}
    skus = first.get('skus') or []
    barcode = next((str(sku) for size in sizes for sku in (size.get('skus') or []) if sku), None)
    if not local:
        local = Product(
            organization_id=tenant, marketplace='WB', nm_id=review.nm_id,
            seller_article=review.observed_article,
        )
        db.add(local)
    local.seller_article = review.observed_article
    local.barcode = barcode
    local.chrt_id = str(first['chrtID']) if first.get('chrtID') is not None else None
    local.name = current.get('title')
    local.updated_at = datetime.utcnow()

    link = db.query(WBIdentityLink).filter(
        WBIdentityLink.organization_id == tenant,
        WBIdentityLink.nm_id == review.nm_id,
    ).with_for_update().first()
    if not link:
        link = WBIdentityLink(organization_id=tenant, nm_id=review.nm_id)
        db.add(link)
    link.master_id = master.id
    link.current_article = review.observed_article
    link.confirmed_at = datetime.utcnow()

    review.status = 'APPROVED'
    review.master_id = master.id
    review.reviewed_at = datetime.utcnow()
    review.reviewed_by = str(user.id)
    db.commit()
    return {
        'status': 'approved', 'nm_id': review.nm_id, 'master_id': master.id,
        'retired_nm_id': old.nm_id if old else None,
        'note': 'Historical records unchanged. Retired WB card retained with archive marker.',
    }


@router.post('/{review_id}/dismiss')
def dismiss(review_id: int, request: Request, db: Session = Depends(get_db)):
    user = owner_only(request)
    review = db.query(WBIdentityReview).filter(
        WBIdentityReview.id == review_id,
        WBIdentityReview.organization_id == org_id(db),
    ).with_for_update().first()
    if not review:
        raise HTTPException(404, 'Not found')
    if review.status != 'OPEN':
        raise HTTPException(409, 'Already processed')
    review.status = 'DISMISSED'
    review.reviewed_at = datetime.utcnow()
    review.reviewed_by = str(user.id)
    db.commit()
    return {'status': 'dismissed'}
