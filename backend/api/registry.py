from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session
from sqlalchemy import func, text

from backend.dependencies import get_db
from backend.models.master_product import MasterProduct
from backend.models.stock_history import StockHistory
from backend.models.one_c_stock import OneCStock


router = APIRouter()


def get_fbs_stock(
    db: Session,
    article: str,
    marketplace: str,
    warehouse_type: str,
):

    rows = (
        db.query(StockHistory)
        .filter(
            StockHistory.seller_article == article,
            StockHistory.marketplace == marketplace,
            StockHistory.warehouse_type == warehouse_type,
        )
        .order_by(
            StockHistory.warehouse_id,
            StockHistory.created_at.desc(),
        )
        .all()
    )

    if not rows:
        return 0

    latest = {}

    for row in rows:

        if row.warehouse_id not in latest:
            latest[row.warehouse_id] = row

    return sum(
        row.stock
        for row in latest.values()
    )


def get_last_snapshot_stock(
    db: Session,
    article: str,
    marketplace: str,
    warehouse_types: list[str],
):

    last_date = (
        db.query(
            func.max(
                StockHistory.date
            )
        )
        .filter(
            StockHistory.seller_article == article,
            StockHistory.marketplace == marketplace,
            StockHistory.warehouse_type.in_(warehouse_types),
        )
        .scalar()
    )

    if not last_date:
        return 0

    rows = (
        db.query(StockHistory)
        .filter(
            StockHistory.seller_article == article,
            StockHistory.marketplace == marketplace,
            StockHistory.warehouse_type.in_(warehouse_types),
            StockHistory.date == last_date,
        )
        .all()
    )

    return sum(
        row.stock
        for row in rows
    )


def build_marketplace_stock(
    db: Session,
    article: str,
    marketplace: str,
    fbs_type: str,
):

    fbs = get_fbs_stock(
        db,
        article,
        marketplace,
        fbs_type,
    )

    fbo = get_last_snapshot_stock(
        db,
        article,
        marketplace,
        ["FBO"],
    )

    return {
        "total": fbo + fbs,
        "fbo": fbo,
        "fbs": fbs,
        "fbs_managed": True,
    }


def build_yandex_stock(
    db: Session,
    article: str,
):

    fbs = get_fbs_stock(
        db,
        article,
        "YANDEX",
        "FBS",
    )

    fby = get_last_snapshot_stock(
        db,
        article,
        "YANDEX",
        ["FBY"],
    )

    return {
        "total": fby + fbs,
        "fby": fby,
        "fbs": fbs,
        "fbs_managed": True,
    }




def calculate_recommendation(
    stock_1c: int,
    group: str,
    fbo_stock: int,
    current_fbs: int,
    marketplace: str,
):
    stock_1c = max(int(stock_1c or 0), 0)
    fbo_stock = max(int(fbo_stock or 0), 0)
    current_fbs = max(int(current_fbs or 0), 0)

    if group == "Готовая продукция" and stock_1c < 35:
        target = 0
        reason = "LOW_1C"
    elif fbo_stock > 0:
        target = 0
        reason = "FBO_STOCK"
    else:
        wb_target = round(stock_1c * 0.40)
        ozon_target = round(stock_1c * 0.40)
        yandex_target = max(
            stock_1c - wb_target - ozon_target,
            0,
        )

        target = {
            "WB": wb_target,
            "OZON": ozon_target,
            "YANDEX": yandex_target,
        }[marketplace]

        reason = "ALLOCATION"

    if target == current_fbs:
        status = "none"
    elif reason in ("LOW_1C", "FBO_STOCK") and target == 0:
        status = "zero"
    elif target > current_fbs:
        status = "increase"
    else:
        status = "decrease"

    return {
        "target": target,
        "status": status,
        "reason": reason,
    }


def build_recommendation(
    stock_1c: int,
    group: str,
    marketplace: str,
    fbo_stock: int,
    current_fbs: int,
):
    return calculate_recommendation(
        stock_1c=stock_1c,
        group=group,
        fbo_stock=fbo_stock,
        current_fbs=current_fbs,
        marketplace=marketplace,
    )


def get_product_updated_at(
    db: Session,
    article: str,
):
    """
    Последнее фактическое обновление остатка товара
    по любому из источников, которые отображаются в реестре.

    Берём MAX(created_at), поэтому старая история не влияет
    на дату последнего обновления.
    """

    latest = (
        db.query(
            func.max(
                StockHistory.created_at
            )
        )
        .filter(
            StockHistory.seller_article == article,
            StockHistory.marketplace.in_(
                ["WB", "OZON", "YANDEX"]
            ),
            StockHistory.warehouse_type.in_(
                ["SELLER", "FBS", "FBO", "FBY"]
            ),
        )
        .scalar()
    )

    return latest


def get_products_by_group(
    db: Session,
    group: str,
):

    products = (
        db.query(MasterProduct)
        .filter(
            MasterProduct.active == True,
            MasterProduct.group == group,
        )
        .order_by(
            MasterProduct.sort_order
        )
        .all()
    )

    result = []

    for product in products:

        one_c = (
            db.query(OneCStock)
            .filter(
                OneCStock.seller_article == product.seller_article,
                OneCStock.group == product.group,
            )
            .first()
        )

        stock_1c = one_c.stock if one_c else 0

        wb = build_marketplace_stock(
            db,
            product.seller_article,
            "WB",
            "SELLER",
        )

        ozon = build_marketplace_stock(
            db,
            product.seller_article,
            "OZON",
            "FBS",
        )

        yandex = build_yandex_stock(
            db,
            product.seller_article,
        )

        wb["recommendation"] = build_recommendation(
            stock_1c,
            product.group,
            "WB",
            wb["fbo"],
            wb["fbs"],
        )

        ozon["recommendation"] = build_recommendation(
            stock_1c,
            product.group,
            "OZON",
            ozon["fbo"],
            ozon["fbs"],
        )

        yandex["recommendation"] = build_recommendation(
            stock_1c,
            product.group,
            "YANDEX",
            yandex["fby"],
            yandex["fbs"],
        )

        result.append(
            {
                "id": product.id,
                "article": product.seller_article,
                "name": product.name,
                "group": product.group,
                "stock_1c": stock_1c,
                "wb": wb,
                "ozon": ozon,
                "yandex": yandex,
                "updated_at": get_product_updated_at(
                    db,
                    product.seller_article,
                ),
            }
        )

    return result


@router.get("/registry")
def get_registry(
    db: Session = Depends(get_db),
):

    additional = {}
    oid = db.execute(text("SELECT NULLIF(current_setting('app.organization_id',true),'')::integer")).scalar()
    if oid is not None:
        for (name,) in db.execute(text("SELECT name FROM local_warehouses WHERE organization_id=:o AND name NOT IN ('Маркетплейс','Готовая продукция') ORDER BY id"), {"o": oid}):
            additional[name] = get_products_by_group(db, name)
    return {
        "extra": additional,
        "marketplace": get_products_by_group(
            db,
            "Маркетплейс",
        ),

        "finished": get_products_by_group(
            db,
            "Готовая продукция",
        ),
    }
