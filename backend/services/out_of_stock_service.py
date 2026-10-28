from sqlalchemy.orm import Session

from backend.models.master_product import MasterProduct
from backend.models.stock_history import StockHistory


MARKETPLACE_CONFIG = {
    "WB": {"stock_types": ["SELLER", "FBO"]},
    "OZON": {"stock_types": ["FBS", "FBO"]},
    "YANDEX": {"stock_types": ["FBS", "FBY"]},
}


def _latest_rows_by_warehouse(
    db: Session,
    article: str,
    marketplace: str,
    warehouse_types: list[str],
):
    rows = (
        db.query(StockHistory)
        .filter(
            StockHistory.seller_article == article,
            StockHistory.marketplace == marketplace,
            StockHistory.warehouse_type.in_(warehouse_types),
        )
        .order_by(
            StockHistory.warehouse_id.asc(),
            StockHistory.created_at.desc(),
        )
        .all()
    )

    latest = {}
    for row in rows:
        key = (row.warehouse_id, row.warehouse_type)
        if key not in latest:
            latest[key] = row

    return list(latest.values())


def _marketplace_stock(
    db: Session,
    article: str,
    marketplace: str,
) -> int:
    rows = _latest_rows_by_warehouse(
        db,
        article,
        marketplace,
        MARKETPLACE_CONFIG[marketplace]["stock_types"],
    )
    return sum(max(int(row.stock or 0), 0) for row in rows)


def calculate_out_of_stock(db: Session):
    products = (
        db.query(MasterProduct)
        .filter(MasterProduct.active == True)
        .order_by(MasterProduct.seller_article.asc())
        .all()
    )

    total_products = len(products)
    total_positions = total_products * len(MARKETPLACE_CONFIG)
    overall_zero = 0
    marketplaces = {}

    for marketplace in MARKETPLACE_CONFIG:
        zero_products = 0

        for product in products:
            total_stock = _marketplace_stock(
                db,
                product.seller_article,
                marketplace,
            )
            if total_stock == 0:
                zero_products += 1

        marketplaces[marketplace] = {
            "zero_products": zero_products,
            "total_products": total_products,
            "percent": round(zero_products / total_products * 100, 2)
            if total_products else 0.0,
        }
        overall_zero += zero_products

    return {
        "status": "ok",
        "total_products": total_products,
        "total_positions": total_positions,
        "marketplaces": marketplaces,
        "overall": {
            "zero_products": overall_zero,
            "total_positions": total_positions,
            "percent": round(overall_zero / total_positions * 100, 2)
            if total_positions else 0.0,
        },
    }


def current_oos_details(db: Session, marketplace: str):
    """Current OOS SKUs and earliest observed zero-stock snapshot in their current run.

    Historical stock_history is sparse: calendar-day duration is estimated from
    observed snapshots, not guaranteed to be a complete daily audit trail.
    """
    from collections import defaultdict
    from datetime import date

    from backend.models.stock_history import StockHistory

    if marketplace not in MARKETPLACE_CONFIG:
        raise ValueError('Unknown marketplace')

    products = (db.query(MasterProduct)
                .filter(MasterProduct.active.is_(True))
                .order_by(MasterProduct.seller_article.asc()).all())
    zero_products = [p for p in products if _marketplace_stock(db, p.seller_article, marketplace) == 0]
    if not zero_products:
        return {'marketplace': marketplace, 'items': [], 'count': 0, 'note': 'Отображаются товары с нулевым остатком сейчас.'}

    articles = [p.seller_article for p in zero_products]
    history = (db.query(StockHistory)
               .filter(StockHistory.marketplace == marketplace,
                       StockHistory.warehouse_type.in_(MARKETPLACE_CONFIG[marketplace]['stock_types']),
                       StockHistory.seller_article.in_(articles))
               .order_by(StockHistory.seller_article, StockHistory.date, StockHistory.created_at, StockHistory.id)
               .all())
    snapshots = defaultdict(lambda: defaultdict(dict))
    for row in history:
        # Last observation per warehouse and day; do not add multiple snapshots.
        snapshots[row.seller_article][row.date][(row.warehouse_id, row.warehouse_type)] = max(int(row.stock or 0), 0)

    today = date.today()
    items = []
    for product in zero_products:
        by_day = snapshots.get(product.seller_article, {})
        # Carry forward each warehouse's most recent known state across observed dates.
        latest_by_warehouse = {}
        first_zero = None
        observed_positive = False
        for day in sorted(by_day):
            latest_by_warehouse.update(by_day[day])
            stock = sum(latest_by_warehouse.values())
            if stock > 0:
                observed_positive = True
                first_zero = None
            elif first_zero is None:
                first_zero = day
        # A snapshot only proves zero at observation time. If history is absent,
        # we deliberately do not invent a starting date or duration.
        observed_start = first_zero if first_zero and first_zero <= today else None
        items.append({
            'article': product.seller_article,
            'name': product.name or 'Без названия',
            'oos_since': observed_start.isoformat() if observed_start else None,
            'days_oos': (today - observed_start).days + 1 if observed_start else None,
            'date_is_observed': True,
            'had_positive_observation': observed_positive,
        })

    items.sort(key=lambda x: (x['days_oos'] is None, -(x['days_oos'] or 0), x['article']))
    return {
        'marketplace': marketplace,
        'count': len(items),
        'items': items,
        'note': 'Дата OOS — первое наблюдение нулевого остатка после последнего зафиксированного наличия. Дни считаются календарно, включая сегодняшний; при пропусках снимков это оценка. Нет истории — дата и дни не указываются.',
    }
