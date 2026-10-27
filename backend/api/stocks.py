from datetime import datetime
import time

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from backend.dependencies import get_db
from backend.logging_config import get_logger

from backend.models.product import Product
from backend.models.warehouse import Warehouse
from backend.models.stock_history import StockHistory

from backend.marketplaces.wb.client import WBClient
from backend.services.marketplace_clients import get_wb_client, get_ozon_client, get_yandex_client, get_yandex_business_id
from backend.marketplaces.ozon.client import OzonAPIError

from backend.marketplaces.yandex.client import YandexAPIError

router = APIRouter()

logger = get_logger("stock_update")


# =========================================================
# ПОЛУЧЕНИЕ ОСТАТКОВ
# =========================================================


@router.get("/stocks")
def get_stocks(
    db: Session = Depends(get_db),
):
    stocks = db.query(StockHistory).order_by(StockHistory.created_at.desc()).all()

    return [
        {
            "date": item.created_at,
            "marketplace": item.marketplace,
            "warehouse": item.warehouse_name,
            "warehouse_type": item.warehouse_type,
            "article": item.seller_article,
            "stock": item.stock,
        }
        for item in stocks
    ]


# =========================================================
# ДАТА ПОСЛЕДНЕГО ОБНОВЛЕНИЯ
# =========================================================


@router.get("/stocks/last-update")
def get_last_update(
    db: Session = Depends(get_db),
):
    last_stock = db.query(StockHistory).order_by(StockHistory.created_at.desc()).first()

    return {"last_update": last_stock.created_at if last_stock else None}


# =========================================================
# ОБНОВЛЕНИЕ WB FBS
# =========================================================


def update_wb_stock(
    article: str,
    stock: int,
    db: Session,
):

    product = (
        db.query(Product)
        .filter(
            Product.seller_article == article
        )
        .first()
    )

    if not product:

        logger.error(
            "STOCK_UPDATE_FAILED | "
            "marketplace=WB | "
            "article=%s | "
            "requested=%s | "
            "error=product_not_found",
            article,
            stock,
        )

        return {
            "status": "error",
            "marketplace": "WB",
            "message": "Товар не найден в каталоге WB",
        }

    if not product.barcode:

        logger.error(
            "STOCK_UPDATE_FAILED | "
            "marketplace=WB | "
            "article=%s | "
            "requested=%s | "
            "error=sku_missing",
            article,
            stock,
        )

        return {
            "status": "error",
            "marketplace": "WB",
            "message": "У товара WB отсутствует SKU",
        }

    warehouse = (
        db.query(Warehouse)
        .filter(
            Warehouse.marketplace == "WB",
            Warehouse.warehouse_type == "SELLER",
        )
        .first()
    )

    if not warehouse:

        logger.error(
            "STOCK_UPDATE_FAILED | "
            "marketplace=WB | "
            "article=%s | "
            "requested=%s | "
            "error=warehouse_not_found",
            article,
            stock,
        )

        return {
            "status": "error",
            "marketplace": "WB",
            "message": "Склад WB FBS не найден",
        }

    warehouse_id = warehouse.warehouse_id
    sku = str(product.barcode)

    current_stock_record = (
        db.query(StockHistory)
        .filter(
            StockHistory.marketplace == "WB",
            StockHistory.warehouse_type == "SELLER",
            StockHistory.warehouse_id == str(warehouse_id),
            StockHistory.seller_article == article,
        )
        .order_by(
            StockHistory.created_at.desc()
        )
        .first()
    )

    current_stock = (
        int(current_stock_record.stock)
        if current_stock_record
        else None
    )

    logger.info(
        "STOCK_UPDATE_START | "
        "marketplace=WB | "
        "article=%s | "
        "old=%s | "
        "requested=%s | "
        "warehouse_id=%s",
        article,
        current_stock,
        stock,
        warehouse_id,
    )

    client = get_wb_client(db)

    # =====================================================
    # ОТПРАВЛЯЕМ НОВЫЙ ОСТАТОК
    #
    # ВАЖНО:
    # После успешного PUT WB возвращает 204.
    # Не делаем немедленный GET для проверки:
    # это лишний запрос к тому же лимиту API и именно
    # он вызывал 429 в предыдущей реализации.
    # =====================================================

    try:

        result = client.update_stocks(
            warehouse_id,
            [
                {
                    "sku": sku,
                    "amount": stock,
                }
            ],
        )

    except Exception:

        logger.exception(
            "STOCK_UPDATE_FAILED | "
            "marketplace=WB | "
            "article=%s | "
            "old=%s | "
            "requested=%s | "
            "stage=send",
            article,
            current_stock,
            stock,
        )

        return {
            "status": "error",
            "marketplace": "WB",
            "code": 500,
            "message": "Не удалось обновить остаток Wildberries.",
        }

    # =====================================================
    # WB ПРИНЯЛ PUT — ОБНОВЛЯЕМ ЛОКАЛЬНУЮ БД
    # =====================================================

    try:

        if current_stock_record:

            current_stock_record.stock = stock
            current_stock_record.created_at = datetime.utcnow()

        else:

            current_stock_record = StockHistory(
                date=datetime.utcnow().date(),
                marketplace="WB",
                warehouse_id=str(warehouse_id),
                warehouse_name=warehouse.warehouse_name,
                warehouse_type="SELLER",
                seller_article=article,
                nm_id=str(product.nm_id),
                sku=sku,
                stock=stock,
                created_at=datetime.utcnow(),
            )

            db.add(current_stock_record)

        db.commit()

    except Exception:

        db.rollback()

        logger.exception(
            "STOCK_UPDATE_DB_FAILED | "
            "marketplace=WB | "
            "article=%s | "
            "confirmed=%s",
            article,
            stock,
        )

        return {
            "status": "error",
            "marketplace": "WB",
            "code": 500,
            "message": (
                "Wildberries принял новый остаток, "
                "но не удалось сохранить его "
                "в локальной базе данных."
            ),
        }

    logger.info(
        "STOCK_UPDATE_OK | "
        "marketplace=WB | "
        "article=%s | "
        "old=%s | "
        "requested=%s | "
        "accepted=%s | "
        "verified=%s | "
        "warehouse_id=%s",
        article,
        current_stock,
        stock,
        True,
        False,
        warehouse_id,
    )

    return {
        "status": "ok",
        "marketplace": "WB",
        "article": article,
        "previous_stock": current_stock,
        "requested_stock": stock,
        "stock": stock,
        "sku": sku,
        "warehouse_id": warehouse_id,
        "warehouse_name": warehouse.warehouse_name,
        "verified": False,
        "accepted": True,
        "message": (
            "Wildberries принял новый остаток. "
            "Локальная база обновлена."
        ),
        "wb_response": result,
    }


# =========================================================
# ОБНОВЛЕНИЕ OZON FBS
# =========================================================


def update_ozon_stock(
    article: str,
    stock: int,
    db: Session,
):
    ozon_stock = (
        db.query(StockHistory)
        .filter(
            StockHistory.marketplace == "OZON",
            StockHistory.warehouse_type == "FBS",
            StockHistory.seller_article == article,
        )
        .order_by(StockHistory.created_at.desc())
        .first()
    )

    if not ozon_stock:
        logger.error(
            "STOCK_UPDATE_FAILED | "
            "marketplace=OZON | "
            "article=%s | "
            "requested=%s | "
            "error=stock_not_found",
            article,
            stock,
        )

        return {
            "status": "error",
            "marketplace": "OZON",
            "message": "Товар не найден на складе Ozon FBS",
        }

    if not ozon_stock.sku:
        logger.error(
            "STOCK_UPDATE_FAILED | "
            "marketplace=OZON | "
            "article=%s | "
            "requested=%s | "
            "error=sku_missing",
            article,
            stock,
        )

        return {
            "status": "error",
            "marketplace": "OZON",
            "message": "У товара Ozon отсутствует SKU",
        }

    if not ozon_stock.warehouse_id:
        logger.error(
            "STOCK_UPDATE_FAILED | "
            "marketplace=OZON | "
            "article=%s | "
            "requested=%s | "
            "error=warehouse_id_missing",
            article,
            stock,
        )

        return {
            "status": "error",
            "marketplace": "OZON",
            "message": "У товара Ozon отсутствует warehouse_id",
        }

    warehouse_id = int(ozon_stock.warehouse_id)
    current_stock = int(ozon_stock.stock)

    if stock == current_stock:
        logger.info(
            "STOCK_UPDATE_SKIPPED | "
            "marketplace=OZON | "
            "article=%s | "
            "stock=%s | "
            "reason=no_change",
            article,
            stock,
        )

        return {
            "status": "ok",
            "marketplace": "OZON",
            "article": article,
            "stock": stock,
            "message": "Остаток уже имеет указанное значение",
        }

    logger.info(
        "STOCK_UPDATE_START | "
        "marketplace=OZON | "
        "article=%s | "
        "old=%s | "
        "requested=%s | "
        "warehouse_id=%s",
        article,
        current_stock,
        stock,
        warehouse_id,
    )

    client = get_ozon_client(db)

    try:
        result = client.update_stocks(
            [
                {
                    "offer_id": article,
                    "stock": stock,
                    "warehouse_id": warehouse_id,
                }
            ]
        )

    except OzonAPIError as error:
        logger.error(
            "STOCK_UPDATE_FAILED | "
            "marketplace=OZON | "
            "article=%s | "
            "old=%s | "
            "requested=%s | "
            "http_status=%s | "
            "error=%s",
            article,
            current_stock,
            stock,
            error.status_code,
            error.message,
        )

        return {
            "status": "error",
            "marketplace": "OZON",
            "code": error.status_code,
            "message": error.message,
        }

    except Exception:
        logger.exception(
            "STOCK_UPDATE_FAILED | "
            "marketplace=OZON | "
            "article=%s | "
            "old=%s | "
            "requested=%s | "
            "stage=send",
            article,
            current_stock,
            stock,
        )

        return {
            "status": "error",
            "marketplace": "OZON",
            "code": 500,
            "message": "Внутренняя ошибка сервера при обновлении Ozon.",
        }

    result_items = result.get("result", [])

    if not result_items:
        logger.error(
            "STOCK_UPDATE_FAILED | "
            "marketplace=OZON | "
            "article=%s | "
            "old=%s | "
            "requested=%s | "
            "error=no_result",
            article,
            current_stock,
            stock,
        )

        return {
            "status": "error",
            "marketplace": "OZON",
            "article": article,
            "message": "Ozon не вернул результат изменения остатка",
        }

    item_result = result_items[0]

    updated = item_result.get("updated", False)
    errors = item_result.get("errors", [])

    if not updated:
        logger.error(
            "STOCK_UPDATE_FAILED | "
            "marketplace=OZON | "
            "article=%s | "
            "old=%s | "
            "requested=%s | "
            "errors=%s",
            article,
            current_stock,
            stock,
            errors,
        )

        return {
            "status": "error",
            "marketplace": "OZON",
            "article": article,
            "message": "Ozon не изменил остаток",
            "errors": errors,
        }

    try:
        confirmed_response = client.get_fbs_stocks()

    except OzonAPIError as error:
        logger.error(
            "STOCK_UPDATE_VERIFY_FAILED | "
            "marketplace=OZON | "
            "article=%s | "
            "requested=%s | "
            "http_status=%s | "
            "error=%s",
            article,
            stock,
            error.status_code,
            error.message,
        )

        return {
            "status": "error",
            "marketplace": "OZON",
            "code": error.status_code,
            "message": (
                "Ozon принял изменение, "
                "но не удалось проверить новый остаток. "
                f"{error.message}"
            ),
        }

    except Exception:
        logger.exception(
            "STOCK_UPDATE_VERIFY_FAILED | "
            "marketplace=OZON | "
            "article=%s | "
            "requested=%s",
            article,
            stock,
        )

        return {
            "status": "error",
            "marketplace": "OZON",
            "code": 500,
            "message": (
                "Ozon принял изменение, "
                "но произошла ошибка при проверке нового остатка."
            ),
        }

    confirmed_products = confirmed_response.get(
        "products",
        [],
    )

    confirmed_item = None

    for item in confirmed_products:
        item_article = item.get("offer_id")
        item_warehouse_id = item.get("warehouse_id")

        if item_article == article and str(item_warehouse_id) == str(warehouse_id):
            confirmed_item = item
            break

    if not confirmed_item:
        logger.error(
            "STOCK_UPDATE_VERIFY_FAILED | "
            "marketplace=OZON | "
            "article=%s | "
            "requested=%s | "
            "error=confirmed_stock_not_found",
            article,
            stock,
        )

        return {
            "status": "error",
            "marketplace": "OZON",
            "article": article,
            "message": (
                "Ozon подтвердил изменение, " "но новый остаток не удалось перечитать"
            ),
        }

    confirmed_free_stock = int(
        confirmed_item.get(
            "free_stock",
            0,
        )
    )

    confirmed_present = int(
        confirmed_item.get(
            "present",
            0,
        )
    )

    confirmed_reserved = int(
        confirmed_item.get(
            "reserved",
            0,
        )
    )

    ozon_stock.stock = confirmed_free_stock
    ozon_stock.created_at = datetime.utcnow()

    try:
        db.commit()

    except Exception:
        db.rollback()

        logger.exception(
            "STOCK_UPDATE_DB_FAILED | "
            "marketplace=OZON | "
            "article=%s | "
            "confirmed=%s",
            article,
            confirmed_free_stock,
        )

        return {
            "status": "error",
            "marketplace": "OZON",
            "code": 500,
            "message": (
                "Ozon обновил остаток, "
                "но не удалось сохранить новое значение в базе данных."
            ),
        }

    logger.info(
        "STOCK_UPDATE_OK | "
        "marketplace=OZON | "
        "article=%s | "
        "old=%s | "
        "requested=%s | "
        "confirmed=%s | "
        "present=%s | "
        "reserved=%s",
        article,
        current_stock,
        stock,
        confirmed_free_stock,
        confirmed_present,
        confirmed_reserved,
    )

    return {
        "status": "ok",
        "marketplace": "OZON",
        "article": article,
        "previous_stock": current_stock,
        "requested_stock": stock,
        "stock": confirmed_free_stock,
        "present": confirmed_present,
        "reserved": confirmed_reserved,
        "sku": ozon_stock.sku,
        "warehouse_id": warehouse_id,
        "warehouse_name": ozon_stock.warehouse_name,
        "verified": True,
    }


# =========================================================
# ОБНОВЛЕНИЕ YANDEX FBS
# =========================================================


def update_yandex_stock(
    article: str,
    stock: int,
    db: Session,
):

    business_id = get_yandex_business_id(db)
    campaign_id = 36304221
    warehouse_id = 420586

    # Только активный FBS-склад.
    # FBY никогда не изменяем этим методом.
    yandex_stock = (
        db.query(StockHistory)
        .filter(
            StockHistory.marketplace == "YANDEX",
            StockHistory.warehouse_type == "FBS",
            StockHistory.warehouse_id == str(warehouse_id),
            StockHistory.seller_article == article,
        )
        .order_by(StockHistory.created_at.desc())
        .first()
    )

    if not yandex_stock:

        logger.error(
            "STOCK_UPDATE_FAILED | "
            "marketplace=YANDEX | "
            "article=%s | "
            "requested=%s | "
            "error=stock_not_found",
            article,
            stock,
        )

        return {
            "status": "error",
            "marketplace": "YANDEX",
            "message": "Товар не найден на активном складе Yandex FBS",
        }

    current_stock = int(yandex_stock.stock)

    if stock == current_stock:

        logger.info(
            "STOCK_UPDATE_SKIPPED | "
            "marketplace=YANDEX | "
            "article=%s | "
            "stock=%s | "
            "reason=no_change",
            article,
            stock,
        )

        return {
            "status": "ok",
            "marketplace": "YANDEX",
            "article": article,
            "stock": stock,
            "message": "Остаток уже имеет указанное значение",
        }

    logger.info(
        "STOCK_UPDATE_START | "
        "marketplace=YANDEX | "
        "article=%s | "
        "old=%s | "
        "requested=%s | "
        "business_id=%s | "
        "campaign_id=%s | "
        "warehouse_id=%s",
        article,
        current_stock,
        stock,
        business_id,
        campaign_id,
        warehouse_id,
    )

    client = get_yandex_client(db)

    # =====================================================
    # ОТПРАВЛЯЕМ НОВЫЙ ДОСТУПНЫЙ ОСТАТОК
    #
    # Яндекс принимает изменение раньше, чем оно становится
    # видимым через GET /v3/businesses/.../offers/stocks.
    # Поэтому результат успешной записи считаем принятым
    # сразу и не блокируем локальное обновление из-за
    # временно старого AVAILABLE.
    # =====================================================

    try:

        result = client.update_partner_stocks(
            business_id=business_id,
            stocks=[
                {
                    "sku": article,
                    "partnerWarehouseId": warehouse_id,
                    "count": stock,
                }
            ],
        )

    except YandexAPIError as error:

        logger.error(
            "STOCK_UPDATE_FAILED | "
            "marketplace=YANDEX | "
            "article=%s | "
            "old=%s | "
            "requested=%s | "
            "http_status=%s | "
            "error=%s",
            article,
            current_stock,
            stock,
            error.status_code,
            error.message,
        )

        return {
            "status": "error",
            "marketplace": "YANDEX",
            "code": error.status_code,
            "message": error.message,
        }

    except Exception:

        logger.exception(
            "STOCK_UPDATE_FAILED | "
            "marketplace=YANDEX | "
            "article=%s | "
            "old=%s | "
            "requested=%s | "
            "stage=send",
            article,
            current_stock,
            stock,
        )

        return {
            "status": "error",
            "marketplace": "YANDEX",
            "code": 500,
            "message": "Внутренняя ошибка сервера при обновлении Yandex.",
        }

    # Яндекс при успешной записи возвращает стандартный status=OK.
    api_status = result.get("status")

    if api_status is not None and api_status != "OK":

        logger.error(
            "STOCK_UPDATE_FAILED | "
            "marketplace=YANDEX | "
            "article=%s | "
            "old=%s | "
            "requested=%s | "
            "error=unexpected_api_status | "
            "api_status=%s",
            article,
            current_stock,
            stock,
            api_status,
        )

        return {
            "status": "error",
            "marketplace": "YANDEX",
            "message": "Yandex не подтвердил изменение остатка",
            "yandex_response": result,
        }

    # =====================================================
    # ЯНДЕКС ПРИНЯЛ ЗАПИСЬ
    #
    # Не ждём моментального обновления AVAILABLE.
    # Seller уже принимает новое значение, а API чтения
    # может некоторое время возвращать старое.
    #
    # Поэтому локальную БД обновляем сразу запрошенным
    # значением. Следующая обычная синхронизация сверит
    # значение с фактическим остатком Yandex.
    # =====================================================

    yandex_stock.stock = stock
    yandex_stock.created_at = datetime.utcnow()

    try:

        db.commit()

    except Exception:

        db.rollback()

        logger.exception(
            "STOCK_UPDATE_DB_FAILED | "
            "marketplace=YANDEX | "
            "article=%s | "
            "requested=%s",
            article,
            stock,
        )

        return {
            "status": "error",
            "marketplace": "YANDEX",
            "code": 500,
            "message": (
                "Yandex принял новый остаток, "
                "но не удалось сохранить новое значение в локальной базе."
            ),
        }

    logger.info(
        "STOCK_UPDATE_ACCEPTED | "
        "marketplace=YANDEX | "
        "article=%s | "
        "old=%s | "
        "requested=%s | "
        "warehouse_id=%s",
        article,
        current_stock,
        stock,
        warehouse_id,
    )

    return {
        "status": "ok",
        "marketplace": "YANDEX",
        "article": article,
        "previous_stock": current_stock,
        "requested_stock": stock,
        "stock": stock,
        "business_id": business_id,
        "campaign_id": campaign_id,
        "warehouse_id": warehouse_id,
        "warehouse_name": yandex_stock.warehouse_name,
        "warehouse_type": "FBS",
        "verified": False,
        "accepted": True,
        "message": (
            "Yandex принял новый остаток. "
            "Локальная база обновлена."
        ),
        "yandex_response": result,
    }


# =========================================================
# РУЧНОЕ ИЗМЕНЕНИЕ ОСТАТКА
# =========================================================


@router.put("/stocks/update")
def update_stock(
    data: dict,
    db: Session = Depends(get_db),
):
    article = data.get("article")
    marketplace = data.get("marketplace")
    stock = data.get("stock")

    if not article:
        logger.warning("STOCK_UPDATE_REJECTED | " "reason=article_missing")

        return {
            "status": "error",
            "message": "Не указан артикул",
        }

    article = str(article).strip()

    if not marketplace:
        logger.warning(
            "STOCK_UPDATE_REJECTED | " "article=%s | " "reason=marketplace_missing",
            article,
        )

        return {
            "status": "error",
            "message": "Не указан маркетплейс",
        }

    marketplace = str(marketplace).strip().upper()

    if stock is None:
        logger.warning(
            "STOCK_UPDATE_REJECTED | "
            "marketplace=%s | "
            "article=%s | "
            "reason=stock_missing",
            marketplace,
            article,
        )

        return {
            "status": "error",
            "message": "Не указан остаток",
        }

    try:
        stock = int(stock)

    except (TypeError, ValueError):
        logger.warning(
            "STOCK_UPDATE_REJECTED | "
            "marketplace=%s | "
            "article=%s | "
            "value=%s | "
            "reason=invalid_stock",
            marketplace,
            article,
            stock,
        )

        return {
            "status": "error",
            "message": "Некорректное значение остатка",
        }

    if stock < 0:
        logger.warning(
            "STOCK_UPDATE_REJECTED | "
            "marketplace=%s | "
            "article=%s | "
            "value=%s | "
            "reason=negative_stock",
            marketplace,
            article,
            stock,
        )

        return {
            "status": "error",
            "message": "Остаток не может быть отрицательным",
        }

    if marketplace == "WB":
        return update_wb_stock(
            article=article,
            stock=stock,
            db=db,
        )

    if marketplace == "OZON":
        return update_ozon_stock(
            article=article,
            stock=stock,
            db=db,
        )

    if marketplace == "YANDEX":
        return update_yandex_stock(
            article=article,
            stock=stock,
            db=db,
        )

    logger.warning(
        "STOCK_UPDATE_REJECTED | "
        "marketplace=%s | "
        "article=%s | "
        "requested=%s | "
        "reason=unsupported_marketplace",
        marketplace,
        article,
        stock,
    )

    return {
        "status": "error",
        "message": (f"Изменение остатков для " f"{marketplace} пока не поддерживается"),
    }
