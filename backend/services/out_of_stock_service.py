"""Marketplace Out Of Stock, excluding unlinked (dash) positions.

WB identity is nmID.  Legacy history is read, never rewritten.  Marketplace
presence is decided separately from quantity: absent is not zero.
"""
from collections import defaultdict
from datetime import date

from sqlalchemy.orm import Session

from backend.models.master_product import MasterProduct
from backend.models.product import Product
from backend.models.stock_history import StockHistory
from backend.models.wb_identity import WBIdentityLink


MARKETPLACE_CONFIG = {
    "WB": {"stock_types": ["SELLER", "FBO"]},
    "OZON": {"stock_types": ["FBS", "FBO"]},
    "YANDEX": {"stock_types": ["FBS", "FBY"]},
}


def _marketplace_identities(db: Session):
    """Return active marketplace positions without using stock=0 as evidence.

    Confirmed WB links take precedence over article matches.  WB cards archived
    as WB_RETIRED:* are deliberately excluded.  Products which have disappeared
    from the local WB catalog do not count as WB OOS, even if wb_enabled is true.
    For Ozon/Yandex, explicit catalog flags or existing marketplace data allow
    participation; changing that eligibility requires a dedicated catalog sync.
    """
    active_products = (db.query(MasterProduct)
                       .filter(MasterProduct.active.is_(True))
                       .order_by(MasterProduct.seller_article.asc()).all())
    wb_products = db.query(Product).filter(Product.marketplace == 'WB').all()
    links = db.query(WBIdentityLink).all()

    linked_by_master = defaultdict(set)
    claimed_nm_ids = set()
    active_wb_by_nm = {
        str(product.nm_id): product
        for product in wb_products
        if product.nm_id and not (product.seller_article or '').startswith('WB_RETIRED:')
    }
    for link in links:
        claimed_nm_ids.add(str(link.nm_id))
        current_card = active_wb_by_nm.get(str(link.nm_id))
        if current_card and current_card.seller_article == link.current_article:
            linked_by_master[link.master_id].add(str(link.nm_id))

    active_nm_by_article = defaultdict(set)
    for product in wb_products:
        if (product.seller_article or '').startswith('WB_RETIRED:'):
            continue
        if product.nm_id:
            active_nm_by_article[product.seller_article].add(str(product.nm_id))

    # A historical snapshot alone must not resurrect a removed WB card.
    # For other marketplaces preserve legacy coverage where the product was
    # represented by stock-history records but its enabled flag wasn't populated.
    history_marketplace_articles = defaultdict(set)
    for marketplace, article in (db.query(StockHistory.marketplace, StockHistory.seller_article)
                                 .filter(StockHistory.marketplace.in_(['OZON', 'YANDEX']))
                                 .distinct().all()):
        history_marketplace_articles[marketplace].add(article)

    positions = {marketplace: [] for marketplace in MARKETPLACE_CONFIG}
    for product in active_products:
        if linked_by_master.get(product.id):
            wb_nm_ids = linked_by_master[product.id]
        else:
            wb_nm_ids = active_nm_by_article.get(product.seller_article, set()) - claimed_nm_ids
        if wb_nm_ids:
            positions['WB'].append((product, frozenset(wb_nm_ids)))

        for marketplace, flag in [('OZON', 'ozon_enabled'), ('YANDEX', 'yandex_enabled')]:
            if bool(getattr(product, flag, False)) or product.seller_article in history_marketplace_articles[marketplace]:
                positions[marketplace].append((product, None))
    return active_products, positions


def _history_rows(db: Session, product: MasterProduct, marketplace: str, nm_ids):
    query = db.query(StockHistory).filter(
        StockHistory.marketplace == marketplace,
        StockHistory.warehouse_type.in_(MARKETPLACE_CONFIG[marketplace]['stock_types']),
    )
    if marketplace == 'WB':
        query = query.filter(StockHistory.nm_id.in_(list(nm_ids)))
    else:
        query = query.filter(StockHistory.seller_article == product.seller_article)
    return query.order_by(StockHistory.created_at.desc(), StockHistory.id.desc()).all()


def _current_stock_from_rows(rows, marketplace):
    """Replicate registry WB FBS-by-SKU/FBO-latest-day selection.

    For other marketplaces retain the original latest-per-warehouse behavior.
    """
    if marketplace == 'WB':
        seller = {}
        fbo_date = None
        for row in rows:
            if row.warehouse_type == 'SELLER':
                seller.setdefault((row.nm_id, row.warehouse_id, row.sku), max(int(row.stock or 0), 0))
            elif fbo_date is None or row.date > fbo_date:
                fbo_date = row.date
        fbo = sum(max(int(row.stock or 0), 0) for row in rows
                  if row.warehouse_type == 'FBO' and row.date == fbo_date)
        return sum(seller.values()) + fbo

    latest = {}
    for row in rows:
        latest.setdefault((row.warehouse_id, row.warehouse_type), max(int(row.stock or 0), 0))
    return sum(latest.values())


def _latest_rows_by_warehouse(db: Session, article: str, marketplace: str, warehouse_types: list[str]):
    """Retained for callers of the legacy helper."""
    rows = (db.query(StockHistory).filter(
        StockHistory.seller_article == article,
        StockHistory.marketplace == marketplace,
        StockHistory.warehouse_type.in_(warehouse_types),
    ).order_by(StockHistory.created_at.desc(), StockHistory.id.desc()).all())
    latest = {}
    for row in rows:
        latest.setdefault((row.warehouse_id, row.warehouse_type), row)
    return list(latest.values())


def _marketplace_stock(db: Session, article: str, marketplace: str) -> int:
    """Legacy helper; the OOS endpoints use resolved marketplace positions."""
    rows = _latest_rows_by_warehouse(db, article, marketplace,
                                     MARKETPLACE_CONFIG[marketplace]['stock_types'])
    return sum(max(int(row.stock or 0), 0) for row in rows)


def calculate_out_of_stock(db: Session):
    products, positions = _marketplace_identities(db)
    marketplaces = {}
    total_positions = 0
    overall_zero = 0
    for marketplace, eligible in positions.items():
        zero_products = sum(
            _current_stock_from_rows(_history_rows(db, product, marketplace, nm_ids), marketplace) == 0
            for product, nm_ids in eligible
        )
        total = len(eligible)
        total_positions += total
        overall_zero += zero_products
        marketplaces[marketplace] = {
            'zero_products': zero_products,
            'total_products': total,
            'percent': round(zero_products / total * 100, 2) if total else 0.0,
        }
    return {
        'status': 'ok',
        'total_products': len(products),
        'total_positions': total_positions,
        'marketplaces': marketplaces,
        'overall': {
            'zero_products': overall_zero,
            'total_positions': total_positions,
            'percent': round(overall_zero / total_positions * 100, 2) if total_positions else 0.0,
        },
    }


def current_oos_details(db: Session, marketplace: str):
    """Show only eligible positions with zero stock, never a dash.

    Historical OOS spans are estimated from observations, not a daily audit.
    WB snapshots are joined across vendorCode changes by stable nmID.
    """
    if marketplace not in MARKETPLACE_CONFIG:
        raise ValueError('Unknown marketplace')

    _, positions = _marketplace_identities(db)
    today = date.today()
    items = []
    for product, nm_ids in positions[marketplace]:
        history = _history_rows(db, product, marketplace, nm_ids)
        if _current_stock_from_rows(history, marketplace) != 0:
            continue

        by_day = defaultdict(dict)
        for row in sorted(history, key=lambda r: (r.date, r.created_at, r.id)):
            # WB FBS variants must not overwrite each other.
            key = ((row.nm_id, row.warehouse_id, row.warehouse_type, row.sku)
                   if marketplace == 'WB' and row.warehouse_type == 'SELLER'
                   else (row.nm_id if marketplace == 'WB' else '', row.warehouse_id, row.warehouse_type))
            by_day[row.date][key] = max(int(row.stock or 0), 0)

        last_by_warehouse = {}
        first_zero = None
        observed_positive = False
        for day in sorted(by_day):
            last_by_warehouse.update(by_day[day])
            if sum(last_by_warehouse.values()) > 0:
                observed_positive = True
                first_zero = None
            elif first_zero is None:
                first_zero = day
        observed_start = first_zero if first_zero and first_zero <= today else None
        items.append({
            'article': product.seller_article,
            'name': product.name or 'Без названия',
            'oos_since': observed_start.isoformat() if observed_start else None,
            'days_oos': (today - observed_start).days + 1 if observed_start else None,
            'date_is_observed': True,
            'had_positive_observation': observed_positive,
        })

    items.sort(key=lambda item: (item['days_oos'] is None, -(item['days_oos'] or 0), item['article']))
    return {
        'marketplace': marketplace,
        'count': len(items),
        'items': items,
        'note': ('Товары без действующей привязки к маркетплейсу исключены из OOS (прочерк не равен нулю). '
                 'WB рассчитывается по nmID. Дата OOS — первое зафиксированное наблюдение нулевого остатка '
                 'после последнего наличия; при пропусках снимков это оценка.'),
    }
