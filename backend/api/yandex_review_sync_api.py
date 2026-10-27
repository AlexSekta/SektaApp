from fastapi import APIRouter, Depends, Query
from sqlalchemy import func
from sqlalchemy.orm import Session

from backend.dependencies import get_db
from backend.models.yandex_review import YandexReview
from backend.services.yandex_review_sync import ensure_yandex_review_tables, sync_yandex_reviews

router = APIRouter(prefix="/yandex/reviews", tags=["Яндекс — Отзывы"])


@router.post(
    "/sync",
    summary="Синхронизировать отзывы Яндекс Маркета с БД",
)
def sync_reviews(
    force_full: bool = Query(False, description="Полная историческая синхронизация"),
    business_id: int | None = Query(None, ge=1),
    db: Session = Depends(get_db),
):
    try:
        return sync_yandex_reviews(db, business_id=business_id, force_full=force_full)
    except Exception as error:
        db.rollback()
        return {
            "status": "error",
            "code": 500,
            "message": "Ошибка при синхронизации отзывов Яндекс Маркета.",
            "details": str(error),
        }


@router.get(
    "/db-count",
    summary="Показать состояние отзывов Яндекс Маркета в БД",
)
def reviews_db_count(
    business_id: int | None = Query(None, ge=1),
    db: Session = Depends(get_db),
):
    try:
        ensure_yandex_review_tables()
        resolved = int(business_id or 0)
        if not resolved:
            from backend.services.marketplace_clients import get_yandex_client
            from backend.services.yandex_review_sync import _resolve_business_id
            client = get_yandex_client(db)
            resolved = _resolve_business_id(client, None, db)

        base = db.query(YandexReview).filter(YandexReview.business_id == resolved)
        total = int(base.with_entities(func.count(YandexReview.id)).scalar() or 0)
        answered = int(base.filter(YandexReview.seller_has_answer.is_(True)).with_entities(func.count(YandexReview.id)).scalar() or 0)
        unanswered = int(base.filter(YandexReview.waiting_for_seller.is_(True)).with_entities(func.count(YandexReview.id)).scalar() or 0)
        last_sync = base.with_entities(func.max(YandexReview.last_synced_at)).scalar()

        return {
            "status": "ok",
            "business_id": resolved,
            "total_reviews": total,
            "answered": answered,
            "unanswered": unanswered,
            "last_sync": last_sync.isoformat() if last_sync else None,
        }
    except Exception as error:
        return {
            "status": "error",
            "code": 500,
            "message": "Ошибка при чтении состояния отзывов Яндекс Маркета из БД.",
            "details": str(error),
        }
