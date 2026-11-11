"""Identity observation; never silently reassign WB cards or historical records."""
from datetime import datetime
from sqlalchemy.orm import Session
from backend.models.product import Product
from backend.models.master_product import MasterProduct
from backend.models.wb_identity import WBIdentityReview, WBIdentityLink

def org_id(db):
    result = db.connection().exec_driver_sql("SELECT NULLIF(current_setting('app.organization_id', true), '')::integer").scalar()
    if not result: raise RuntimeError('organization_id is required')
    return int(result)

def observe(db:Session, card:dict):
    nm = str(card.get('nmID') or '').strip()
    article = str(card.get('vendorCode') or '').strip()
    if not nm or not article: return None
    local = db.query(Product).filter(Product.marketplace=='WB',Product.nm_id==nm).all()
    collision = db.query(Product).filter(Product.marketplace=='WB',Product.seller_article==article,Product.nm_id != nm).all()
    master = db.query(MasterProduct).filter(MasterProduct.seller_article==article).all()
    approved = db.query(WBIdentityLink).filter(WBIdentityLink.nm_id==nm).first()
    # A confirmed link may have been imported after an OPEN review was created.
    # Resolve that review only when all three identities still agree. Never
    # auto-approve an absent, duplicate, or conflicting local card.
    if (approved and approved.current_article == article and len(local) == 1
            and local[0].seller_article == article and not collision):
        linked_master = db.query(MasterProduct).filter(
            MasterProduct.id == approved.master_id,
            MasterProduct.seller_article == article,
        ).first()
        if linked_master:
            pending = db.query(WBIdentityReview).filter(WBIdentityReview.nm_id == nm).first()
            if pending and pending.status == 'OPEN':
                pending.status = 'APPROVED'
                pending.master_id = approved.master_id
                pending.reviewed_at = approved.confirmed_at or datetime.utcnow()
                pending.observed_article = article
                pending.stored_article = local[0].seller_article
                pending.last_seen_at = datetime.utcnow()
            return None
    if len(local)>1: reason='DUPLICATE_NM_ID'
    elif collision: reason='ARTICLE_COLLISION'
    elif local and local[0].seller_article!=article: reason='ARTICLE_CHANGED'
    elif not local: reason='MISSING_LOCAL_CARD'
    elif not master: reason='NO_MASTER_PRODUCT'
    else: return None
    review=db.query(WBIdentityReview).filter(WBIdentityReview.nm_id==nm).first()
    if not review:
        review=WBIdentityReview(organization_id=org_id(db),nm_id=nm,first_seen_at=datetime.utcnow())
        db.add(review)
    if review.status=='APPROVED' and review.observed_article!=article:
        review.status='OPEN';review.master_id=None;review.reviewed_at=None;review.reviewed_by=None
    if review.status == 'DISMISSED' and review.observed_article==article:
        return review
    if review.status != 'APPROVED':
        review.status='OPEN'
    review.observed_article=article
    review.stored_article=local[0].seller_article if local else None
    review.reason=reason
    review.title=str(card.get('title') or '')
    review.barcodes=','.join(dict.fromkeys(str(s) for size in (card.get('sizes') or []) for s in (size.get('skus') or []) if s))
    review.last_seen_at=datetime.utcnow()
    return review

def active_article(db, product):
    link=db.query(WBIdentityLink).filter(WBIdentityLink.nm_id==str(product.nm_id)).first()
    return link.current_article if link else product.seller_article
