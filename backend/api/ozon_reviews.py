from typing import Literal

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from backend.dependencies import get_db

from backend.marketplaces.ozon.client import OzonAPIError, OzonClient
from backend.services.marketplace_clients import get_ozon_client


router = APIRouter(
    prefix="/ozon/reviews",
    tags=["Ozon — Отзывы"],
)

Status = Literal["unanswered", "answered", "all"]

STATUS_MAP: dict[Status, str] = {
    "unanswered": "UNPROCESSED",
    "answered": "PROCESSED",
    "all": "ALL",
}


def normalize_review(item: dict, product: dict | None = None) -> dict:
    """Привести ответ Ozon Review API к формату приложения."""
    product = product or {}
    status = str(item.get("status") or "").upper()

    return {
        "id": str(item.get("id") or ""),
        "text": item.get("text") or "",
        "rating": item.get("rating"),
        "created_at": item.get("published_at"),
        "is_answered": status == "PROCESSED",
        "status": status,
        "sku": item.get("sku"),
        "article": product.get("offer_id"),
        "product_name": product.get("name"),
        "photos_amount": int(item.get("photos_amount") or 0),
        "videos_amount": int(item.get("videos_amount") or 0),
        "comments_amount": int(item.get("comments_amount") or 0),
        "order_status": item.get("order_status"),
    }


def get_products_for_reviews(
    client: OzonClient,
    reviews: list[dict],
) -> dict[str, dict]:
    """Получить карточки товаров для SKU, встречающихся в отзывах."""
    skus = list({
        str(item.get("sku"))
        for item in reviews
        if item.get("sku") is not None
    })

    if not skus:
        return {}

    data = client.get_review_product_info(skus)
    result: dict[str, dict] = {}

    for item in data.get("items", []):
        if item.get("sku") is not None:
            result[str(item["sku"])] = item

    return result


def get_ozon_reviews_data(
    status: Status = "unanswered",
    limit: int = 100,
    db: Session | None = None,
) -> dict:
    """Получить отзывы Ozon и нормализовать их для frontend.

    Только чтение. Отправка ответа продавца намеренно не реализована.
    """
    if db is None:
        raise RuntimeError("Для работы с Ozon требуется DB-сессия текущей организации")

    client = get_ozon_client(db)

    try:
        count_data = client.get_review_count_v1()

        new_count = int(count_data.get("new") or 0)
        viewed_count = int(count_data.get("viewed") or 0)
        processed_count = int(count_data.get("processed") or 0)
        total_count = int(count_data.get("total") or 0)

        response = client.get_reviews_v1(
            status=STATUS_MAP[status],
            limit=limit,
            sort_dir="DESC",
        )

        raw_reviews = response.get("reviews", [])
        products = get_products_for_reviews(client, raw_reviews)

        reviews = [
            normalize_review(
                item,
                products.get(str(item.get("sku"))),
            )
            for item in raw_reviews
        ]

        return {
            "status": "ok",
            "source": "OZON",
            "status_filter": status,
            "count_unanswered": new_count + viewed_count,
            "count_answered": processed_count,
            "count_all": total_count,
            "reviews": reviews,
            "has_next": bool(response.get("has_next")),
            "last_id": response.get("last_id"),
        }

    except OzonAPIError as error:
        return {
            "status": "error",
            "http_status": error.status_code,
            "message": error.message,
        }

    except Exception as error:
        return {
            "status": "error",
            "message": str(error),
        }


@router.get(
    "",
    summary="Получить отзывы Ozon",
    description=(
        "Получает отзывы Ozon с фильтрацией по статусу. "
        "На текущем этапе endpoint только читает данные; "
        "отправка ответа продавца не выполняется."
    ),
)
def get_ozon_reviews(
    status: Status = Query(
        "unanswered",
        description="Фильтр: без ответа, с ответом или все отзывы.",
    ),
    limit: int = Query(
        100,
        ge=1,
        le=100,
        description="Количество отзывов за запрос.",
    ),
    db: Session = Depends(get_db),
):
    return get_ozon_reviews_data(status=status, limit=limit, db=db)
