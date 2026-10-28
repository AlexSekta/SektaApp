from fastapi import FastAPI, Depends
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy.orm import Session

from backend.logging_config import get_logger
from backend.database import test_connection
from backend.auth.middleware import AuthenticationMiddleware
from backend.auth.tenant import ensure_multitenancy_schema, ensure_marketplace_connections_schema, ensure_team_schema
from backend.dependencies import get_db

from backend.marketplaces.wb.client import WBClient

from backend.services.product_service import save_products
from backend.services.stock_service import (
    sync_wb_stocks,
    sync_all_wb_stocks,
    sync_all_stocks,
)
from backend.services.warehouse_service import save_warehouses
from backend.services.stock_history_schema import ensure_stock_history_warehouse_id_schema

from backend.api.stocks import router as stocks_router
from backend.api.local_warehouses import router as local_warehouse_router
from backend.services.local_warehouse_schema import ensure_local_warehouses, ensure_stock_view_settings
from backend.api.stock_view_settings import router as stock_view_settings_router
from backend.api.sync_status import router as sync_status_router
from backend.api.master_products import router as master_products_router
from backend.api.registry import router as registry_router
from backend.api.ozon import router as ozon_router
from backend.api.ozon_reviews import router as ozon_reviews_router

from backend.api.yandex import router as yandex_router
from backend.api.yandex_reviews import router as yandex_reviews_router
from backend.api.yandex_questions import router as yandex_questions_router
from backend.api.one_c import router as one_c_router
from backend.api.analytics import router as analytics_router
from backend.api.wb_sales_funnel_probe import router as wb_sales_funnel_probe_router
from backend.api.wb_sales_daily import router as wb_sales_daily_router
from backend.services.wb_sales_schema import ensure_wb_sales_table
from backend.services.wb_sales_live_scheduler import start_wb_sales_live_scheduler, stop_wb_sales_live_scheduler
from backend.services.wb_sales_history_scheduler import (
    ensure_wb_sales_history_schema, start_wb_sales_history_scheduler, stop_wb_sales_history_scheduler,
)
from backend.api.reviews import router as reviews_router
from backend.api.questions import router as questions_router
from backend.services.yandex_question_scheduler import (
    start_yandex_question_scheduler,
    stop_yandex_question_scheduler,
)

from backend.api.wb_review_sync_api import router as wb_review_sync_router
from backend.services.wb_review_scheduler import start_wb_reviews_scheduler
from backend.api.wb_question_sync_api import router as wb_question_sync_router
from backend.services.wb_question_scheduler import start_wb_questions_scheduler
from backend.api.yandex_review_sync_api import router as yandex_review_sync_router
from backend.api.auth import router as auth_router
from backend.api.marketplace_connections import router as marketplace_connections_router
from backend.api.organization import router as organization_router
from backend.api.team import router as team_router
from backend.services.yandex_review_scheduler import start_yandex_reviews_scheduler
from backend.services.ozon_order_sync import ensure_ozon_order_tables
from backend.services.ozon_event_sync import ensure_event_tables
from backend.services.ozon_event_scheduler import start_ozon_event_scheduler, stop_ozon_event_scheduler
from backend.services.ozon_order_scheduler import start_ozon_order_scheduler, stop_ozon_order_scheduler
from backend.services.ozon_order_history_scheduler import (verify_ozon_order_history_schema, start_ozon_order_history_scheduler, stop_ozon_order_history_scheduler)
from backend.services.ozon_sales_history_scheduler import verify_ozon_sales_history_schema, start_ozon_sales_history_scheduler, stop_ozon_sales_history_scheduler
from backend.services.ozon_sales_scheduler import (
    start_ozon_sales_scheduler,
    stop_ozon_sales_scheduler,
)
from backend.services.wb_question_response_monitor_scheduler import (
    start_wb_question_response_monitor_scheduler,
    stop_wb_question_response_monitor_scheduler,
)

from backend.services.wb_review_response_monitor_scheduler import (
    start_wb_review_response_monitor_scheduler,
    stop_wb_review_response_monitor_scheduler,
)

from backend.services.yandex_review_response_monitor_scheduler import (
    start_yandex_review_response_monitor_scheduler,
    stop_yandex_review_response_monitor_scheduler,
)

from backend.services.yandex_question_response_monitor_scheduler import (
    start_yandex_question_response_monitor_scheduler,
    stop_yandex_question_response_monitor_scheduler,
)

from backend.services.yandex_sales_order_sync import verify_yandex_sales_schema
from backend.services.yandex_sales_order_scheduler import start_yandex_sales_order_scheduler, stop_yandex_sales_order_scheduler
from backend.services.yandex_sales_history_scheduler import verify_yandex_sales_history_schema, start_yandex_sales_history_scheduler, stop_yandex_sales_history_scheduler

from backend.api.payouts_dashboard import router as payouts_dashboard_router
from backend.api.wb_finance_reports import router as wb_finance_reports_router
from backend.api.penalties_dashboard import router as penalties_dashboard_router
from backend.services.wb_finance_worker import start_wb_finance_worker, stop_wb_finance_worker

logger = get_logger("backend")


app = FastAPI(
    title="Marketplace Analytics API",
    description=("API для работы с товарами, остатками " "и маркетплейсами"),
    version="1.0.0",
    openapi_tags=[
        {
            "name": "Система",
            "description": "Состояние backend и подключение к базе данных",
        },
        {
            "name": "WB — Товары",
            "description": "Товары Wildberries и их синхронизация",
        },
        {
            "name": "WB — Склады",
            "description": "Склады Wildberries и их синхронизация",
        },
        {
            "name": "WB — Остатки",
            "description": "Получение и синхронизация остатков Wildberries",
        },
        {
            "name": "WB Отзывы",
            "description": "Получение отзывов Wildberries. Отправка ответа пока не выполняется.",
        },
        {
            "name": "WB Вопросы",
            "description": "Получение вопросов покупателей Wildberries",
        },
        {
            "name": "Ozon — Система",
            "description": "Проверка подключения к Ozon",
        },
        {
            "name": "Ozon — Товары",
            "description": "Товары Ozon",
        },
        {
            "name": "Ozon — Склады",
            "description": "Склады Ozon",
        },
        {
            "name": "Ozon — Остатки",
            "description": "Общие, FBS и FBO остатки Ozon",
        },
        {
            "name": "Ozon — Отзывы",
            "description": "Получение отзывов Ozon. Отправка ответа пока не выполняется.",
        },
        {
            "name": "Яндекс — Кампании",
            "description": "Кампании Яндекс Маркета",
        },
        {
            "name": "Яндекс — Остатки",
            "description": "Остатки и синхронизация Яндекс Маркета",
        },
        {
            "name": "Яндекс — Склады",
            "description": "Диагностика складов Яндекс Маркета",
        },
        {
            "name": "Яндекс — Отзывы",
            "description": "Получение отзывов Яндекс Маркета. Отправка ответа пока не выполняется.",
        },
        {
            "name": "Яндекс — Вопросы",
            "description": "Получение вопросов Яндекс Маркета. Отправка ответа пока не выполняется.",
        },
        {
            "name": "Остатки",
            "description": "Общий реестр и синхронизация остатков",
        },
        {
            "name": "Реестр",
            "description": "Товары, используемые в реестре остатков",
        },
        {
            "name": "1C",
            "description": "Импорт и просмотр остатков из 1С",
        },
    ],
)


# =========================================================
# ЗАПУСК BACKEND
# =========================================================


@app.on_event("startup")
def backend_startup():

    logger.info("BACKEND_START")
    ensure_multitenancy_schema()
    ensure_team_schema()
    ensure_local_warehouses()
    ensure_stock_view_settings()
    ensure_marketplace_connections_schema()
    ensure_stock_history_warehouse_id_schema()
    start_yandex_question_scheduler()
    start_wb_reviews_scheduler()
    start_wb_review_response_monitor_scheduler()
    start_wb_question_response_monitor_scheduler()
    start_ozon_sales_scheduler()
    verify_ozon_sales_history_schema()
    start_ozon_sales_history_scheduler()
    ensure_ozon_order_tables()
    start_ozon_order_scheduler()
    verify_ozon_order_history_schema()
    start_ozon_order_history_scheduler()
    ensure_event_tables()
    start_ozon_event_scheduler()
    start_wb_questions_scheduler()
    start_yandex_reviews_scheduler()
    start_yandex_review_response_monitor_scheduler()
    start_yandex_question_response_monitor_scheduler()
    ensure_wb_sales_table()
    ensure_wb_sales_history_schema()
    start_wb_sales_history_scheduler()
    start_wb_sales_live_scheduler()
    start_wb_finance_worker()
    verify_yandex_sales_schema()
    verify_yandex_sales_history_schema()
    start_yandex_sales_order_scheduler()
    start_yandex_sales_history_scheduler()


@app.on_event("shutdown")
def backend_shutdown():

    stop_wb_finance_worker()
    stop_wb_sales_live_scheduler()
    stop_wb_sales_history_scheduler()
    stop_yandex_question_scheduler()
    stop_yandex_sales_order_scheduler()
    stop_yandex_sales_history_scheduler()
    stop_yandex_question_response_monitor_scheduler()
    stop_yandex_review_response_monitor_scheduler()
    stop_wb_review_response_monitor_scheduler()
    stop_wb_question_response_monitor_scheduler()
    stop_ozon_sales_history_scheduler()
    stop_ozon_sales_scheduler()
    stop_ozon_order_scheduler()
    stop_ozon_order_history_scheduler()
    stop_ozon_event_scheduler()
    logger.info("BACKEND_STOP")


# =========================================================
# AUTHENTICATION
# =========================================================

app.add_middleware(AuthenticationMiddleware)

# =========================================================
# CORS
# =========================================================

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# =========================================================
# API РОУТЫ
# =========================================================

app.include_router(local_warehouse_router)
app.include_router(stock_view_settings_router)
app.include_router(sync_status_router)
app.include_router(wb_finance_reports_router)
app.include_router(payouts_dashboard_router)
app.include_router(penalties_dashboard_router)
app.include_router(auth_router)
app.include_router(marketplace_connections_router)
app.include_router(organization_router)
app.include_router(team_router)

app.include_router(
    stocks_router,
    tags=["Остатки"],
)

app.include_router(
    master_products_router,
    tags=["Реестр"],
)

app.include_router(
    registry_router,
    tags=["Реестр"],
)

app.include_router(
    ozon_router,
)

app.include_router(
    ozon_reviews_router,
)

app.include_router(yandex_router)
app.include_router(yandex_reviews_router)
app.include_router(yandex_questions_router)

app.include_router(one_c_router)

app.include_router(analytics_router)
app.include_router(wb_sales_funnel_probe_router)
app.include_router(wb_sales_daily_router)

app.include_router(reviews_router)
app.include_router(questions_router)

app.include_router(wb_review_sync_router)
app.include_router(wb_question_sync_router)
app.include_router(yandex_review_sync_router)

# =========================================================
# СИСТЕМА
# =========================================================


@app.get(
    "/",
    tags=["Система"],
    summary="Проверить backend",
)
def root():

    return {
        "status": "ok",
        "message": "Marketplace Analytics Backend работает",
    }


@app.get(
    "/database",
    tags=["Система"],
    summary="Проверить подключение к БД",
)
def database():

    database_name = test_connection()

    return {
        "status": "ok",
        "database": database_name,
    }


# =========================================================
# WB — СКЛАДЫ
# =========================================================


@app.get(
    "/wb/warehouses",
    tags=["WB — Склады"],
    summary="Получить склады WB",
)
def wb_warehouses():

    client = WBClient()

    return client.get_warehouses()


# =========================================================
# WB — ТОВАРЫ
# =========================================================


@app.get(
    "/wb/products",
    tags=["WB — Товары"],
    summary="Получить товары WB",
)
def wb_products():

    client = WBClient()

    return client.get_products()


@app.get(
    "/wb/sync-products",
    tags=["WB — Товары"],
    summary="Синхронизировать товары WB",
)
def sync_products(
    db: Session = Depends(get_db),
):

    logger.info("WB_PRODUCT_SYNC_START")

    try:

        client = WBClient()

        data = client.get_products()

        cards = data.get(
            "cards",
            [],
        )

        save_products(
            db,
            cards,
        )

        logger.info(
            "WB_PRODUCT_SYNC_OK | saved=%s",
            len(cards),
        )

        return {
            "status": "ok",
            "saved": len(cards),
        }

    except Exception:

        db.rollback()

        logger.exception("WB_PRODUCT_SYNC_FAILED")

        raise


# =========================================================
# WB — FBO ОСТАТКИ
# =========================================================


@app.get(
    "/wb/fbo-stocks",
    tags=["WB — Остатки"],
    summary="Получить остатки WB FBO",
)
def wb_fbo_stocks():

    client = WBClient()

    return client.get_fbw_stocks()


# =========================================================
# WB — ТЕСТ ОСТАТКОВ
# =========================================================


@app.get(
    "/wb/stocks-test",
    tags=["WB — Остатки"],
    summary="Проверить получение остатков WB",
)
def stocks_test():

    client = WBClient()

    skus = ["2037425274288"]

    return client.get_stocks(
        689478,
        skus,
    )


# =========================================================
# WB — СИНХРОНИЗАЦИЯ ОСТАТКОВ
# =========================================================


@app.get(
    "/wb/sync-stocks",
    tags=["WB — Остатки"],
    summary="Синхронизировать остатки WB",
)
def wb_sync_stocks(
    db: Session = Depends(get_db),
):

    logger.info("WB_STOCK_SYNC_START | source=api")

    try:

        count = sync_wb_stocks(
            db,
            warehouse_id="689478",
            warehouse_name="Мой склад",
        )

        logger.info(
            "WB_STOCK_SYNC_OK | saved=%s",
            count,
        )

        return {
            "status": "ok",
            "saved": count,
        }

    except Exception:

        db.rollback()

        logger.exception("WB_STOCK_SYNC_FAILED | source=api")

        raise


# =========================================================
# WB — СИНХРОНИЗАЦИЯ СКЛАДОВ
# =========================================================


@app.get(
    "/wb/sync-warehouses",
    tags=["WB — Склады"],
    summary="Синхронизировать склады WB",
)
def sync_warehouses(
    db: Session = Depends(get_db),
):

    logger.info("WB_WAREHOUSE_SYNC_START")

    try:

        client = WBClient()

        data = client.get_warehouses()

        saved = save_warehouses(
            db,
            data,
        )

        logger.info(
            "WB_WAREHOUSE_SYNC_OK | saved=%s",
            saved,
        )

        return {
            "status": "ok",
            "saved": saved,
        }

    except Exception:

        db.rollback()

        logger.exception("WB_WAREHOUSE_SYNC_FAILED")

        raise


# =========================================================
# ОБЩАЯ НЕЗАВИСИМАЯ СИНХРОНИЗАЦИЯ ОСТАТКОВ
# WB + OZON + YANDEX
# =========================================================


@app.post(
    "/stocks/sync",
    tags=["Остатки"],
    summary="Обновить остатки маркетплейсов",
)
def sync_stocks_now(
    db: Session = Depends(get_db),
):

    logger.info("STOCK_SYNC_START | source=api")

    result = sync_all_stocks(db)

    status = result.get(
        "status",
        "error",
    )

    wb = result.get(
        "wb",
        {},
    )

    ozon = result.get(
        "ozon",
        {},
    )

    yandex = result.get(
        "yandex",
        {},
    )

    logger.info(
        "STOCK_SYNC_FINISH | "
        "source=api | "
        "status=%s | "
        "wb_status=%s | "
        "wb_saved=%s | "
        "wb_fbs=%s | "
        "wb_fbo=%s | "
        "wb_errors=%s | "
        "ozon_status=%s | "
        "ozon_saved=%s | "
        "yandex_status=%s | "
        "yandex_saved=%s | "
        "total=%s",
        status,
        wb.get("status"),
        wb.get("saved", 0),
        wb.get("fbs", 0),
        wb.get("fbo", 0),
        wb.get("errors", []),
        ozon.get("status"),
        ozon.get("saved", 0),
        yandex.get("status"),
        yandex.get("saved", 0),
        result.get("total", 0),
    )

    return {
        "status": status,
        "updated": result,
    }
