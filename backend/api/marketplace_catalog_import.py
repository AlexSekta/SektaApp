"""Controlled first-time import. Preview is read-only; POST imports a selected card only."""
from datetime import datetime
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError
import re
import json
import hashlib
from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel
from sqlalchemy.orm import Session
from sqlalchemy.exc import IntegrityError
from backend.auth.security import require_current_user
from backend.dependencies import get_db
from backend.models.master_product import MasterProduct
from backend.models.product import Product
from backend.models.wb_identity import WBIdentityLink, WBIdentityReview
from backend.models.marketplace_catalog_card import MarketplaceCatalogCard
from backend.models.marketplace_product_barcode import MarketplaceProductBarcode
from backend.models.catalog_sync_setting import CatalogSyncSetting
from backend.services.catalog_bulk_match_27 import candidates as safe_bulk_candidates, fingerprint as bulk_fingerprint
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
        # Read-only Ozon reconciliation. Matching seller article does not prove
        # identical barcode: platform barcode(s) are independent identifiers.
        if market == 'OZON':
            master = masters_by_id.get(row['master_id']) if row['master_id'] is not None else None
            local_barcode = str(master.barcode or '').strip() if master else ''
            remote_barcodes = list(dict.fromkeys(str(b).strip() for b in
                                    (row.get('barcodes') or []) if str(b).strip()))
            row['catalog_barcode'] = local_barcode or None
            row['catalog_name'] = (master.name or None) if master else None
            row['barcode_check'] = (
                'UNRESOLVED' if master is None else
                'MISSING_ON_OZON' if not remote_barcodes else
                'MISSING_IN_CATALOG' if not local_barcode else
                'SAME' if local_barcode in remote_barcodes else 'DIFFERENT'
            )
            row['barcode_check_read_only'] = True
            # Dimensions are independently audited. Missing Ozon data and API
            # errors must not be treated as matching catalog dimensions.
            source_status = row.get('dimension_fetch_status', 'UNKNOWN')
            ozon_dims = row.get('dimensions')
            fields = ('length_cm', 'width_cm', 'height_cm')
            if source_status == 'API_ERROR':
                dimension_check = 'OZON_API_ERROR'
            elif not ozon_dims:
                dimension_check = 'OZON_MISSING'
            elif master is None:
                dimension_check = 'UNRESOLVED'
            elif any(getattr(master, field, None) is None for field in fields):
                dimension_check = 'CATALOG_MISSING'
            elif any(abs(float(getattr(master,field)) - ozon_dims[field]) > 0.01 for field in fields):
                dimension_check = 'DIFFERENT'
            else:
                dimension_check = 'SAME'
            row['dimension_check'] = dimension_check
            row['catalog_dimensions'] = ({field:getattr(master,field,None) for field in fields}
                                         if master else None)
            row['dimension_check_read_only'] = True
    return rows


# Scheduled runs are deliberately NOT activated until a separate scheduler patch.
DEFAULT_SCHEDULE = ['06:00', '18:00', '23:00']


def _setting(db, oid):
    return db.query(CatalogSyncSetting).filter(CatalogSyncSetting.organization_id == oid).first()


def _setting_view(row):
    return {'match_by': row.match_by if row else 'ARTICLE',
            'auto_enabled': bool(row.auto_enabled) if row else False,
            'timezone': row.timezone if row else 'Europe/Moscow',
            'times': json.loads(row.times_json) if row else DEFAULT_SCHEDULE,
            'scheduler_active': False}


class MatchingSettingsInput(BaseModel):
    match_by: str
    auto_enabled: bool = False
    timezone: str = 'Europe/Moscow'
    times: list[str]


@router.get('/matching-settings')
def matching_settings_get(request: Request, db: Session = Depends(get_db)):
    owner(request)
    return _setting_view(_setting(db, org_id(db)))


@router.put('/matching-settings')
def matching_settings_save(payload: MatchingSettingsInput, request: Request, db: Session = Depends(get_db)):
    owner(request)
    if payload.match_by not in ('ARTICLE', 'BARCODE'):
        raise HTTPException(422, 'Выберите артикул продавца или штрихкод')
    if not 1 <= len(payload.times) <= 12 or len(set(payload.times)) != len(payload.times):
        raise HTTPException(422, 'Укажите от 1 до 12 различных времён запуска')
    if any(not re.fullmatch(r'(?:[01]\d|2[0-3]):[0-5]\d', t) for t in payload.times):
        raise HTTPException(422, 'Время должно иметь формат ЧЧ:ММ')
    # Windows installations may not ship the IANA tz database. Common zones
    # work without the optional tzdata package; arbitrary zones require it.
    known_zones = {'Europe/Moscow', 'UTC', 'Europe/Amsterdam', 'Asia/Yekaterinburg',
                   'Asia/Novosibirsk', 'Asia/Krasnoyarsk', 'Asia/Irkutsk',
                   'Asia/Vladivostok', 'Asia/Kamchatka'}
    if payload.timezone not in known_zones:
        try:
            ZoneInfo(payload.timezone)
        except (ZoneInfoNotFoundError, ValueError, KeyError):
            raise HTTPException(422, 'Неизвестный часовой пояс; установите пакет tzdata')
    oid = org_id(db)
    row = _setting(db, oid)
    if row is None:
        row = CatalogSyncSetting(organization_id=oid)
        db.add(row)
    row.match_by = payload.match_by
    row.auto_enabled = payload.auto_enabled
    row.timezone = payload.timezone
    row.times_json = json.dumps(sorted(payload.times))
    db.commit()
    return _setting_view(row)


class AutoApplyInput(BaseModel):
    fingerprint: str
    match_by: str



def _read_all_matching(db):
    """Read every enabled marketplace; never treat a partial remote read as a full batch."""
    from backend.services.unified_catalog_sync_23 import configured_markets
    markets, skipped = configured_markets(db)
    if not markets:
        raise HTTPException(409, 'Нет подключённых маркетплейсов с API-ключами')
    rows_by_market = {}
    failed = []
    tenant = org_id(db)
    for market in markets:
        try:
            rows = read_marketplace(db, market)
            if not isinstance(rows, list):
                raise ValueError('Invalid marketplace response')
            if any(str(r.get('marketplace', market)).upper() != market for r in rows):
                raise ValueError('Mismatched marketplace response')
            rows_by_market[market] = rows
        except Exception as exc:
            db.rollback()
            # get_db uses session-level SET ROLE and app.organization_id. A rollback
            # during a remote client failure can undo their initial SET statements.
            # Re-establish both before any further ORM query in this request.
            from backend.auth.tenant import set_app_db_role, set_tenant_context
            if db.get_bind().dialect.name == "postgresql":
                set_app_db_role(db)
                set_tenant_context(db, tenant)
            log.warning('CATALOG_ALL_MATCH_FETCH_FAILED market=%s error_type=%s',market,type(exc).__name__)
            failed.append(market)
    return markets, skipped, rows_by_market, failed


def _all_candidates(db, rows_by_market, method):
    proposed, excluded = [], []
    for market, rows in rows_by_market.items():
        matches, invalid = safe_bulk_candidates(db, rows, method, marketplace=market)
        proposed.extend([dict(p, marketplace=market) for p in matches])
        excluded.extend([dict(x, marketplace=market) for x in invalid])
    return proposed, excluded


def _matching_report(db, markets, rows_by_market, proposed, excluded, match_by, failed):
    """Explain planned writes separately from skips. No database mutation.

    Counts describe remote cards, not unique master products. Some exclusion
    reasons are not sufficient to distinguish new goods from ambiguous matches;
    consult tenant-scoped catalog rows for those cases.
    """
    from collections import Counter
    masters = db.query(MasterProduct).all()
    by_article = Counter(str(m.seller_article or '').strip() for m in masters)
    by_barcode = Counter(str(m.barcode or '').strip() for m in masters if m.barcode)
    stats = {market: dict(received=len(rows_by_market.get(market, [])) if market not in failed else None,
                          new_links=0, already_linked=0, new_products=0,
                          needs_review=0, api_error=(market in failed))
             for market in markets}
    classified = []
    for p in proposed:
        stats[p['marketplace']]['new_links'] += 1
    for p in excluded:
        reason = p['reason']
        category = 'NEEDS_REVIEW'
        if reason == 'ALREADY_LINKED':
            category = 'ALREADY_LINKED'
        elif reason in ('NO_UNIQUE_CATALOG_ARTICLE', 'NO_UNIQUE_CATALOG_BARCODE'):
            # Only zero plausible local candidates is a NEW product; multiple
            # candidates and absent/malformed identifiers stay for review.
            if match_by == 'ARTICLE':
                count = by_article[str(p.get('article') or '').strip()]
            else:
                source = next((r for r in rows_by_market.get(p['marketplace'], [])
                               if str(r.get('external_id')) == str(p['external_id'])), None)
                codes = set(str(x).strip() for x in ((source or {}).get('barcodes') or []) if str(x).strip())
                count = sum(by_barcode[x] for x in codes)
            if count == 0 and (match_by == 'ARTICLE' or
                               (codes and by_article[str(p.get('article') or '').strip()] == 0)):
                category = 'NEW_PRODUCT'
        bucket = {'ALREADY_LINKED':'already_linked', 'NEW_PRODUCT':'new_products',
                  'NEEDS_REVIEW':'needs_review'}[category]
        stats[p['marketplace']][bucket] += 1
        classified.append(dict(p, category=category))
    return dict(by_marketplace=stats, excluded_details=classified,
                operation_count=len(proposed),
                note='Только новые связи. Товары, которые уже связаны, не записываются повторно.')


def _all_fingerprint(proposed, excluded, method, markets):
    payload = dict(match_by=method, markets=sorted(markets),
                   proposed=sorted(proposed,key=lambda p:(p['marketplace'],p['external_id'])),
                   excluded=sorted(excluded,key=lambda p:(p['marketplace'],p['external_id'],p['reason'])))
    return hashlib.sha256(json.dumps(payload,sort_keys=True,ensure_ascii=False,default=str).encode()).hexdigest()


@router.get('/auto-preview')
def all_auto_preview(request: Request, db: Session = Depends(get_db)):
    owner(request)
    method = _setting_view(_setting(db, org_id(db)))['match_by']
    markets, skipped, rows, failed = _read_all_matching(db)
    proposed, excluded = _all_candidates(db, rows, method)
    report = _matching_report(db, markets, rows, proposed, excluded, method, failed)
    return dict(match_by=method, marketplaces=markets,
                received={m:len(items) for m,items in rows.items()},
                skipped=skipped, failed=failed, proposals=proposed, excluded=excluded,
                by_marketplace=report['by_marketplace'],
                excluded_details=report['excluded_details'],
                operation_count=report['operation_count'],
                fingerprint=_all_fingerprint(proposed,excluded,method,markets) if not failed else None,
                can_apply=not failed, read_only=True)


@router.post('/auto-apply')
def all_auto_apply(payload: AutoApplyInput, request: Request, db: Session = Depends(get_db)):
    """One explicit, verified transaction for all configured marketplaces."""
    user = owner(request)
    tenant = org_id(db)
    method = _setting_view(_setting(db,tenant))['match_by']
    if method != payload.match_by:
        raise HTTPException(409,'Правило сопоставления изменилось')
    markets, skipped, rows, failed = _read_all_matching(db)
    if failed:
        raise HTTPException(409,'Не все маркетплейсы доступны. Повторите предварительную сверку')
    # Lock existing identities before recomputing candidate safety checks.
    db.query(MarketplaceCatalogCard).filter(MarketplaceCatalogCard.organization_id == tenant).with_for_update().all()
    db.query(WBIdentityLink).filter(WBIdentityLink.organization_id == tenant).with_for_update().all()
    proposals, excluded = _all_candidates(db, rows, method)
    if _all_fingerprint(proposals,excluded,method,markets) != payload.fingerprint:
        raise HTTPException(409,'Список карточек изменился. Проверьте кандидатов повторно')
    if not proposals:
        raise HTTPException(409,'Нет новых однозначных связей')
    if len(proposals)>5000:
        raise HTTPException(422,'Более 5000 связей за один запуск — разделите операцию')
    try:
        for item in proposals:
            market = item['marketplace']
            external = item['external_id']
            article = item['article']
            master = db.query(MasterProduct).filter(MasterProduct.organization_id == tenant,
                         MasterProduct.id == item['master_id']).with_for_update().first()
            if master is None or (method == 'ARTICLE' and master.seller_article != article):
                raise HTTPException(409,'Каталог изменился — перепроверьте совпадения')
            if market == 'WB':
                db.add(WBIdentityLink(organization_id=tenant,nm_id=external,
                       master_id=master.id,current_article=article,confirmed_at=datetime.utcnow()))
                review = db.query(WBIdentityReview).filter(WBIdentityReview.organization_id == tenant,
                          WBIdentityReview.nm_id == external).first()
                if review and review.status == 'OPEN':
                    review.status = 'APPROVED'
                    review.master_id = master.id
                    review.reviewed_at = datetime.utcnow()
                    review.reviewed_by = str(user.id)
            else:
                db.add(MarketplaceCatalogCard(organization_id=tenant,marketplace=market,
                    external_id=external,seller_article=article,master_id=master.id,
                    title=item['remote_name'],barcode=(item['barcodes'] or [None])[0],
                    platform_ids_json=json.dumps(item['platform_ids'],ensure_ascii=False),
                    **(item['dimensions'] or {})))
                for bc in dict.fromkeys(item['barcodes']):
                    if bc:
                        db.add(MarketplaceProductBarcode(organization_id=tenant,master_id=master.id,
                            marketplace=market,external_id=external,barcode=bc))
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(409,'Изменились связи; вся операция отменена') from exc
    except Exception:
        db.rollback()
        raise
    return dict(status='ok',linked=len(proposals),by_marketplace={m:sum(p['marketplace']==m for p in proposals) for m in markets})


@router.get('/OZON/auto-preview')
def ozon_auto_preview(request: Request, db: Session = Depends(get_db)):
    owner(request)
    from backend.services.unified_catalog_sync_23 import configured_markets
    if 'OZON' not in configured_markets(db)[0]:
        raise HTTPException(409, 'Ozon выключен или API-ключи не настроены')
    method = _setting_view(_setting(db, org_id(db)))['match_by']
    try:
        rows = read_marketplace(db, 'OZON')
        proposals, excluded = safe_bulk_candidates(db, rows, method)
    except Exception as exc:
        log.exception('OZON_AUTO_PREVIEW_FAILED')
        raise HTTPException(502, 'Не удалось получить и проверить карточки Ozon') from exc
    return {'match_by':method, 'total':len(rows), 'proposals':proposals, 'excluded':excluded,
            'fingerprint':bulk_fingerprint(proposals,method), 'read_only':True}


@router.post('/OZON/auto-apply')
def ozon_auto_apply(payload: AutoApplyInput, request: Request, db: Session = Depends(get_db)):
    """Owner-authorized and fingerprint-verified ALL safe Ozon proposals, one transaction."""
    owner(request)
    from backend.services.unified_catalog_sync_23 import configured_markets
    if 'OZON' not in configured_markets(db)[0]:
        raise HTTPException(409, 'Ozon выключен или API-ключи не настроены')
    oid = org_id(db)
    method = _setting_view(_setting(db, oid))['match_by']
    if method != payload.match_by or method not in ('ARTICLE', 'BARCODE'):
        raise HTTPException(409, 'Правило сопоставления изменилось')
    try:
        fresh = read_marketplace(db, 'OZON')
    except Exception as exc:
        log.exception('OZON_AUTO_APPLY_READ_FAILED')
        raise HTTPException(502, 'Не удалось перепроверить Ozon') from exc
    proposals, excluded = safe_bulk_candidates(db, fresh, method)
    if bulk_fingerprint(proposals, method) != payload.fingerprint:
        raise HTTPException(409, 'Карточки изменились, обновите предварительную сверку')
    if not proposals:
        raise HTTPException(409, 'Нет однозначных карточек для подтверждения')
    if len(proposals) > 5000:
        raise HTTPException(422, 'Слишком много совпадений: разбейте операцию на части')
    try:
        for item in proposals:
            master = db.query(MasterProduct).filter(MasterProduct.organization_id == oid,
                MasterProduct.id == item['master_id']).with_for_update().first()
            if master is None or (method == 'ARTICLE' and master.seller_article != item['article']):
                raise HTTPException(409, 'Каталог изменился: повторите сверку')
            existing = db.query(MarketplaceCatalogCard).filter(
                MarketplaceCatalogCard.organization_id == oid,
                MarketplaceCatalogCard.marketplace == 'OZON',
                MarketplaceCatalogCard.external_id == item['external_id']).with_for_update().first()
            collision = db.query(MarketplaceCatalogCard).filter(
                MarketplaceCatalogCard.organization_id == oid,
                MarketplaceCatalogCard.marketplace == 'OZON',
                MarketplaceCatalogCard.seller_article == item['article'],
                MarketplaceCatalogCard.external_id != item['external_id']).first()
            if existing or collision:
                raise HTTPException(409, 'Возник конфликт карточек Ozon: повторите сверку')
            db.add(MarketplaceCatalogCard(organization_id=oid, marketplace='OZON',
                external_id=item['external_id'], seller_article=item['article'],
                master_id=master.id, title=item['remote_name'],
                barcode=(item['barcodes'] or [None])[0],
                platform_ids_json=json.dumps(item['platform_ids'],ensure_ascii=False),
                **(item['dimensions'] or {})))
            for bc in dict.fromkeys(item['barcodes']):
                if bc:
                    db.add(MarketplaceProductBarcode(organization_id=oid, master_id=master.id,
                        marketplace='OZON', external_id=item['external_id'], barcode=bc))
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(409, 'Уникальность связей нарушена; все изменения отменены') from exc
    except Exception:
        db.rollback()
        raise
    return {'status':'ok','linked':len(proposals),'excluded':len(excluded),'marketplace':'OZON'}


@router.post('/sync-connected')
def sync_connected(request: Request, db: Session = Depends(get_db)):
    """Explicit sync of enabled/configured MPs. Snapshots only, no imports."""
    owner(request)
    from backend.services.unified_catalog_sync_23 import sync_connected_catalogs
    result = sync_connected_catalogs(db, organization_id=org_id(db))
    if any(x['status'] == 'ERROR' for x in result['marketplaces']):
        log.warning('CATALOG_UNIFIED_SYNC_PARTIAL_FAILURE')
    return result


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
    barcode_summary = ({k: sum(r.get('barcode_check') == k for r in rows) for k in
                        ('SAME', 'DIFFERENT', 'MISSING_IN_CATALOG', 'MISSING_ON_OZON', 'UNRESOLVED')}
                       if marketplace == 'OZON' else None)
    dimension_summary = ({k:sum(row.get('dimension_check') == k for row in rows) for k in
                          ('SAME','DIFFERENT','CATALOG_MISSING','OZON_MISSING','OZON_API_ERROR','UNRESOLVED')}
                         if marketplace == 'OZON' else None)
    return {'marketplace': marketplace, 'total': len(rows), 'summary': summary, 'items': rows,
            'barcode_summary': barcode_summary, 'dimension_summary': dimension_summary, 'read_only': True}


def _ozon_safe_candidates(rows):
    """Only unique remote articles matching one catalog item; never match by barcode."""
    articles = {}
    for row in rows:
        if row['marketplace'] == 'OZON':
            articles[row['article']] = articles.get(row['article'], 0) + 1
    return [r for r in rows if r['marketplace'] == 'OZON'
            and articles.get(r['article']) == 1
            and r['status'] == 'MATCH' and r['suggested_master_id'] is not None
            and r['master_id'] == r['suggested_master_id']]


def _ozon_fingerprint(rows):
    payload = [{'external_id': r['external_id'], 'article': r['article'],
                'master_id': r['master_id'], 'barcodes': sorted(set(r.get('barcodes') or [])),
                'sku': (r.get('platform_ids') or {}).get('sku')}
               for r in sorted(rows, key=lambda x: x['external_id'])]
    return hashlib.sha256(json.dumps(payload, sort_keys=True, ensure_ascii=False).encode('utf-8')).hexdigest()


@router.get('/OZON/link-preview')
def ozon_link_preview(request: Request, db: Session = Depends(get_db)):
    """Read-only Ozon linking proposal. No writes and no automatic selections."""
    owner(request)
    try:
        rows = classify(db, read_marketplace(db, 'OZON'))
    except Exception as exc:
        log.exception('OZON_LINK_PREVIEW_FAILED')
        raise HTTPException(502, 'Не удалось получить карточки Ozon') from exc
    proposals = _ozon_safe_candidates(rows)
    excluded = [{'external_id': r['external_id'], 'article': r['article'],
                 'status': r['status'], 'reason': r.get('conflict_reason')}
                for r in rows if r not in proposals]
    return {'total': len(rows), 'proposals': proposals, 'excluded': excluded,
            'fingerprint': _ozon_fingerprint(proposals), 'read_only': True}


class OzonLinkSelected(BaseModel):
    external_id: str
    article: str
    master_id: int


class OzonLinkBatch(BaseModel):
    fingerprint: str
    items: list[OzonLinkSelected]


@router.post('/OZON/link-batch')
def ozon_link_batch(payload: OzonLinkBatch, request: Request, db: Session = Depends(get_db)):
    """Atomic, explicitly selected Ozon matches. Never edits master products."""
    owner(request)
    if not 1 <= len(payload.items) <= 200:
        raise HTTPException(422, 'Выберите от 1 до 200 карточек')
    ids = [x.external_id for x in payload.items]
    if len(ids) != len(set(ids)):
        raise HTTPException(422, 'Повторяются идентификаторы Ozon')
    try:
        fresh = classify(db, read_marketplace(db, 'OZON'))
    except Exception as exc:
        log.exception('OZON_LINK_VERIFY_FAILED')
        raise HTTPException(502, 'Не удалось повторно проверить карточки Ozon') from exc
    eligible = _ozon_safe_candidates(fresh)
    if _ozon_fingerprint(eligible) != payload.fingerprint:
        raise HTTPException(409, 'Данные изменились. Повторите предварительную сверку.')
    lookup = {r['external_id']: r for r in eligible}
    oid = org_id(db)
    try:
        for item in payload.items:
            row = lookup.get(item.external_id)
            if not row or row['article'] != item.article or row['master_id'] != item.master_id:
                raise HTTPException(409, f'{item.article}: сопоставление изменилось; обновите сверку')
            master = db.query(MasterProduct).filter(MasterProduct.id == item.master_id,
                       MasterProduct.organization_id == oid).with_for_update().first()
            if not master or master.seller_article != item.article:
                raise HTTPException(409, f'{item.article}: товар каталога изменился')
            # Recheck identity uniqueness under the transaction; DB unique key is final guard.
            previous = db.query(MarketplaceCatalogCard).filter(
                MarketplaceCatalogCard.organization_id == oid,
                MarketplaceCatalogCard.marketplace == 'OZON',
                MarketplaceCatalogCard.external_id == item.external_id).with_for_update().first()
            collision = db.query(MarketplaceCatalogCard).filter(
                MarketplaceCatalogCard.organization_id == oid,
                MarketplaceCatalogCard.marketplace == 'OZON',
                MarketplaceCatalogCard.seller_article == item.article,
                MarketplaceCatalogCard.external_id != item.external_id).first()
            if previous or collision:
                raise HTTPException(409, f'{item.article}: связь уже существует или возник конфликт')
            db.add(MarketplaceCatalogCard(
                organization_id=oid, marketplace='OZON', external_id=item.external_id,
                seller_article=item.article, master_id=master.id, title=row['name'],
                barcode=(row.get('barcodes') or [None])[0],
                platform_ids_json=json.dumps(row['platform_ids'], ensure_ascii=False),
                **(row.get('dimensions') or {})))
            for barcode in dict.fromkeys(row.get('barcodes') or []):
                if barcode:
                    db.add(MarketplaceProductBarcode(
                        organization_id=oid, master_id=master.id, marketplace='OZON',
                        external_id=item.external_id, barcode=barcode))
        db.commit()
        return {'status': 'ok', 'linked': len(payload.items), 'marketplace': 'OZON'}
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(409, 'Конфликт связей или штрихкодов, изменения отменены') from exc
    except Exception:
        db.rollback()
        raise


class DimensionDecisionInput(BaseModel):
    marketplace: str
    external_id: str
    master_id: int
    issue_code: str
    fingerprint: str
    decision: str


@router.post('/dimension-decision')
def set_dimension_decision(payload: DimensionDecisionInput, request: Request, db: Session = Depends(get_db)):
    """Record one explicit decision on a confirmed card. No MP/catalog attributes written."""
    user = owner(request)
    from backend.services.catalog_dimension_issues_25 import list_snapshot_attention
    from backend.models.marketplace_dimension_decision import MarketplaceDimensionDecision
    if payload.decision not in {'DISPUTED', 'ACCEPTED'}:
        raise HTTPException(422, 'Неизвестное решение')
    if payload.marketplace not in MARKETS or payload.issue_code not in {'DIFFERENT', 'MARKETPLACE_MISSING', 'CATALOG_MISSING'}:
        raise HTTPException(422, 'Неизвестная проблема')
    oid = org_id(db)
    # Lock the master to prevent simultaneous changes to catalog dimensions.
    master = db.query(MasterProduct).filter(MasterProduct.organization_id == oid,
                 MasterProduct.id == payload.master_id).with_for_update().first()
    if master is None:
        raise HTTPException(404, 'Товар не найден')
    issues = list_snapshot_attention(db, oid)
    match = next((r for r in issues if r['confirmed'] and r['master_id'] == payload.master_id
                  and r['marketplace'] == payload.marketplace
                  and r['external_id'] == payload.external_id), None)
    problem = next((p for p in (match or {}).get('problems', [])
                    if p['code'] == payload.issue_code and p.get('fingerprint') == payload.fingerprint), None)
    if not problem:
        raise HTTPException(409, 'Связь или габариты изменились. Обновите список проблем.')
    # This table is append-only: repeated approvals are traceable.
    db.add(MarketplaceDimensionDecision(
        organization_id=oid, marketplace=payload.marketplace,
        external_id=payload.external_id, master_id=payload.master_id,
        issue_code=payload.issue_code, fingerprint=payload.fingerprint,
        decision=payload.decision, actor_user_id=user.id,
        catalog_cm_json=json.dumps(match['catalog_cm']),
        marketplace_cm_json=json.dumps(match['marketplace_cm'])))
    db.commit()
    return {'status': 'ok', 'decision': payload.decision}


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
    saved_barcodes = db.query(MarketplaceProductBarcode).filter(
        MarketplaceProductBarcode.master_id == master_id).all()
    barcode_by_card = {}
    for b in saved_barcodes:
        barcode_by_card.setdefault((b.marketplace, b.external_id), []).append(b.barcode)
    result = [{'marketplace':x.marketplace, 'external_id':x.external_id,
             'seller_article':x.seller_article, 'title':x.title, 'barcode':x.barcode,
             'barcodes': barcode_by_card.get((x.marketplace, x.external_id), [x.barcode] if x.barcode else []),
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
                       'barcodes': [local.barcode] if local and local.barcode else [],
                       'dimensions':None, 'platform_ids':{'nmID':w.nm_id}})
    return result
