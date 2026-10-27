from datetime import date, datetime, time, timedelta
from typing import Literal

from fastapi import APIRouter, Depends, Query
from sqlalchemy import func
from sqlalchemy.orm import Session

from backend.dependencies import get_db
from backend.models.wb_question import WBQuestion


router = APIRouter(
    prefix="/wb/questions",
    tags=["WB Вопросы"],
)


def _serialize_question(item: WBQuestion) -> dict:
    return {
        "id": item.question_id,
        "text": item.text or "",
        "created_at": item.created_at.isoformat() if item.created_at else None,
        "is_answered": bool(item.seller_has_answer),
        "answer": (
            {
                "text": item.answer_text or "",
                "editable": bool(item.answer_editable),
                "state": item.answer_state,
                "created_at": item.answer_created_at.isoformat()
                if item.answer_created_at
                else None,
            }
            if item.seller_has_answer
            else None
        ),
        "article": item.article,
        "nm_id": int(item.nm_id) if item.nm_id is not None else None,
        "product_name": item.product_name,
        "brand_name": item.brand_name,
        "was_viewed": bool(item.was_viewed),
        "is_warned": bool(item.is_warned),
        "state": item.state,
    }


@router.get("", summary="Получить вопросы WB из БД")
def questions(
    status: Literal["unanswered", "answered", "all"] = Query("unanswered"),
    nm_id: int | None = Query(None),
    article: str | None = Query(None),
    date_from: date | None = Query(None),
    date_to: date | None = Query(None),
    take: int = Query(100, ge=1, le=10000),
    skip: int = Query(0, ge=0),
    order: Literal["dateAsc", "dateDesc"] = Query("dateDesc"),
    db: Session = Depends(get_db),
):
    query = db.query(WBQuestion)

    if status == "unanswered":
        query = query.filter(WBQuestion.seller_has_answer.is_(False))
    elif status == "answered":
        query = query.filter(WBQuestion.seller_has_answer.is_(True))

    if nm_id is not None:
        query = query.filter(WBQuestion.nm_id == nm_id)

    if article and article.strip():
        query = query.filter(WBQuestion.article.ilike(f"%{article.strip()}%"))

    if date_from is not None:
        query = query.filter(
            WBQuestion.created_at >= datetime.combine(date_from, time.min)
        )

    if date_to is not None:
        query = query.filter(
            WBQuestion.created_at < datetime.combine(date_to + timedelta(days=1), time.min)
        )

    if order == "dateAsc":
        query = query.order_by(WBQuestion.created_at.asc(), WBQuestion.id.asc())
    else:
        query = query.order_by(WBQuestion.created_at.desc(), WBQuestion.id.desc())

    total_filtered = query.count()
    unanswered_total = (
        db.query(func.count(WBQuestion.id))
        .filter(WBQuestion.seller_has_answer.is_(False))
        .scalar()
        or 0
    )

    rows = query.offset(skip).limit(take).all()

    return {
        "status": "ok",
        "source": "DB",
        "status_filter": status,
        "count_unanswered": int(unanswered_total),
        "count_filtered": int(total_filtered),
        "questions": [_serialize_question(item) for item in rows],
    }


@router.get("/count", summary="Получить количество неотвеченных вопросов WB из БД")
def count(db: Session = Depends(get_db)):
    unanswered = (
        db.query(func.count(WBQuestion.id))
        .filter(WBQuestion.seller_has_answer.is_(False))
        .scalar()
        or 0
    )
    return {
        "status": "ok",
        "source": "DB",
        "count_unanswered": int(unanswered),
    }
