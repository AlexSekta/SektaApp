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
