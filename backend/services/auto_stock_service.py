from datetime import date, datetime

from sqlalchemy.orm import Session

from backend.models.master_product import MasterProduct
from backend.models.stock_history import StockHistory
from backend.models.auto_stock_history import AutoStockHistory


def calculate_auto_stock(db: Session):

    products = db.query(MasterProduct).filter(MasterProduct.active == True).all()

    total = len(products)

    if total == 0:
        return {"status": "error", "message": "Нет активных товаров"}

    counters = {
        "WB": 0,
        "OZON": 0,
        "YANDEX": 0,
        "ALL": 0,
    }

    for product in products:

        stocks = {}

        for mp, warehouse_type in [
            ("WB", "SELLER"),
            ("OZON", "FBS"),
            ("YANDEX", "FBS"),
        ]:

            row = (
                db.query(StockHistory)
                .filter(
                    StockHistory.seller_article == product.seller_article,
                    StockHistory.marketplace == mp,
                    StockHistory.warehouse_type == warehouse_type,
                )
                .order_by(StockHistory.created_at.desc())
                .first()
            )

            stocks[mp] = row.stock if row else 0

            if stocks[mp] == 0:
                counters[mp] += 1

        if all(value == 0 for value in stocks.values()):
            counters["ALL"] += 1

    result = {
        "date": str(date.today()),
        "total_products": total,
    }

    for key, value in counters.items():

        percent = round(value / total * 100, 2)

        result[key] = {
            "zero_products": value,
            "percent": percent,
        }

        existing = (
            db.query(AutoStockHistory)
            .filter(
                AutoStockHistory.date == date.today(),
                AutoStockHistory.marketplace == key,
            )
            .first()
        )

        if existing:

            existing.zero_products = value
            existing.total_products = total
            existing.autostock_percent = percent
            existing.created_at = datetime.utcnow()

        else:

            db.add(
                AutoStockHistory(
                    date=date.today(),
                    marketplace=key,
                    total_products=total,
                    zero_products=value,
                    autostock_percent=percent,
                )
            )

    db.commit()

    return result
