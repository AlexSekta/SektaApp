from datetime import date, datetime, time, timedelta
from typing import Any, Literal

from fastapi import APIRouter, Depends, Query
from sqlalchemy import and_, cast, func, not_, or_
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Session

from backend.dependencies import get_db
from backend.models.yandex_review import YandexReview
from backend.models.yandex_review_comment import YandexReviewComment

router = APIRouter(prefix="/yandex")

ReviewStatus = Literal["unanswered", "rating_only", "answered", "all"]
UNANSWERED_FROM = datetime(2026, 1, 1)


def _resolve_business_id(db: Session, business_id: int | None) -> int:
    if business_id is not None:
        return int(business_id)

    value = (
        db.query(YandexReview.business_id)
        .order_by(YandexReview.last_synced_at.desc())
        .first()
    )
    if value is None:
        raise ValueError("В БД пока нет отзывов Яндекс Маркета.")
    return int(value[0])


def _has_review_content():
    """Есть содержимое отзыва помимо самой оценки."""
    photos_json = cast(YandexReview.photos, JSONB)
    videos_json = cast(YandexReview.videos, JSONB)
    return or_(
        func.length(func.btrim(func.coalesce(YandexReview.comment, ""))) > 0,
        func.length(func.btrim(func.coalesce(YandexReview.advantages, ""))) > 0,
        func.length(func.btrim(func.coalesce(YandexReview.disadvantages, ""))) > 0,
        func.coalesce(func.jsonb_array_length(photos_json), 0) > 0,
        func.coalesce(func.jsonb_array_length(videos_json), 0) > 0,
    )


def _is_rating_only():
    return and_(
        YandexReview.rating.is_not(None),
        not_(_has_review_content()),
    )


def _is_actionable_unanswered():
    return and_(
        YandexReview.waiting_for_seller.is_(True),
        _has_review_content(),
        YandexReview.created_at >= UNANSWERED_FROM,
    )


def _serialize_comment(comment: YandexReviewComment) -> dict[str, Any]:
    return {
        "id": comment.comment_id,
        "text": comment.text or "",
        "author": comment.author or "",
        "author_type": comment.author_type,
        "status": comment.status,
        "can_modify": bool(comment.can_modify),
        "parent_id": comment.parent_id,
    }


def _serialize_review(review: YandexReview, comments: list[YandexReviewComment]) -> dict[str, Any]:
    all_comments = [_serialize_comment(comment) for comment in comments]
    seller_comments = [
        comment
        for comment in all_comments
        if str(comment.get("author_type") or "").upper() == "BUSINESS"
        or bool(comment.get("can_modify"))
    ]

    return {
        "id": str(review.feedback_id),
        "created_at": review.created_at.isoformat() if review.created_at else None,
        "need_reaction": bool(review.waiting_for_seller),
        "is_answered": bool(review.seller_has_answer),
        "author": review.author or "Покупатель",
        "offer_id": review.offer_id,
        "product_name": review.product_name,
        "order_id": review.order_id,
        "advantages": review.advantages or "",
        "disadvantages": review.disadvantages or "",
        "comment": review.comment or "",
        "rating": review.rating,
        "comments_count": int(review.comments_count or 0),
        "recommended": review.recommended,
        "paid_amount": review.paid_amount or 0,
        "photos": review.photos or [],
        "videos": review.videos or [],
        "comments": all_comments,
        "seller_comments": seller_comments,
    }


@router.get(
    "/reviews",
    tags=["Яндекс — Отзывы"],
    summary="Получить отзывы Яндекс Маркета из БД",
    description=(
        "Читает сохранённые отзывы и комментарии из локальной БД. "
        "Актуализация выполняется фоновой синхронизацией."
    ),
)
def yandex_reviews(
    status: ReviewStatus = Query("unanswered"),
    limit: int = Query(100, ge=1, le=100),
    page_token: str | None = Query(None),
    business_id: int | None = Query(None, ge=1),
    date_from: date | None = Query(None),
    date_to: date | None = Query(None),
    rating: int | None = Query(None, ge=1, le=5),
    article: str | None = Query(None),
    db: Session = Depends(get_db),
):
    try:
        resolved_business_id = _resolve_business_id(db, business_id)

        try:
            offset = max(0, int(page_token)) if page_token else 0
        except ValueError:
            offset = 0

        query = db.query(YandexReview).filter(
            YandexReview.business_id == resolved_business_id
        )

        if status == "unanswered":
            query = query.filter(_is_actionable_unanswered())
        elif status == "rating_only":
            query = query.filter(
                YandexReview.waiting_for_seller.is_(True),
                _is_rating_only(),
            )
        elif status == "answered":
            query = query.filter(YandexReview.seller_has_answer.is_(True))

        # Для рабочей очереди «Без ответа» 2026 год — минимальная дата.
        # Для остальных вкладок date_from применяется только если пользователь
        # действительно задал его вручную.
        if status == "unanswered":
            effective_from = max(date_from or UNANSWERED_FROM.date(), UNANSWERED_FROM.date())
            query = query.filter(
                YandexReview.created_at >= datetime.combine(effective_from, time.min)
            )
        elif date_from is not None:
            query = query.filter(
                YandexReview.created_at >= datetime.combine(date_from, time.min)
            )

        if date_to is not None:
            query = query.filter(
                YandexReview.created_at < datetime.combine(date_to + timedelta(days=1), time.min)
            )

        if rating is not None:
            query = query.filter(YandexReview.rating == rating)

        if article and article.strip():
            query = query.filter(YandexReview.offer_id.ilike(f"%{article.strip()}%"))

        # Сначала считаем количество без ORDER BY. PostgreSQL не разрешает
        # сортировать агрегатный COUNT по created_at, которого нет в GROUP BY.
        total = int(
            query.order_by(None)
            .with_entities(func.count(YandexReview.id))
            .scalar()
            or 0
        )
        query = query.order_by(YandexReview.created_at.desc(), YandexReview.id.desc())

        rows = query.offset(offset).limit(limit).all()

        feedback_ids = [str(row.feedback_id) for row in rows]
        comments = (
            db.query(YandexReviewComment)
            .filter(
                YandexReviewComment.business_id == resolved_business_id,
                YandexReviewComment.feedback_id.in_(feedback_ids),
            )
            .order_by(YandexReviewComment.created_at.asc(), YandexReviewComment.id.asc())
            .all()
            if feedback_ids
            else []
        )

        comments_by_feedback: dict[str, list[YandexReviewComment]] = {}
        for comment in comments:
            comments_by_feedback.setdefault(str(comment.feedback_id), []).append(comment)

        reviews = [
            _serialize_review(row, comments_by_feedback.get(str(row.feedback_id), []))
            for row in rows
        ]

        unanswered_total = int(
            db.query(func.count(YandexReview.id))
            .filter(
                YandexReview.business_id == resolved_business_id,
                _is_actionable_unanswered(),
            )
            .scalar()
            or 0
        )

        next_offset = offset + len(rows)
        next_page_token = str(next_offset) if next_offset < total else None

        return {
            "status": "ok",
            "business_id": resolved_business_id,
            "filter": status,
            "reviews": reviews,
            "next_page_token": next_page_token,
            "total_count": total,
            "count_filtered": total,
            "count_unanswered": unanswered_total,
        }

    except Exception as error:
        return {
            "status": "error",
            "code": 500,
            "message": "Внутренняя ошибка при получении отзывов Яндекс Маркета.",
            "details": str(error),
        }


@router.get(
    "/reviews/count",
    tags=["Яндекс — Отзывы"],
    summary="Получить количество отзывов без ответа из БД",
)
def yandex_reviews_count(
    business_id: int | None = Query(None, ge=1),
    db: Session = Depends(get_db),
):
    try:
        resolved_business_id = _resolve_business_id(db, business_id)
        count = (
            db.query(func.count(YandexReview.id))
            .filter(
                YandexReview.business_id == resolved_business_id,
                _is_actionable_unanswered(),
            )
            .scalar()
            or 0
        )

        return {
            "status": "ok",
            "business_id": resolved_business_id,
            "count_unanswered": int(count),
        }
    except Exception as error:
        return {
            "status": "error",
            "code": 500,
            "message": "Внутренняя ошибка при получении счётчика отзывов Яндекс Маркета.",
            "details": str(error),
        }
