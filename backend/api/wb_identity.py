"""Manual WB identity approval; preserve master products and historical snapshots."""
from datetime import datetime
import hashlib
import json
import logging

logger = logging.getLogger(__name__)

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
from backend.services.product_dimensions_audit import dimension_issues
from backend.services.product_dimension_fill import plan_fill
from backend.services.wb_bulk_identity import build_proposals
from backend.services.product_dimension_manual import plan_manual_dimensions
from backend.models.product_dimension_change import ProductDimensionChange
from backend.models.marketplace_catalog_card import MarketplaceCatalogCard
from backend.models.product_barcode_change import ProductBarcodeChange

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


class BulkLinkApply(BaseModel):
    preview_fingerprint: str
    selected_nm_ids: list[str]


def _bulk_candidates(db, tenant, cards, *, lock=False):
    links = db.query(WBIdentityLink).filter(WBIdentityLink.organization_id == tenant).all()
    masters_query = db.query(MasterProduct).filter(MasterProduct.organization_id == tenant)
    locals_query = db.query(Product).filter(Product.organization_id == tenant, Product.marketplace == 'WB')
    reviews_query = db.query(WBIdentityReview).filter(WBIdentityReview.organization_id == tenant)
    if lock:
        masters_query = masters_query.with_for_update()
        locals_query = locals_query.with_for_update()
        reviews_query = reviews_query.with_for_update()
    imported_query = db.query(MarketplaceCatalogCard).filter(
        MarketplaceCatalogCard.organization_id == tenant,
        MarketplaceCatalogCard.marketplace == 'WB',
    )
    if lock:
        imported_query = imported_query.with_for_update()
    return build_proposals(cards, links, masters_query.all(), locals_query.all(),
                           reviews_query.all(), imported_query.all())


def _bulk_fingerprint(proposals, skipped):
    # Scope to the whole observed proposal set. Re-evaluated under transaction.
    data = {'proposals': proposals, 'skipped': skipped}
    return hashlib.sha256(json.dumps(data, ensure_ascii=False, sort_keys=True, default=str).encode()).hexdigest()


@router.post('/bulk-links/preview')
def preview_bulk_links(request: Request, db: Session = Depends(get_db)):
    owner_only(request)
    tenant = org_id(db)
    try:
        cards = get_wb_client(db).get_products().get('cards') or []
        proposals, skipped = _bulk_candidates(db, tenant, cards)
        return {'proposals': proposals, 'skipped': skipped,
                'fingerprint': _bulk_fingerprint(proposals, skipped), 'read_only': True}
    except Exception as err:
        logger.exception('WB_BULK_LINK_PREVIEW_FAILED error_type=%s', type(err).__name__)
        raise HTTPException(502, 'Не удалось получить актуальные данные WB для сверки') from err


@router.post('/bulk-links/apply')
def apply_bulk_links(payload: BulkLinkApply, request: Request, db: Session = Depends(get_db)):
    user = owner_only(request)
    tenant = org_id(db)
    selected = payload.selected_nm_ids
    if not selected or len(selected) > 200 or len(set(selected)) != len(selected):
        raise HTTPException(422, 'Выберите уникальные карточки для подтверждения')
    try:
        cards = get_wb_client(db).get_products().get('cards') or []
    except Exception as err:
        logger.exception('WB_BULK_LINK_FETCH_FAILED')
        raise HTTPException(502, 'Не удалось повторно проверить WB') from err
    try:
        # One transaction; lock all identity rows before resolving proposals.
        db.query(WBIdentityLink).filter(WBIdentityLink.organization_id == tenant).with_for_update().all()
        proposals, skipped = _bulk_candidates(db, tenant, cards, lock=True)
        if _bulk_fingerprint(proposals, skipped) != payload.preview_fingerprint:
            raise HTTPException(409, 'Данные изменились. Выполните предварительную проверку заново')
        indexed = {p['nm_id']: p for p in proposals}
        if any(nm not in indexed for nm in selected):
            raise HTTPException(409, 'Одна из выбранных связей больше не является однозначной')
        for nm in selected:
            p = indexed[nm]
            # Do not rewrite products, master catalog, sales, dimensions or statuses.
            db.add(WBIdentityLink(organization_id=tenant, nm_id=nm,
                                  master_id=p['master_id'], current_article=p['article'],
                                  confirmed_at=datetime.utcnow()))
            review = db.query(WBIdentityReview).filter(
                WBIdentityReview.organization_id == tenant, WBIdentityReview.nm_id == nm
            ).first()
            if review and review.status == 'OPEN':
                review.status = 'APPROVED'
                review.master_id = p['master_id']
                review.reviewed_at = datetime.utcnow()
                review.reviewed_by = str(user.id)
        db.commit()
        return {'linked': len(selected), 'nm_ids': selected}
    except HTTPException:
        db.rollback()
        raise
    except Exception as err:
        db.rollback()
        logger.exception('WB_BULK_LINK_APPLY_FAILED error_type=%s', type(err).__name__)
        raise HTTPException(409, 'Привязки не сохранены; повторите предварительную проверку') from err


@router.post('/scan')
def scan(request: Request, db: Session = Depends(get_db)):
    owner_only(request)
    try:
        cards = get_wb_client(db).get_products().get('cards') or []
        seen = set()
        dimensions_attention = []
        barcode_attention = []
        # Explicitly account for cards excluded from the dimensions audit.
        # No article-only matching and no automatic writes are performed here.
        audit_counts = {
            'checked': 0, 'with_issues': 0, 'clean': 0,
            'no_link': 0, 'no_master': 0, 'no_local': 0,
            'duplicate_local': 0, 'article_mismatch': 0,
        }
        excluded = []
        tenant = org_id(db)
        links = {str(x.nm_id): x for x in db.query(WBIdentityLink).filter(WBIdentityLink.organization_id == tenant).all()}
        masters = {x.id: x for x in db.query(MasterProduct).filter(MasterProduct.organization_id == tenant).all()}
        locals_by_nm = {}
        for product in db.query(Product).filter(Product.organization_id == tenant, Product.marketplace == 'WB').all():
            locals_by_nm.setdefault(str(product.nm_id), []).append(product)
        for card in cards:
            nm = str(card.get('nmID') or '').strip()
            if not nm or nm in seen:
                continue
            seen.add(nm)
            observe(db, card)
            link = links.get(nm)
            master = masters.get(link.master_id) if link else None
            local = locals_by_nm.get(nm, [])
            article = str(card.get('vendorCode') or '').strip()
            reason = None
            if not link:
                reason = 'no_link'
            elif not master:
                reason = 'no_master'
            elif not local:
                reason = 'no_local'
            elif len(local) > 1:
                reason = 'duplicate_local'
            elif not article or any((link.current_article != article,
                                     local[0].seller_article != article,
                                     master.seller_article != article)):
                reason = 'article_mismatch'
            if reason:
                audit_counts[reason] += 1
                # Report all excluded cards, not only the first 20.
                excluded.append({'nm_id': nm, 'article': article, 'reason': reason,
                                 'master_id': master.id if master else None})
                continue
            # A barcode is a product identifier, not an nmID or marketplace SKU.
            # Never write through scan; show missing or conflicting data for review.
            wb_barcodes = sorted({str(sku).strip() for size in (card.get('sizes') or [])
                                  for sku in (size.get('skus') or []) if str(sku).strip()})
            catalog_barcode = str(master.barcode or '').strip()
            if not wb_barcodes:
                barcode_issue = 'MISSING_ON_WB'
            elif not catalog_barcode:
                barcode_issue = 'MISSING_IN_CATALOG'
            elif catalog_barcode not in wb_barcodes:
                barcode_issue = 'BARCODE_MISMATCH'
            else:
                barcode_issue = None
            if barcode_issue:
                barcode_attention.append({
                    'nm_id': nm, 'article': article, 'master_id': master.id,
                    'title': str(card.get('title') or ''), 'catalog_barcode': catalog_barcode,
                    'wb_barcodes': wb_barcodes, 'problem': barcode_issue,
                })
            audit_counts['checked'] += 1
            wb_dimensions = card.get('dimensions') or {}
            dimensions = {dst: wb_dimensions.get(src) for src, dst in (('length', 'length_cm'), ('width', 'width_cm'), ('height', 'height_cm'))}
            problems = dimension_issues(master, dimensions)
            if problems:
                audit_counts['with_issues'] += 1
                dimensions_attention.append({
                    'marketplace': 'WB', 'nm_id': nm, 'article': link.current_article,
                    'title': str(card.get('title') or ''), 'master_id': master.id,
                    'problems': problems,
                    'catalog_dimensions': {k: float(getattr(master, k)) if getattr(master, k) is not None else None for k in ('length_cm', 'width_cm', 'height_cm')},
                    'marketplace_dimensions': {k: dimensions[k] for k in ('length_cm', 'width_cm', 'height_cm')},
                })
            else:
                audit_counts['clean'] += 1
        db.commit()
    except Exception as err:
        db.rollback()
        logger.exception('WB_PRODUCT_ATTENTION_SCAN_FAILED error_type=%s', type(err).__name__)
        raise HTTPException(status_code=502, detail='WB sync check failed; see backend logs') from err
    return {
        'dimensions_attention': dimensions_attention,
        'barcode_attention': barcode_attention,
        'dimensions_audit': {'counts': audit_counts, 'excluded': excluded},
        'scanned': len(seen),
        'attention': db.query(WBIdentityReview).filter(WBIdentityReview.status == 'OPEN').count(),
    }


def _dimension_candidates(db, tenant, cards, *, lock=False):
    """Re-check live identities and local catalog. Never use article-only matching."""
    links = {x.nm_id: x for x in db.query(WBIdentityLink).filter(WBIdentityLink.organization_id == tenant).all()}
    masters_query = db.query(MasterProduct).filter(MasterProduct.organization_id == tenant)
    if lock:
        masters_query = masters_query.with_for_update()
    masters = {x.id: x for x in masters_query.all()}
    locals_by_nm = {}
    for item in db.query(Product).filter(Product.organization_id == tenant, Product.marketplace == 'WB').all():
        locals_by_nm.setdefault(str(item.nm_id), []).append(item)
    candidates = []
    seen = set()
    duplicates = set()
    for card in cards:
        nm = str(card.get('nmID') or '').strip()
        if nm in seen:
            duplicates.add(nm)
        seen.add(nm)
    for card in cards:
        nm = str(card.get('nmID') or '').strip()
        if not nm or nm in duplicates:
            continue
        link = links.get(nm)
        master = masters.get(link.master_id) if link else None
        local = locals_by_nm.get(nm, [])
        article = str(card.get('vendorCode') or '').strip()
        if not (link and master and len(local) == 1 and article
                and link.current_article == article
                and local[0].seller_article == article
                and master.seller_article == article):
            continue
        remote = card.get('dimensions') or {}
        fields = {dest: remote.get(src) for src, dest in (
            ('length', 'length_cm'), ('width', 'width_cm'), ('height', 'height_cm'))}
        changes = plan_fill(master, fields)
        if changes:
            candidates.append({'master_id': master.id, 'article': article, 'nm_id': nm,
                               'changes': changes, '_master': master})
    return sorted(candidates, key=lambda x: (x['master_id'], x['nm_id']))


def _public_candidates(candidates):
    return [{k: v for k, v in row.items() if k != '_master'} for row in candidates]


def _fingerprint(candidates):
    payload = json.dumps(_public_candidates(candidates), sort_keys=True, ensure_ascii=False)
    return hashlib.sha256(payload.encode('utf-8')).hexdigest()


class DimensionApplyRequest(BaseModel):
    preview_fingerprint: str


class DimensionItemRequest(BaseModel):
    master_id: int
    nm_id: str


class DimensionItemApplyRequest(DimensionItemRequest):
    preview_fingerprint: str


def _candidate_for_item(candidates, master_id: int, nm_id: str):
    """Only the confirmed WB card requested by the user; never apply to others."""
    matching = [row for row in candidates if row['master_id'] == master_id and row['nm_id'] == nm_id]
    if len(matching) > 1:
        raise HTTPException(409, 'Найдены дубли карточки, запись запрещена')
    return matching


class DimensionManualRequest(DimensionItemRequest):
    dimensions: dict[str, float]


class DimensionManualApplyRequest(DimensionManualRequest):
    preview_fingerprint: str


def _manual_context(db, tenant, cards, master_id, nm_id, *, lock=False):
    """Fail closed unless one current WB card has an exact, confirmed identity."""
    matching = [card for card in cards if str(card.get('nmID') or '').strip() == nm_id]
    if len(matching) != 1:
        raise HTTPException(409, 'Карточка WB не найдена или дублируется')
    card = matching[0]
    link = db.query(WBIdentityLink).filter(
        WBIdentityLink.organization_id == tenant, WBIdentityLink.nm_id == nm_id).one_or_none()
    master_query = db.query(MasterProduct).filter(
        MasterProduct.organization_id == tenant, MasterProduct.id == master_id)
    if lock:
        master_query = master_query.with_for_update()
    master = master_query.one_or_none()
    locals_ = db.query(Product).filter(
        Product.organization_id == tenant, Product.marketplace == 'WB', Product.nm_id == nm_id).all()
    article = str(card.get('vendorCode') or '').strip()
    if not (link and master and len(locals_) == 1 and article
            and link.master_id == master_id and link.current_article == article
            and locals_[0].seller_article == article and master.seller_article == article):
        raise HTTPException(409, 'Привязка WB изменилась или не подтверждена')
    return master, article, card


def _manual_snapshot(master, article, card, nm_id, changes):
    raw = card.get('dimensions') or {}
    return {'master_id': master.id, 'nm_id': nm_id, 'article': article,
            'catalog': {f: float(getattr(master, f)) if getattr(master, f) is not None else None
                        for f in ('length_cm', 'width_cm', 'height_cm')},
            'wb': {f: raw.get(source) for source, f in (
                ('length', 'length_cm'), ('width', 'width_cm'), ('height', 'height_cm'))},
            'changes': changes}


def _manual_fingerprint(snapshot):
    return hashlib.sha256(json.dumps(snapshot, sort_keys=True, ensure_ascii=False, default=str).encode()).hexdigest()


class BarcodeRequest(BaseModel):
    master_id: int
    nm_id: str
    barcode: str


class BarcodeApplyRequest(BarcodeRequest):
    preview_fingerprint: str


def _barcode_context(db, tenant, cards, master_id, nm_id, *, lock=False):
    # Recheck complete identity, including remote card and its SKU/GTIN list.
    master, article, card = _manual_context(db, tenant, cards, master_id, nm_id, lock=lock)
    remote = sorted({str(sku).strip() for size in (card.get('sizes') or [])
                     for sku in (size.get('skus') or []) if str(sku).strip()})
    return master, article, remote


def _barcode_snapshot(master, article, nm_id, remote, barcode):
    if not barcode or len(barcode) > 64 or not barcode.isdigit():
        raise HTTPException(422, 'Штрихкод должен состоять из цифр (не более 64)')
    if not remote:
        raise HTTPException(409, 'WB не передал штрихкоды; заполнение из WB недоступно')
    if barcode not in remote:
        raise HTTPException(409, 'Выбранный штрихкод отсутствует в актуальной карточке WB')
    return {'master_id': master.id, 'nm_id': nm_id, 'article': article,
            'catalog_barcode': (master.barcode or '').strip(), 'wb_barcodes': remote,
            'new_barcode': barcode}


def _barcode_fingerprint(snapshot):
    return hashlib.sha256(json.dumps(snapshot, sort_keys=True, ensure_ascii=False).encode()).hexdigest()


@router.post('/barcode/item/preview')
def barcode_preview(payload: BarcodeRequest, request: Request, db: Session = Depends(get_db)):
    owner_only(request)
    try:
        cards = get_wb_client(db).get_products().get('cards') or []
        master, article, remote = _barcode_context(db, org_id(db), cards, payload.master_id, payload.nm_id)
        snapshot = _barcode_snapshot(master, article, payload.nm_id, remote, payload.barcode.strip())
        return {'dry_run': True, **snapshot, 'fingerprint': _barcode_fingerprint(snapshot)}
    except HTTPException:
        raise
    except Exception as err:
        logger.exception('WB_BARCODE_PREVIEW_FAILED')
        raise HTTPException(502, 'Не удалось проверить штрихкоды WB') from err


@router.post('/barcode/item/apply')
def barcode_apply(payload: BarcodeApplyRequest, request: Request, db: Session = Depends(get_db)):
    user = owner_only(request)
    if len(payload.preview_fingerprint) != 64:
        raise HTTPException(422, 'Требуется предварительная проверка')
    tenant = org_id(db)
    try:
        cards = get_wb_client(db).get_products().get('cards') or []
        master, article, remote = _barcode_context(db, tenant, cards, payload.master_id, payload.nm_id, lock=True)
        snapshot = _barcode_snapshot(master, article, payload.nm_id, remote, payload.barcode.strip())
        if _barcode_fingerprint(snapshot) != payload.preview_fingerprint:
            raise HTTPException(409, 'Данные изменились. Повторите предварительную проверку')
        if snapshot['catalog_barcode'] == snapshot['new_barcode']:
            raise HTTPException(409, 'Штрихкод уже совпадает; обновите сверку')
        old = snapshot['catalog_barcode'] or None
        master.barcode = snapshot['new_barcode']
        db.add(ProductBarcodeChange(organization_id=tenant, master_id=master.id,
                                    marketplace='WB', external_id=payload.nm_id,
                                    old_barcode=old, new_barcode=master.barcode, changed_by=user.id))
        db.commit()
        return {'status': 'updated', 'master_id': master.id, 'barcode': master.barcode}
    except HTTPException:
        db.rollback()
        raise
    except Exception as err:
        db.rollback()
        logger.exception('WB_BARCODE_APPLY_FAILED')
        raise HTTPException(500, 'Штрихкод не сохранён; транзакция отменена') from err


@router.post('/dimensions/item/manual/preview')
def preview_manual_dimensions(payload: DimensionManualRequest, request: Request, db: Session = Depends(get_db)):
    owner_only(request)
    if payload.master_id <= 0 or not payload.nm_id.strip():
        raise HTTPException(400, 'Неверный идентификатор товара')
    try:
        cards = get_wb_client(db).get_products().get('cards') or []
        master, article, card = _manual_context(db, org_id(db), cards, payload.master_id, payload.nm_id)
        changes = plan_manual_dimensions(master, payload.dimensions)
        snapshot = _manual_snapshot(master, article, card, payload.nm_id, changes)
        return {'dry_run': True, **snapshot, 'fingerprint': _manual_fingerprint(snapshot)}
    except ValueError as err:
        raise HTTPException(400, str(err)) from err
    except HTTPException:
        raise
    except Exception as err:
        logger.exception('WB_DIMENSIONS_MANUAL_PREVIEW_FAILED')
        raise HTTPException(502, 'Не удалось проверить габариты') from err


@router.post('/dimensions/item/manual/apply')
def apply_manual_dimensions(payload: DimensionManualApplyRequest, request: Request, db: Session = Depends(get_db)):
    user = owner_only(request)
    if payload.master_id <= 0 or not payload.nm_id.strip() or len(payload.preview_fingerprint) != 64:
        raise HTTPException(400, 'Неверные параметры')
    try:
        cards = get_wb_client(db).get_products().get('cards') or []
        tenant = org_id(db)
        master, article, card = _manual_context(db, tenant, cards, payload.master_id, payload.nm_id, lock=True)
        changes = plan_manual_dimensions(master, payload.dimensions)
        snapshot = _manual_snapshot(master, article, card, payload.nm_id, changes)
        if not changes or _manual_fingerprint(snapshot) != payload.preview_fingerprint:
            raise HTTPException(409, 'Данные изменились. Повторите предварительную проверку.')
        for change in changes:
            setattr(master, change['field'], change['new_cm'])
            db.add(ProductDimensionChange(
                organization_id=tenant, master_id=master.id, marketplace='WB',
                external_id=payload.nm_id, field=change['field'],
                old_cm=change['old_cm'], new_cm=change['new_cm'], changed_by=user.id))
        db.commit()
        return {'updated_fields': len(changes), 'updated_products': 1}
    except ValueError as err:
        db.rollback()
        raise HTTPException(400, str(err)) from err
    except HTTPException:
        db.rollback()
        raise
    except Exception as err:
        db.rollback()
        logger.exception('WB_DIMENSIONS_MANUAL_APPLY_FAILED')
        raise HTTPException(500, 'Не удалось сохранить габариты') from err


@router.post('/dimensions/item/preview')
def preview_dimension_item(payload: DimensionItemRequest, request: Request, db: Session = Depends(get_db)):
    owner_only(request)
    if payload.master_id <= 0 or not payload.nm_id.strip():
        raise HTTPException(400, 'Неверный идентификатор товара')
    try:
        tenant = org_id(db)
        cards = get_wb_client(db).get_products().get('cards') or []
        rows = _candidate_for_item(_dimension_candidates(db, tenant, cards), payload.master_id, payload.nm_id)
        return {'dry_run': True, 'items': _public_candidates(rows),
                'fields_count': sum(len(row['changes']) for row in rows),
                'fingerprint': _fingerprint(rows),
                'master_id': payload.master_id, 'nm_id': payload.nm_id}
    except HTTPException:
        raise
    except Exception as err:
        logger.exception('WB_DIMENSION_ITEM_PREVIEW_FAILED error_type=%s', type(err).__name__)
        raise HTTPException(502, 'Не удалось проверить размеры товара; см. лог backend') from err


@router.post('/dimensions/item/apply')
def apply_dimension_item(payload: DimensionItemApplyRequest, request: Request, db: Session = Depends(get_db)):
    user = owner_only(request)
    if payload.master_id <= 0 or not payload.nm_id.strip() or len(payload.preview_fingerprint) != 64:
        raise HTTPException(400, 'Некорректные параметры подтверждения')
    try:
        tenant = org_id(db)
        cards = get_wb_client(db).get_products().get('cards') or []
        rows = _candidate_for_item(_dimension_candidates(db, tenant, cards, lock=True), payload.master_id, payload.nm_id)
        if not rows or _fingerprint(rows) != payload.preview_fingerprint:
            db.rollback()
            raise HTTPException(409, 'Данные изменились или пустых полей больше нет. Повторите предварительную проверку.')
        updated = 0
        for row in rows:
            master = row['_master']
            for change in row['changes']:
                if getattr(master, change['field']) is not None:
                    db.rollback()
                    raise HTTPException(409, 'Размер в каталоге уже заполнен. Повторите предварительную проверку.')
                setattr(master, change['field'], change['new_cm'])
                db.add(ProductDimensionChange(
                    organization_id=tenant, master_id=master.id, marketplace='WB',
                    external_id=row['nm_id'], field=change['field'],
                    old_cm=None, new_cm=change['new_cm'], changed_by=user.id,
                ))
                updated += 1
        db.commit()
        return {'updated_fields': updated, 'updated_products': len(rows)}
    except HTTPException:
        db.rollback()
        raise
    except Exception as err:
        db.rollback()
        logger.exception('WB_DIMENSION_ITEM_APPLY_FAILED error_type=%s', type(err).__name__)
        raise HTTPException(500, 'Не удалось записать габариты; транзакция отменена') from err


@router.post('/dimensions/preview')
def preview_dimensions(request: Request, db: Session = Depends(get_db)):
    owner_only(request)
    try:
        tenant = org_id(db)
        cards = get_wb_client(db).get_products().get('cards') or []
        candidates = _dimension_candidates(db, tenant, cards)
        return {'dry_run': True, 'items': _public_candidates(candidates),
                'fields_count': sum(len(row['changes']) for row in candidates),
                'fingerprint': _fingerprint(candidates)}
    except Exception as err:
        logger.exception('WB_DIMENSIONS_PREVIEW_FAILED error_type=%s', type(err).__name__)
        raise HTTPException(502, 'Не удалось проверить габариты WB; см. лог backend') from err


@router.post('/dimensions/apply')
def apply_dimensions(payload: DimensionApplyRequest, request: Request, db: Session = Depends(get_db)):
    user = owner_only(request)
    if len(payload.preview_fingerprint) != 64:
        raise HTTPException(400, 'Неверная контрольная сумма предварительной проверки')
    try:
        tenant = org_id(db)
        cards = get_wb_client(db).get_products().get('cards') or []
        candidates = _dimension_candidates(db, tenant, cards, lock=True)
        if _fingerprint(candidates) != payload.preview_fingerprint:
            db.rollback()
            raise HTTPException(409, 'Данные WB или каталога изменились. Сначала повторите предварительную проверку.')
        updated = 0
        for row in candidates:
            master = row['_master']
            for change in row['changes']:
                # Defense in depth: never overwrite a value filled concurrently.
                if getattr(master, change['field']) is not None:
                    continue
                setattr(master, change['field'], change['new_cm'])
                db.add(ProductDimensionChange(
                    organization_id=tenant, master_id=master.id, marketplace='WB',
                    external_id=row['nm_id'], field=change['field'],
                    old_cm=None, new_cm=change['new_cm'], changed_by=user.id,
                ))
                updated += 1
        db.commit()
        return {'updated_fields': updated, 'updated_products': len(candidates)}
    except HTTPException:
        raise
    except Exception as err:
        db.rollback()
        logger.exception('WB_DIMENSIONS_APPLY_FAILED error_type=%s', type(err).__name__)
        raise HTTPException(500, 'Не удалось записать габариты; транзакция отменена') from err


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
