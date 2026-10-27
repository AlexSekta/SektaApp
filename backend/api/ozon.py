from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from backend.dependencies import get_db
from requests import HTTPError

from backend.services.marketplace_clients import get_ozon_client

router = APIRouter(prefix="/ozon")


def error_response(error: Exception):

    if isinstance(error, HTTPError):

        response = error.response

        return {
            "status": "error",
            "http_status": response.status_code if response is not None else None,
            "message": response.text if response is not None else str(error),
        }

    return {"status": "error", "message": str(error)}


# =========================================================
# ПРОВЕРКА ПОДКЛЮЧЕНИЯ
# =========================================================


@router.get("/test", tags=["Ozon — Система"], summary="Проверить подключение к Ozon")
def test_ozon_connection(db: Session = Depends(get_db)):

    try:

        client = get_ozon_client(db)

        data = client.get_seller_info()

        return {"status": "ok", "data": data}

    except Exception as error:

        return error_response(error)


# =========================================================
# ТОВАРЫ
# =========================================================


@router.get("/products", tags=["Ozon — Товары"], summary="Получить товары Ozon")
def get_ozon_products(db: Session = Depends(get_db)):

    try:

        client = get_ozon_client(db)

        data = client.get_products()

        items = data.get("items", [])

        return {"status": "ok", "count": len(items), "items": items}

    except Exception as error:

        return error_response(error)


# =========================================================
# ОБЩИЕ ОСТАТКИ
# =========================================================


@router.get("/stocks", tags=["Ozon — Остатки"], summary="Получить остатки Ozon")
def get_ozon_stocks(db: Session = Depends(get_db)):

    try:

        client = get_ozon_client(db)

        data = client.get_stocks()

        items = data.get("items", [])

        return {"status": "ok", "count": len(items), "items": items}

    except Exception as error:

        return error_response(error)


# =========================================================
# ОСТАТКИ FBS
# =========================================================


@router.get("/fbs-stocks", tags=["Ozon — Остатки"], summary="Получить остатки Ozon FBS")
def get_ozon_fbs_stocks(db: Session = Depends(get_db)):

    try:

        client = get_ozon_client(db)

        data = client.get_fbs_stocks()

        return {"status": "ok", "data": data}

    except Exception as error:

        return error_response(error)


# =========================================================
# СКЛАДЫ
# =========================================================


@router.get("/warehouses", tags=["Ozon — Склады"], summary="Получить склады Ozon")
def get_ozon_warehouses(db: Session = Depends(get_db)):

    try:

        client = get_ozon_client(db)

        data = client.get_warehouses()

        return {"status": "ok", "data": data}

    except Exception as error:

        return error_response(error)


# =========================================================
# ОСТАТКИ FBO
# =====================================================


@router.get(
    "/fbo-stocks",
    tags=["Ozon — Остатки"],
    summary="Получить остатки Ozon FBO",
)
def get_ozon_fbo_stocks(db: Session = Depends(get_db)):

    try:

        client = get_ozon_client(db)

        data = client.get_fbo_stocks()

        return {
            "status": "ok",
            "data": data,
        }

    except Exception as error:

        return error_response(error)

# =========================================================
# LEGACY: /ozon/review
#
# Оставляем старый endpoint для обратной совместимости, но
# скрываем его из Swagger. Новый frontend использует /ozon/reviews.
# Логика получения единая.
# =========================================================


@router.get("/review", include_in_schema=False)
def get_ozon_reviews_legacy(
    status: str = "unanswered",
    limit: int = 100,
    db: Session = Depends(get_db),
):
    from backend.api.ozon_reviews import get_ozon_reviews_data

    normalized_status = (
        status
        if status in {"unanswered", "answered", "all"}
        else "unanswered"
    )
    normalized_limit = max(1, min(int(limit), 100))

    return get_ozon_reviews_data(
        status=normalized_status,
        limit=normalized_limit,
        db=db,
    )
