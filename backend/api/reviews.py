from datetime import date, datetime, time, timedelta
from typing import Literal

from fastapi import APIRouter, Depends, Query
from sqlalchemy import and_, cast, func, not_, or_
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Session

from backend.dependencies import get_db
from backend.models.wb_review import WBReview


router = APIRouter(
    prefix="/wb/reviews",
    tags=["WB Отзывы"],
)


ReviewStatus = Literal["unanswered", "rating_only", "answered", "all"]
UNANSWERED_FROM = datetime(2026, 1, 1)


def _has_review_content():
    """Есть содержимое, ради которого отзыв требует реакции: текст/плюсы/минусы или фото."""
    photo_json = cast(WBReview.photo_links, JSONB)
    return or_(
        func.length(func.btrim(func.coalesce(WBReview.text, ""))) > 0,
        func.length(func.btrim(func.coalesce(WBReview.pros, ""))) > 0,
        func.length(func.btrim(func.coalesce(WBReview.cons, ""))) > 0,
        func.jsonb_array_length(photo_json) > 0,
    )


def _is_rating_only():
    return and_(
        WBReview.rating.is_not(None),
        not_(_has_review_content()),
    )


def _is_actionable_unanswered():
    return and_(
        WBReview.seller_has_answer.is_(False),
        _has_review_content(),
        WBReview.created_at >= UNANSWERED_FROM,
    )


def _serialize_review(item: WBReview) -> dict:
    return {
        "id": item.feedback_id,
        "text": item.text or "",
        "pros": item.pros or "",
        "cons": item.cons or "",
        "rating": item.rating,
        "created_at": item.created_at.isoformat() if item.created_at else None,
        "buyer_name": item.buyer_name or "",
        "is_answered": bool(item.seller_has_answer),
        "answer": (
            {
                "text": item.answer_text or "",
                "state": item.answer_state,
                "editable": bool(item.answer_editable),
            }
            if item.seller_has_answer
            else None
        ),
        "article": item.article,
        "nm_id": int(item.nm_id) if item.nm_id is not None else None,
        "product_name": item.product_name,
        "brand_name": item.brand_name,
        "subject_name": item.subject_name,
        "color": item.color,
        "photo_links": item.photo_links or [],
        "was_viewed": bool(item.was_viewed),
        "bables": item.bables or [],
    }


@router.get("", summary="Получить отзывы WB из БД")
def get_reviews(
    status: ReviewStatus = Query("unanswered"),
    nm_id: int | None = Query(None),
    article: str | None = Query(None),
    rating: int | None = Query(None, ge=1, le=5),
    date_from: date | None = Query(None),
    date_to: date | None = Query(None),
    take: int = Query(100, ge=1, le=100),
    skip: int = Query(0, ge=0),
    order: Literal["dateAsc", "dateDesc"] = Query("dateDesc"),
    db: Session = Depends(get_db),
):
    query = db.query(WBReview)

    if status == "unanswered":
        query = query.filter(_is_actionable_unanswered())
    elif status == "rating_only":
        query = query.filter(_is_rating_only(), WBReview.seller_has_answer.is_(False))
    elif status == "answered":
        query = query.filter(WBReview.seller_has_answer.is_(True))

    if nm_id is not None:
        query = query.filter(WBReview.nm_id == nm_id)

    if article and article.strip():
        query = query.filter(WBReview.article.ilike(f"%{article.strip()}%"))

    if rating is not None:
        query = query.filter(WBReview.rating == rating)

    if date_from is not None:
        query = query.filter(
            WBReview.created_at >= datetime.combine(date_from, time.min)
        )

    if date_to is not None:
        query = query.filter(
            WBReview.created_at < datetime.combine(date_to + timedelta(days=1), time.min)
        )

    if order == "dateAsc":
        query = query.order_by(WBReview.created_at.asc(), WBReview.id.asc())
    else:
        query = query.order_by(WBReview.created_at.desc(), WBReview.id.desc())

    total_filtered = query.count()
    unanswered_total = (
        db.query(func.count(WBReview.id))
        .filter(_is_actionable_unanswered())
        .scalar()
        or 0
    )

    rows = query.offset(skip).limit(take).all()

    return {
        "status": "ok",
        "source": "DB",
        "status_filter": status,
        "take": take,
        "skip": skip,
        "order": order,
        "count_unanswered": int(unanswered_total),
        "count_filtered": int(total_filtered),
        "reviews": [_serialize_review(item) for item in rows],
    }
