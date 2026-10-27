from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from backend.dependencies import get_db
from backend.services.stock_service import sync_all_yandex_stocks
from backend.services.marketplace_clients import get_yandex_client, get_yandex_business_id

from backend.marketplaces.yandex.client import YandexAPIError

router = APIRouter(
    prefix="/yandex",
)


@router.get("/campaigns", tags=["Яндекс — Кампании"], summary="Получить кампании Яндекс Маркета")
def yandex_campaigns(db: Session = Depends(get_db)):
    try:
        client = get_yandex_client(db)
        data = client.get_campaigns()

        return {
            "status": "ok",
            "data": data,
        }

    except YandexAPIError as error:
        return {
            "status": "error",
            "code": error.status_code,
            "message": error.message,
            "details": error.response_data,
        }

    except Exception as error:
        return {
            "status": "error",
            "code": 500,
            "message": "Внутренняя ошибка при работе с Яндекс Маркетом.",
            "details": str(error),
        }


@router.get("/stocks/{campaign_id}", tags=["Яндекс — Остатки"], summary="Получить остатки кампании Яндекс Маркета")
def yandex_campaign_stocks(campaign_id: int, db: Session = Depends(get_db)):
    try:
        client = get_yandex_client(db)
        data = client.get_campaign_stocks(campaign_id)

        return {
            "status": "ok",
            "data": data,
        }

    except YandexAPIError as error:
        return {
            "status": "error",
            "code": error.status_code,
            "message": error.message,
            "details": error.response_data,
        }

    except Exception as error:
        return {
            "status": "error",
            "code": 500,
            "message": "Внутренняя ошибка при получении остатков Яндекс Маркета.",
            "details": str(error),
        }


# =========================================================
# СИНХРОНИЗАЦИЯ YANDEX В STOCK_HISTORY
# FBS + FBY
# =========================================================


@router.post("/sync-stocks", tags=["Яндекс — Остатки"], summary="Синхронизировать остатки Яндекс Маркета")
def yandex_sync_stocks(
    db: Session = Depends(get_db),
):

    try:

        result = sync_all_yandex_stocks(db)

        return {
            "status": "ok",
            "updated": result,
        }

    except YandexAPIError as error:

        db.rollback()

        return {
            "status": "error",
            "code": error.status_code,
            "message": error.message,
            "details": error.response_data,
        }

    except Exception as error:

        db.rollback()

        return {
            "status": "error",
            "code": 500,
            "message": (
                "Внутренняя ошибка при синхронизации " "остатков Яндекс Маркета."
            ),
            "details": str(error),
        }


# =========================================================
# ДИАГНОСТИКА СКЛАДОВ YANDEX
# READ ONLY
#
# Проверяем оба актуальных варианта:
# v3 — кабинеты без групп складов
# v2 — кабинеты с группами складов
# =========================================================


@router.get("/warehouses", tags=["Яндекс — Склады"], summary="Получить склады Яндекс Маркета")
def yandex_warehouses(db: Session = Depends(get_db)):

    client = get_yandex_client(db)
    business_id = get_yandex_business_id(db, client)

    # Активный FBS-магазин.
    campaign_ids = [
        36304221,
    ]

    result = {
        "business_id": business_id,
        "campaign_ids": campaign_ids,
    }

    # -----------------------------------------------------
    # V3 — БЕЗ ГРУПП СКЛАДОВ
    # -----------------------------------------------------

    try:

        v3_data = client.get_partner_warehouses(business_id)

        result["v3"] = {
            "status": "ok",
            "data": v3_data,
        }

    except YandexAPIError as error:

        result["v3"] = {
            "status": "error",
            "code": error.status_code,
            "message": error.message,
            "details": error.response_data,
        }

    # -----------------------------------------------------
    # V2 — С ГРУППАМИ СКЛАДОВ
    # -----------------------------------------------------

    try:

        v2_data = client.get_grouped_warehouses(
            business_id=business_id,
            campaign_ids=campaign_ids,
        )

        result["v2"] = {
            "status": "ok",
            "data": v2_data,
        }

    except YandexAPIError as error:

        result["v2"] = {
            "status": "error",
            "code": error.status_code,
            "message": error.message,
            "details": error.response_data,
        }

    return {
        "status": "ok",
        "data": result,
    }
