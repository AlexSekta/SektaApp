from datetime import date, datetime

from sqlalchemy.orm import Session

from backend.models.product import Product
from backend.models.stock_history import StockHistory
from backend.models.warehouse import Warehouse
from backend.auth.tenant import set_app_db_role, set_tenant_context
from backend.services.marketplace_clients import get_wb_client, get_ozon_client, get_yandex_client

from backend.marketplaces.wb.client import WBClient

# =========================================================
# WB — ОСТАТКИ ОДНОГО FBS СКЛАДА
# =========================================================


def sync_wb_stocks(
    db: Session,
    warehouse_id: str,
    warehouse_name: str,
):

    client = get_wb_client(db)

    products = db.query(Product).all()

    skus = [product.barcode for product in products if product.barcode]

    if not skus:
        return 0

    response = client.get_stocks(
        warehouse_id,
        skus,
    )

    stocks = response.get(
        "stocks",
        [],
    )

    product_map = {product.barcode: product for product in products if product.barcode}

    today = date.today()
    saved = 0

    for item in stocks:

        sku = item.get("sku")

        if not sku:
            continue

        product = product_map.get(sku)

        if not product:
            continue

        stock_value = item.get(
            "amount",
            0,
        )

        existing = (
            db.query(StockHistory)
            .filter(
                StockHistory.date == today,
                StockHistory.marketplace == "WB",
                StockHistory.warehouse_id == str(warehouse_id),
                StockHistory.sku == str(sku),
            )
            .first()
        )

        if existing:

            existing.stock = stock_value
            existing.created_at = datetime.utcnow()

        else:

            history = StockHistory(
                date=today,
                marketplace="WB",
                warehouse_id=str(warehouse_id),
                warehouse_name=warehouse_name,
                warehouse_type="SELLER",
                seller_article=product.seller_article,
                nm_id=product.nm_id,
                sku=str(sku),
                stock=stock_value,
                created_at=datetime.utcnow(),
            )

            db.add(history)

        saved += 1

    db.commit()

    return saved


# =========================================================
# WB — ВСЕ FBS СКЛАДЫ
# =========================================================


def sync_all_wb_stocks(
    db: Session,
):
    """
    Синхронизирует все WB FBS-склады независимо.

    Ошибка одного склада не должна отменять уже успешно сохранённые
    склады. После rollback восстанавливаем tenant context.
    """

    tenant_raw = db.connection().exec_driver_sql(
        "SELECT current_setting('app.organization_id', true)"
    ).scalar()

    try:
        tenant_id = int(str(tenant_raw or "").strip())
    except (TypeError, ValueError):
        raise RuntimeError(
            "Не установлен organization_id для текущей сессии БД."
        )

    def restore_tenant_context():
        set_app_db_role(db)
        set_tenant_context(db, tenant_id)

    warehouses = (
        db.query(Warehouse)
        .filter(Warehouse.marketplace == "WB")
        .all()
    )

    total_saved = 0
    errors = []
    warehouses_ok = 0

    for warehouse in warehouses:
        warehouse_name = (
            warehouse.warehouse_name
            or str(warehouse.warehouse_id)
        )

        try:
            restore_tenant_context()

            saved = sync_wb_stocks(
                db,
                warehouse_id=warehouse.warehouse_id,
                warehouse_name=warehouse.warehouse_name,
            )

            total_saved += int(saved or 0)
            warehouses_ok += 1

        except Exception as error:
            db.rollback()
            restore_tenant_context()

            errors.append(
                {
                    "warehouse_id": str(warehouse.warehouse_id),
                    "warehouse_name": warehouse_name,
                    "error": str(error),
                }
            )

    return {
        "saved": total_saved,
        "warehouses_total": len(warehouses),
        "warehouses_ok": warehouses_ok,
        "warehouses_failed": len(errors),
        "errors": errors,
    }


# =========================================================
# WB — FBO (склады Wildberries) через Analytics API
# =========================================================


def sync_wb_fbo_stocks(
    db: Session,
):

    client = get_wb_client(db)

    products = (
        db.query(Product)
        .filter(
            Product.nm_id.isnot(None),
        )
        .all()
    )

    nm_ids = [
        int(product.nm_id)
        for product in products
        if product.nm_id is not None
    ]

    if not nm_ids:
        return 0

    product_map = {
        int(product.nm_id): product
        for product in products
        if product.nm_id is not None
    }

    response = client.get_fbw_stocks(
        nm_ids
    )

    items = (
        response
        .get("data", {})
        .get("items", [])
    )

    today = date.today()
    saved = 0

    for item in items:

        nm_id = item.get("nmId")

        warehouse_id = item.get(
            "warehouseId"
        )

        warehouse_name = item.get(
            "warehouseName"
        )

        if nm_id is None:
            continue

        if warehouse_id is None:
            continue

        product = product_map.get(
            int(nm_id)
        )

        if not product:
            continue

        stock_value = item.get(
            "quantity",
            0,
        )

        if stock_value is None:
            stock_value = 0

        stock_value = int(
            stock_value
        )

        # Метод возвращает одну строку на размер товара + склад.
        # Используем chrtId как sku, чтобы не потерять размеры.
        chrt_id = item.get(
            "chrtId"
        )

        sku_string = str(
            chrt_id
            if chrt_id is not None
            else product.barcode
            or product.seller_article
        )

        warehouse_id_string = str(
            warehouse_id
        )

        existing = (
            db.query(StockHistory)
            .filter(
                StockHistory.date == today,
                StockHistory.marketplace == "WB",
                StockHistory.warehouse_id == warehouse_id_string,
                StockHistory.sku == sku_string,
            )
            .first()
        )

        if existing:

            existing.stock = stock_value
            existing.warehouse_name = (
                warehouse_name
                or existing.warehouse_name
            )
            existing.warehouse_type = "FBO"
            existing.seller_article = product.seller_article
            existing.nm_id = product.nm_id
            existing.created_at = datetime.utcnow()

        else:

            history = StockHistory(
                date=today,
                marketplace="WB",
                warehouse_id=warehouse_id_string,
                warehouse_name=warehouse_name or "WB",
                warehouse_type="FBO",
                seller_article=product.seller_article,
                nm_id=product.nm_id,
                sku=sku_string,
                stock=stock_value,
                created_at=datetime.utcnow(),
            )

            db.add(history)

        saved += 1

    db.commit()

    return saved


# =========================================================
# OZON — FBS
# =========================================================


def sync_ozon_fbs_stocks(
    db: Session,
):

    client = get_ozon_client(db)

    response = client.get_fbs_stocks()

    products = response.get(
        "products",
        [],
    )

    today = date.today()
    saved = 0

    for item in products:

        offer_id = item.get("offer_id")

        sku = item.get("sku")

        warehouse_id = item.get("warehouse_id")

        warehouse_name = item.get("warehouse_name")

        stock_value = item.get(
            "free_stock",
            0,
        )

        product_id = item.get("product_id")

        if not offer_id:
            continue

        if sku is None:
            continue

        if warehouse_id is None:
            continue

        sku_string = str(sku)

        warehouse_id_string = str(warehouse_id)

        existing = (
            db.query(StockHistory)
            .filter(
                StockHistory.date == today,
                StockHistory.marketplace == "OZON",
                StockHistory.warehouse_id == warehouse_id_string,
                StockHistory.sku == sku_string,
            )
            .first()
        )

        if existing:

            existing.stock = stock_value
            existing.warehouse_name = warehouse_name
            existing.warehouse_type = "FBS"
            existing.seller_article = offer_id
            existing.nm_id = product_id
            existing.created_at = datetime.utcnow()

        else:

            history = StockHistory(
                date=today,
                marketplace="OZON",
                warehouse_id=warehouse_id_string,
                warehouse_name=warehouse_name,
                warehouse_type="FBS",
                seller_article=offer_id,
                nm_id=product_id,
                sku=sku_string,
                stock=stock_value,
                created_at=datetime.utcnow(),
            )

            db.add(history)

        saved += 1

    db.commit()

    return saved


# =========================================================
# OZON — FBO
# =========================================================


def sync_ozon_fbo_stocks(
    db: Session,
):

    client = get_ozon_client(db)

    # Получаем FBO остатки
    response = client.get_fbo_stocks()

    result = response.get(
        "result",
        {},
    )

    rows = result.get(
        "rows",
        [],
    )

    # Получаем каталог Ozon,
    # чтобы связать SKU с product_id
    products_response = client.get_products()

    products = products_response.get(
        "items",
        [],
    )

    # SKU -> product_id
    product_id_map = {
        str(product.get("sku")): product.get("product_id")
        for product in products
        if (product.get("sku") is not None and product.get("product_id") is not None)
    }

    today = date.today()

    saved = 0
    skipped = 0

    for item in rows:

        offer_id = item.get("item_code")

        sku = item.get("sku")

        warehouse_name = item.get("warehouse_name")

        stock_value = item.get(
            "free_to_sell_amount",
            0,
        )

        if not offer_id:
            skipped += 1
            continue

        if sku is None:
            skipped += 1
            continue

        if not warehouse_name:
            skipped += 1
            continue

        sku_string = str(sku)

        # Находим product_id Ozon
        product_id = product_id_map.get(sku_string)

        # nm_id в нашей БД NOT NULL,
        # поэтому запись без product_id не сохраняем
        if product_id is None:
            skipped += 1
            continue

        # У analytics endpoint нет warehouse_id,
        # поэтому пока используем имя склада
        warehouse_id_string = f"OZON_FBO_{warehouse_name}"

        existing = (
            db.query(StockHistory)
            .filter(
                StockHistory.date == today,
                StockHistory.marketplace == "OZON",
                StockHistory.warehouse_id == warehouse_id_string,
                StockHistory.sku == sku_string,
            )
            .first()
        )

        if existing:

            existing.stock = stock_value
            existing.warehouse_name = warehouse_name
            existing.warehouse_type = "FBO"
            existing.seller_article = offer_id
            existing.nm_id = product_id
            existing.created_at = datetime.utcnow()

        else:

            history = StockHistory(
                date=today,
                marketplace="OZON",
                warehouse_id=warehouse_id_string,
                warehouse_name=warehouse_name,
                warehouse_type="FBO",
                seller_article=offer_id,
                nm_id=product_id,
                sku=sku_string,
                stock=stock_value,
                created_at=datetime.utcnow(),
            )

            db.add(history)

        saved += 1

    db.commit()

    return saved


# =========================================================
# YANDEX — ОСТАТКИ ОДНОГО МАГАЗИНА
# AVAILABLE = ДОСТУПНЫЙ К ПРОДАЖЕ ОСТАТОК
# =========================================================


def sync_yandex_campaign_stocks(
    db: Session,
    campaign_id: int,
    warehouse_type: str,
):

    client = get_yandex_client(db)

    response = client.get_campaign_stocks(campaign_id)

    warehouses = response.get(
        "warehouses",
        [],
    )

    today = date.today()
    saved = 0

    for warehouse in warehouses:

        warehouse_id = warehouse.get("warehouseId")

        if warehouse_id is None:
            continue

        warehouse_id_string = str(warehouse_id)

        warehouse_name = f"Yandex {warehouse_type} " f"{warehouse_id_string}"

        offers = warehouse.get(
            "offers",
            [],
        )

        for offer in offers:

            offer_id = offer.get("offerId")

            if not offer_id:
                continue

            stocks = offer.get(
                "stocks",
                [],
            )

            available_stock = 0

            for stock_item in stocks:

                if stock_item.get("type") == "AVAILABLE":

                    available_stock = int(
                        stock_item.get(
                            "count",
                            0,
                        )
                    )

                    break

            # У Яндекса в этом ответе нет отдельного SKU/product_id.
            # StockHistory требует nm_id и sku NOT NULL,
            # поэтому используем offerId как стабильный
            # идентификатор внутри интеграции Yandex.
            sku_string = str(offer_id)

            nm_id_string = str(offer_id)

            existing = (
                db.query(StockHistory)
                .filter(
                    StockHistory.date == today,
                    StockHistory.marketplace == "YANDEX",
                    StockHistory.warehouse_id == warehouse_id_string,
                    StockHistory.sku == sku_string,
                )
                .first()
            )

            if existing:

                existing.stock = available_stock

                existing.warehouse_name = warehouse_name

                existing.warehouse_type = warehouse_type

                existing.seller_article = offer_id

                existing.nm_id = nm_id_string

                existing.created_at = datetime.utcnow()

            else:

                history = StockHistory(
                    date=today,
                    marketplace="YANDEX",
                    warehouse_id=warehouse_id_string,
                    warehouse_name=warehouse_name,
                    warehouse_type=warehouse_type,
                    seller_article=offer_id,
                    nm_id=nm_id_string,
                    sku=sku_string,
                    stock=available_stock,
                    created_at=datetime.utcnow(),
                )

                db.add(history)

            saved += 1

    db.commit()

    return saved


# =========================================================
# YANDEX — FBS
# campaign 36304221
# =========================================================


def sync_yandex_fbs_stocks(
    db: Session,
):

    return sync_yandex_campaign_stocks(
        db=db,
        campaign_id=36304221,
        warehouse_type="FBS",
    )


# =========================================================
# YANDEX — FBY
# campaign 52610787
# =========================================================


def sync_yandex_fby_stocks(
    db: Session,
):

    return sync_yandex_campaign_stocks(
        db=db,
        campaign_id=52610787,
        warehouse_type="FBY",
    )


# =========================================================
# YANDEX — ВСЕ ОСТАТКИ
# =========================================================


def sync_all_yandex_stocks(
    db: Session,
):

    fbs_saved = sync_yandex_fbs_stocks(db)

    fby_saved = sync_yandex_fby_stocks(db)

    return {
        "fbs": fbs_saved,
        "fby": fby_saved,
        "total": fbs_saved + fby_saved,
    }


# =========================================================
# ОБЩАЯ НЕЗАВИСИМАЯ СИНХРОНИЗАЦИЯ
#
# Ошибка одного источника не останавливает остальные.
# Каждый шаг возвращает собственный status / saved / error.
# =========================================================


def sync_all_stocks(
    db: Session,
):
    """
    Запускает независимые синхронизации в одной request-scoped Session.

    Важно: db.rollback() откатывает не только INSERT/UPDATE, но и
    транзакционные SET ROLE / SET app.organization_id. Поэтому после
    любой ошибки обязательно восстанавливаем restricted DB role и tenant
    context перед продолжением со следующим маркетплейсом.
    """

    tenant_raw = db.connection().exec_driver_sql(
        "SELECT current_setting('app.organization_id', true)"
    ).scalar()

    try:
        tenant_id = int(str(tenant_raw or "").strip())
    except (TypeError, ValueError):
        raise RuntimeError(
            "Не установлен organization_id для текущей сессии БД."
        )

    def restore_tenant_context():
        set_app_db_role(db)
        set_tenant_context(db, tenant_id)

    result = {
        "wb": {
            "status": "pending",
            "saved": 0,
        },
        "ozon": {
            "status": "pending",
            "saved": 0,
            "fbs": {
                "status": "pending",
                "saved": 0,
            },
            "fbo": {
                "status": "pending",
                "saved": 0,
            },
        },
        "yandex": {
            "status": "pending",
            "saved": 0,
            "fbs": {
                "status": "pending",
                "saved": 0,
            },
            "fby": {
                "status": "pending",
                "saved": 0,
            },
        },
        "total": 0,
    }

    # =====================================================
    # WB
    # =====================================================

    try:
        restore_tenant_context()

        wb_fbs = sync_all_wb_stocks(db)
        wb_fbs_saved = int(wb_fbs.get("saved", 0))

        wb_fbo_saved = 0
        wb_fbo_error = None

        try:
            restore_tenant_context()
            wb_fbo_saved = int(sync_wb_fbo_stocks(db) or 0)
        except Exception as error:
            db.rollback()
            restore_tenant_context()
            wb_fbo_error = str(error)

        wb_errors = list(wb_fbs.get("errors", []))

        if wb_fbo_error:
            wb_errors.append(
                {
                    "warehouse_id": None,
                    "warehouse_name": "WB FBO",
                    "error": wb_fbo_error,
                }
            )

        wb_saved = wb_fbs_saved + wb_fbo_saved

        if not wb_errors:
            wb_status = "ok"
        elif wb_saved > 0:
            wb_status = "partial"
        else:
            wb_status = "error"

        result["wb"] = {
            "status": wb_status,
            "saved": wb_saved,
            "fbs": wb_fbs_saved,
            "fbo": wb_fbo_saved,
            "warehouses_total": wb_fbs.get("warehouses_total", 0),
            "warehouses_ok": wb_fbs.get("warehouses_ok", 0),
            "warehouses_failed": wb_fbs.get("warehouses_failed", 0),
            "errors": wb_errors,
        }

        result["total"] += wb_saved

    except Exception as error:
        db.rollback()
        restore_tenant_context()

        result["wb"] = {
            "status": "error",
            "saved": 0,
            "fbs": 0,
            "fbo": 0,
            "errors": [
                {
                    "warehouse_id": None,
                    "warehouse_name": "WB",
                    "error": str(error),
                }
            ],
        }

    # =====================================================
    # OZON FBS
    # =====================================================

    try:
        restore_tenant_context()

        ozon_fbs_saved = sync_ozon_fbs_stocks(db)

        result["ozon"]["fbs"] = {
            "status": "ok",
            "saved": ozon_fbs_saved,
        }
        result["ozon"]["saved"] += ozon_fbs_saved
        result["total"] += ozon_fbs_saved

    except Exception as error:
        db.rollback()
        restore_tenant_context()

        result["ozon"]["fbs"] = {
            "status": "error",
            "saved": 0,
            "error": str(error),
        }

    # =====================================================
    # OZON FBO
    # =====================================================

    try:
        restore_tenant_context()

        ozon_fbo_saved = sync_ozon_fbo_stocks(db)

        result["ozon"]["fbo"] = {
            "status": "ok",
            "saved": ozon_fbo_saved,
        }
        result["ozon"]["saved"] += ozon_fbo_saved
        result["total"] += ozon_fbo_saved

    except Exception as error:
        db.rollback()
        restore_tenant_context()

        result["ozon"]["fbo"] = {
            "status": "error",
            "saved": 0,
            "error": str(error),
        }

    ozon_steps = [
        result["ozon"]["fbs"]["status"],
        result["ozon"]["fbo"]["status"],
    ]

    if all(status == "ok" for status in ozon_steps):
        result["ozon"]["status"] = "ok"
    elif any(status == "ok" for status in ozon_steps):
        result["ozon"]["status"] = "partial"
    else:
        result["ozon"]["status"] = "error"

    # =====================================================
    # YANDEX FBS
    # =====================================================

    try:
        restore_tenant_context()

        yandex_fbs_saved = sync_yandex_fbs_stocks(db)

        result["yandex"]["fbs"] = {
            "status": "ok",
            "saved": yandex_fbs_saved,
        }
        result["yandex"]["saved"] += yandex_fbs_saved
        result["total"] += yandex_fbs_saved

    except Exception as error:
        db.rollback()
        restore_tenant_context()

        result["yandex"]["fbs"] = {
            "status": "error",
            "saved": 0,
            "error": str(error),
        }

    # =====================================================
    # YANDEX FBY
    # =====================================================

    try:
        restore_tenant_context()

        yandex_fby_saved = sync_yandex_fby_stocks(db)

        result["yandex"]["fby"] = {
            "status": "ok",
            "saved": yandex_fby_saved,
        }
        result["yandex"]["saved"] += yandex_fby_saved
        result["total"] += yandex_fby_saved

    except Exception as error:
        db.rollback()
        restore_tenant_context()

        result["yandex"]["fby"] = {
            "status": "error",
            "saved": 0,
            "error": str(error),
        }

    yandex_steps = [
        result["yandex"]["fbs"]["status"],
        result["yandex"]["fby"]["status"],
    ]

    if all(status == "ok" for status in yandex_steps):
        result["yandex"]["status"] = "ok"
    elif any(status == "ok" for status in yandex_steps):
        result["yandex"]["status"] = "partial"
    else:
        result["yandex"]["status"] = "error"

    # =====================================================
    # ОБЩИЙ СТАТУС
    # =====================================================

    marketplace_statuses = [
        result["wb"]["status"],
        result["ozon"]["status"],
        result["yandex"]["status"],
    ]

    if all(status == "ok" for status in marketplace_statuses):
        overall_status = "ok"
    elif all(status == "error" for status in marketplace_statuses):
        overall_status = "error"
    else:
        overall_status = "partial"

    result["status"] = overall_status
    return result
