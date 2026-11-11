"""Controlled first-time import. Preview is read-only; POST imports a selected card only."""
from datetime import datetime
import json
from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel
from sqlalchemy.orm import Session
from sqlalchemy.exc import IntegrityError
from backend.auth.security import require_current_user
from backend.dependencies import get_db
from backend.models.master_product import MasterProduct
from backend.models.product import Product
from backend.models.wb_identity import WBIdentityLink
from backend.models.marketplace_catalog_card import MarketplaceCatalogCard
from backend.services.marketplace_catalog_import import read_marketplace
from backend.services.wb_identity_service import org_id
from backend.logging_config import get_logger

router = APIRouter(prefix='/catalog-import', tags=['Товары — первичная синхронизация'])
log = get_logger('catalog_import')
MARKETS = {'WB', 'OZON', 'YANDEX'}


def owner(request):
    user = require_current_user(request)
    if user.role != 'OWNER':
        raise HTTPException(403, 'Only organization owner may import catalog cards')
    return user


def candidates(db, row):
    return db.query(MasterProduct).filter(MasterProduct.seller_article == row['article']).all()


def classify(db, rows):
    """Read-only reconciliation of the shared catalog and confirmed platform identities.

    WB confirmations exist in two tables because the Attention and catalog-import
    flows were introduced separately. A confirmed nmID takes precedence over an
    article-only suggestion; disagreement is shown as CONFLICT, never silently
    repaired. For Ozon/Yandex only the generic catalog identity is authoritative.
    """
    masters = db.query(MasterProduct).all()
    masters_by_id = {m.id: m for m in masters}
    by_article = {}
    for master in masters:
        by_article.setdefault(master.seller_article, []).append(master)
    generic_links = db.query(MarketplaceCatalogCard).all()
    by_identity = {(x.marketplace, x.external_id): x for x in generic_links}
    by_market_article = {}
    for link in generic_links:
        by_market_article.setdefault((link.marketplace, link.seller_article), set()).add(link.external_id)

    wb_links = {str(x.nm_id): x for x in db.query(WBIdentityLink).all()} if any(
        row['marketplace'] == 'WB' for row in rows) else {}
    wb_by_article = {}
    for link in wb_links.values():
        wb_by_article.setdefault(link.current_article, set()).add(str(link.nm_id))

    for row in rows:
        market, external_id, article = row['marketplace'], row['external_id'], row['article']
        matches = by_article.get(article, [])
        suggestion = matches[0].id if len(matches) == 1 else None
        generic = by_identity.get((market, external_id))
        wb = wb_links.get(external_id) if market == 'WB' else None
        confirmed = wb or generic
        row['suggested_master_id'] = suggestion
        row['master_id'] = confirmed.master_id if confirmed else suggestion
        row['conflict_reason'] = None

        if wb and generic and wb.master_id != generic.master_id:
            row['conflict_reason'] = 'IDENTITY_DISAGREEMENT'
        elif confirmed and confirmed.master_id not in masters_by_id:
            row['conflict_reason'] = 'CONFIRMED_MASTER_MISSING'
        elif wb and wb.current_article != article:
            row['conflict_reason'] = 'WB_ARTICLE_CHANGED'
        elif generic and generic.seller_article != article:
            row['conflict_reason'] = 'IMPORTED_ARTICLE_CHANGED'
        elif len(matches) > 1:
            row['conflict_reason'] = 'DUPLICATE_CATALOG_ARTICLE'
        elif (market, article) in by_market_article and (
            by_market_article[(market, article)] - {external_id}):
            row['conflict_reason'] = 'ARTICLE_USED_BY_ANOTHER_CARD'
        elif market == 'WB' and wb_by_article.get(article, set()) - {external_id}:
            row['conflict_reason'] = 'WB_ARTICLE_USED_BY_ANOTHER_CARD'

        row['status'] = ('CONFLICT' if row['conflict_reason'] else
                         'LINKED' if confirmed else
                         'MATCH' if len(matches) == 1 else 'NEW')
    return rows


@router.get('/{marketplace}/preview')
def preview(marketplace: str, request: Request, db: Session = Depends(get_db)):
    owner(request)
    marketplace = marketplace.upper()
    if marketplace not in MARKETS:
        raise HTTPException(422, 'Unknown marketplace')
    try:
        rows = classify(db, read_marketplace(db, marketplace))
    except Exception as exc:
        log.exception('CATALOG_IMPORT_PREVIEW_FAILED market=%s', marketplace)
        raise HTTPException(502, 'Marketplace catalog request failed; check backend logs') from exc
    summary = {x: sum(row['status'] == x for row in rows) for x in ('LINKED','MATCH','NEW','CONFLICT')}
    return {'marketplace': marketplace, 'total': len(rows), 'summary': summary, 'items': rows,
            'read_only': True}


class ImportOne(BaseModel):
    external_id: str
    article: str
    master_id: int | None = None


def _apply_verified(db: Session, marketplace: str, payload: ImportOne, row: dict, oid: int):
    current_link = db.query(MarketplaceCatalogCard).filter(
        MarketplaceCatalogCard.marketplace == marketplace,
        MarketplaceCatalogCard.external_id == payload.external_id
    ).with_for_update().first()
    # WB identity may have been confirmed via the Attention workflow rather
    # than catalog-import. Never create a second, conflicting identity here.
    wb_confirmed = (db.query(WBIdentityLink).filter(
        WBIdentityLink.nm_id == payload.external_id).first()
        if marketplace == 'WB' else None)
    if wb_confirmed:
        if (wb_confirmed.current_article != row['article'] or
                (payload.master_id is not None and payload.master_id != wb_confirmed.master_id) or
                (current_link is not None and current_link.master_id != wb_confirmed.master_id)):
            raise HTTPException(409, 'WB identity differs from confirmed link; review manually')
        return {'status': 'already_linked', 'master_id': wb_confirmed.master_id}
    if current_link:
        if payload.master_id and current_link.master_id != payload.master_id:
            raise HTTPException(409, 'Card already linked to another product')
        return {'status':'already_linked', 'master_id':current_link.master_id}
    # One article may not silently map to two different cards on same marketplace.
    collision = db.query(MarketplaceCatalogCard).filter(
        MarketplaceCatalogCard.marketplace == marketplace,
        MarketplaceCatalogCard.seller_article == row['article'],
        MarketplaceCatalogCard.external_id != row['external_id']
    ).first()
    if collision:
        raise HTTPException(409, 'Article collision: review manually')
    target = None
    if payload.master_id is not None:
        target = db.query(MasterProduct).filter(MasterProduct.id == payload.master_id).first()
        if not target:
            raise HTTPException(404, 'Selected master product not found')
        # Explicit cross-marketplace association is allowed. Marketplace seller articles
        # are independent; NEVER rewrite the master seller_article on this path.
    else:
        matches = candidates(db, row)
        if len(matches) > 1:
            raise HTTPException(409, 'Multiple matching products. Select manually')
        if matches:
            target = matches[0]
        else:
            # Only unambiguous new article. Never mark as selling or active automatically.
            last = db.query(MasterProduct.sort_order).order_by(MasterProduct.sort_order.desc()).first()
            target = MasterProduct(
                organization_id=oid, sort_order=(last[0] or 0) + 1 if last else 1,
                seller_article=row['article'], internal_article=row['article'],
                name=row['name'] or row['article'], barcode=(row['barcodes'] or [None])[0],
                group='Маркетплейс', purchase_price=0, additional_costs=0,
                status='READY', active=False,
                wb_enabled=(marketplace == 'WB'),
                ozon_enabled=(marketplace == 'OZON'),
                yandex_enabled=(marketplace == 'YANDEX')
            )
            for field, value in (row.get('dimensions') or {}).items():
                setattr(target, field, value)
            db.add(target)
            db.flush()
    # Keep user-edited names, dimensions, prices, status and flags untouched.
    # Only fill clearly empty / placeholder metadata for explicitly confirmed card.
    if (not target.name or target.name == target.seller_article) and target.seller_article == row['article']:
        target.name = row['name'] or target.name or target.seller_article
    if not target.barcode and row['barcodes']:
        target.barcode = row['barcodes'][0]
    for field, value in (row.get('dimensions') or {}).items():
        if getattr(target, field) is None:
            setattr(target, field, value)
    db.add(MarketplaceCatalogCard(
        organization_id=oid, marketplace=marketplace, external_id=row['external_id'],
        seller_article=row['article'], master_id=target.id, confirmed_at=datetime.utcnow(),
        title=row['name'], barcode=(row['barcodes'] or [None])[0],
        platform_ids_json=json.dumps(row['platform_ids'], ensure_ascii=False),
        **(row.get('dimensions') or {})
    ))
    if marketplace == 'WB':
        previous = db.query(WBIdentityLink).filter(WBIdentityLink.nm_id == row['external_id']).first()
        if previous and previous.master_id != target.id:
            raise HTTPException(409, 'WB nmID already linked to another product; use Attention queue')
        if not previous:
            db.add(WBIdentityLink(organization_id=oid, nm_id=row['external_id'],
                                  master_id=target.id, current_article=row['article']))
        local = db.query(Product).filter(Product.marketplace == 'WB', Product.nm_id == row['external_id']).first()
        if not local:
            other = db.query(Product).filter(Product.marketplace=='WB', Product.seller_article==row['article']).first()
            if other:
                raise HTTPException(409, 'WB article already used by another nmID; use Attention queue')
            db.add(Product(organization_id=oid,marketplace='WB',nm_id=row['external_id'],
                           seller_article=row['article'],barcode=(row['barcodes'] or [None])[0],name=row['name']))
    return {'status':'imported', 'master_id':target.id, 'marketplace':marketplace,
            'external_id':row['external_id'], 'selling_status_unchanged':True}


@router.post('/{marketplace}/import-one')
def import_one(marketplace: str, payload: ImportOne, request: Request, db: Session = Depends(get_db)):
    owner(request)
    marketplace = marketplace.upper()
    if marketplace not in MARKETS:
        raise HTTPException(422, 'Unknown marketplace')
    try:
        cards = read_marketplace(db, marketplace)
    except Exception as exc:
        log.exception('CATALOG_IMPORT_VERIFY_FAILED market=%s', marketplace)
        raise HTTPException(502, 'Marketplace verification failed; no changes saved') from exc
    observed = [x for x in cards if x['external_id'] == payload.external_id]
    if len(observed) != 1 or observed[0]['article'] != payload.article:
        raise HTTPException(409, 'Remote card changed. Refresh preview.')
    try:
        result = _apply_verified(db, marketplace, payload, observed[0], org_id(db))
        db.commit()
        return result
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(409, 'Catalog key conflict; no changes saved') from exc
    except Exception:
        db.rollback()
        raise


@router.post('/{marketplace}/create-one')
def create_one(marketplace: str, payload: ImportOne, request: Request, db: Session = Depends(get_db)):
    """Create a new master from a verified card, regardless of source marketplace.

    Unlike import-one, never attach an existing master implicitly. The caller
    requested creation, so a concurrent/newly-existing master is a conflict.
    """
    owner(request)
    marketplace = marketplace.upper()
    if marketplace not in MARKETS:
        raise HTTPException(422, 'Unknown marketplace')
    if payload.master_id is not None:
        raise HTTPException(422, 'Creating a product must not specify an existing master_id')
    try:
        observed = [row for row in read_marketplace(db, marketplace)
                    if row['external_id'] == payload.external_id]
    except Exception as exc:
        log.exception('CATALOG_CREATE_VERIFY_FAILED market=%s', marketplace)
        raise HTTPException(502, 'Не удалось проверить карточку маркетплейса') from exc
    if len(observed) != 1 or observed[0]['article'] != payload.article or not payload.article.strip():
        raise HTTPException(409, 'Карточка изменилась; обновите предварительный просмотр')
    row = observed[0]
    oid = org_id(db)
    try:
        # Lock existing catalog rows to minimize concurrent creation conflicts;
        # the tenant-article unique constraint remains the final guard.
        db.query(MasterProduct).filter(MasterProduct.organization_id == oid).with_for_update().all()
        if candidates(db, row):
            raise HTTPException(409, 'Товар с таким артикулом уже есть в каталоге. Используйте сопоставление.')
        old = db.query(MarketplaceCatalogCard).filter(
            MarketplaceCatalogCard.marketplace == marketplace,
            MarketplaceCatalogCard.external_id == payload.external_id).first()
        if old:
            raise HTTPException(409, 'Карточка уже связана с товаром')
        if marketplace == 'WB' and db.query(WBIdentityLink).filter(
                WBIdentityLink.nm_id == payload.external_id).first():
            raise HTTPException(409, 'Карточка WB уже связана с товаром')
        result = _apply_verified(db, marketplace, payload, row, oid)
        if result.get('status') != 'imported':
            raise HTTPException(409, 'Карточка уже импортирована')
        db.commit()
        return {'status': 'created', 'master_id': result['master_id'],
                'marketplace': marketplace, 'external_id': payload.external_id}
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(409, 'Товар уже создан или возник конфликт артикула') from exc
    except Exception:
        db.rollback()
        raise


class ImportBatch(BaseModel):
    items: list[ImportOne]


@router.post('/{marketplace}/import-batch')
def import_batch(marketplace: str, payload: ImportBatch, request: Request, db: Session = Depends(get_db)):
    """Atomic batch: one remote fetch, all selected identities verified, then one DB commit."""
    owner(request)
    marketplace = marketplace.upper()
    if marketplace not in MARKETS:
        raise HTTPException(422, 'Unknown marketplace')
    if not 1 <= len(payload.items) <= 200:
        raise HTTPException(422, 'Select between 1 and 200 cards')
    identities = [x.external_id for x in payload.items]
    if len(set(identities)) != len(identities):
        raise HTTPException(422, 'Duplicate external IDs in selection')
    try:
        catalog = {x['external_id']:x for x in read_marketplace(db, marketplace)}
    except Exception as exc:
        log.exception('CATALOG_IMPORT_BATCH_VERIFY_FAILED market=%s', marketplace)
        raise HTTPException(502, 'Marketplace verification failed; no changes saved') from exc
    for x in payload.items:
        remote = catalog.get(x.external_id)
        if not remote or remote['article'] != x.article:
            raise HTTPException(409, f'{x.external_id}: remote card changed; refresh preview')
    results = []
    try:
        oid = org_id(db)
        for x in payload.items:
            results.append(_apply_verified(db, marketplace, x, catalog[x.external_id], oid))
            db.flush()
        db.commit()
        return {'status':'ok', 'results':results, 'count':len(results)}
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(409, 'Catalog key conflict; entire batch rolled back') from exc
    except Exception:
        db.rollback()
        raise


@router.get('/product/{master_id}/cards')
def product_cards(master_id: int, request: Request, db: Session = Depends(get_db)):
    require_current_user(request)
    master = db.query(MasterProduct).filter(MasterProduct.id == master_id).first()
    if not master:
        raise HTTPException(404, 'Product not found')
    linked = db.query(MarketplaceCatalogCard).filter(MarketplaceCatalogCard.master_id == master_id).all()
    result = [{'marketplace':x.marketplace, 'external_id':x.external_id,
             'seller_article':x.seller_article, 'title':x.title, 'barcode':x.barcode,
             'dimensions': {name:float(getattr(x, name)) for name in ('length_cm','width_cm','height_cm')}
                 if all(getattr(x, name) is not None for name in ('length_cm','width_cm','height_cm')) else None,
             'platform_ids':json.loads(x.platform_ids_json or '{}')} for x in linked]
    # Display WB links confirmed by the earlier Attention workflow, too.
    existing = {(x['marketplace'], x['external_id']) for x in result}
    for w in db.query(WBIdentityLink).filter(WBIdentityLink.master_id == master_id).all():
        if ('WB', w.nm_id) in existing:
            continue
        local = db.query(Product).filter(Product.marketplace == 'WB', Product.nm_id == w.nm_id).first()
        result.append({'marketplace':'WB','external_id':w.nm_id,
                       'seller_article':w.current_article,
                       'title':local.name if local else None,
                       'barcode':local.barcode if local else None,
                       'dimensions':None, 'platform_ids':{'nmID':w.nm_id}})
    return result
