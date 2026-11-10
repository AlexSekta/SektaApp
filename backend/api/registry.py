from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session
from sqlalchemy import func, text

from backend.dependencies import get_db
from backend.models.master_product import MasterProduct
from backend.models.product import Product
from backend.models.wb_identity import WBIdentityLink
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


def build_wb_stock_for_master(db: Session, master_id: int, article: str, links_by_master: dict, linked_nm_ids: set):
    """Use WB nmID (both FBS and FBO) for confirmed master mapping.
    Without a confirmed link, legacy article matching remains available but
    may not consume rows already claimed by a different master.
    """
    ids = links_by_master.get(master_id) or []
    rows = db.query(StockHistory).filter(StockHistory.marketplace == 'WB',
        StockHistory.warehouse_type.in_(['SELLER','FBO']))
    if ids:
        rows = rows.filter(StockHistory.nm_id.in_(ids))
    else:
        rows = rows.filter(StockHistory.seller_article == article)
        if linked_nm_ids:
            rows = rows.filter(~StockHistory.nm_id.in_(linked_nm_ids))
    all_rows = rows.order_by(StockHistory.created_at.desc()).all()
    latest_fbs = {}
    latest_fbo_day = None
    fbo = 0
    for row in all_rows:
        if row.warehouse_type == 'SELLER':
            key = (row.nm_id, row.warehouse_id, row.sku)
            latest_fbs.setdefault(key, row.stock)
        elif latest_fbo_day is None:
            latest_fbo_day = row.date
    if latest_fbo_day is not None:
        fbo = sum(row.stock for row in all_rows if row.warehouse_type == 'FBO' and row.date == latest_fbo_day)
    fbs = sum(latest_fbs.values())
    return {'total':fbo+fbs,'fbo':fbo,'fbs':fbs,'fbs_managed':True}


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
    wb_articles: set | None = None,
    renamed_wb_articles: set | None = None,
    links_by_master: dict | None = None,
    linked_nm_ids: set | None = None,
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

        wb = build_wb_stock_for_master(
            db, product.id, product.seller_article,
            links_by_master or {}, linked_nm_ids or set(),
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

        # A retired WB vendorCode must not show a stale stock number (or zero).
        # The same article can remain active on Ozon and Yandex.
        wb_unavailable = (
            not (links_by_master or {}).get(product.id)
            and (product.seller_article in (renamed_wb_articles or set())
                 or (bool(product.wb_enabled) and product.seller_article not in (wb_articles or set())))
        )
        wb["available"] = not wb_unavailable

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

        if wb_unavailable:
            wb["recommendation"]["status"] = "none"

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

    # Detect historical WB articles whose nmID is currently attached to a
    # different vendorCode. Historical StockHistory records remain unchanged.
    wb_products = db.query(Product).filter(Product.marketplace == "WB").all()
    wb_articles = {p.seller_article for p in wb_products}
    current_by_nm = {str(p.nm_id): p.seller_article for p in wb_products}
    renamed_wb_articles = set()
    for old_article, old_nm_id in db.query(
        StockHistory.seller_article, StockHistory.nm_id
    ).filter(StockHistory.marketplace == "WB").distinct().all():
        current_article = current_by_nm.get(str(old_nm_id))
        if current_article and old_article != current_article:
            renamed_wb_articles.add(old_article)

    approved_links = db.query(WBIdentityLink).all()
    links_by_master = {}
    linked_nm_ids = set()
    for link in approved_links:
        links_by_master.setdefault(link.master_id, []).append(link.nm_id)
        linked_nm_ids.add(link.nm_id)
    # Do not display stale WB stock under the previous vendorCode of a confirmed nmID.
    for product in wb_products:
        for link in approved_links:
            if product.nm_id == link.nm_id and product.seller_article != link.current_article:
                renamed_wb_articles.add(product.seller_article)

    additional = {}
    oid = db.execute(text("SELECT NULLIF(current_setting('app.organization_id',true),'')::integer")).scalar()
    if oid is not None:
        for (name,) in db.execute(text("SELECT name FROM local_warehouses WHERE organization_id=:o AND name NOT IN ('Маркетплейс','Готовая продукция') ORDER BY id"), {"o": oid}):
            additional[name] = get_products_by_group(db, name, wb_articles, renamed_wb_articles, links_by_master, linked_nm_ids)
    return {
        "extra": additional,
        "marketplace": get_products_by_group(
            db,
            "Маркетплейс",
            wb_articles,
            renamed_wb_articles,
            links_by_master,
            linked_nm_ids,
        ),

        "finished": get_products_by_group(
            db,
            "Готовая продукция",
            wb_articles,
            renamed_wb_articles,
            links_by_master,
            linked_nm_ids,
        ),
    }
