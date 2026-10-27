from fastapi import APIRouter, Depends, Query, Request, HTTPException
from sqlalchemy import and_, cast, func, not_, or_
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Session

from backend.dependencies import get_db
from backend.models.wb_review import WBReview
from backend.services.wb_review_sync import sync_wb_reviews
from backend.auth.tenant import legacy_sync_organization_id


def _has_review_content():
    photo_json = cast(WBReview.photo_links, JSONB)
    return or_(
        func.length(func.btrim(func.coalesce(WBReview.text, ""))) > 0,
        func.length(func.btrim(func.coalesce(WBReview.pros, ""))) > 0,
        func.length(func.btrim(func.coalesce(WBReview.cons, ""))) > 0,
        func.jsonb_array_length(photo_json) > 0,
    )


def _actionable_unanswered_filter():
    return and_(WBReview.seller_has_answer.is_(False), _has_review_content())


router = APIRouter(prefix="/wb/reviews", tags=["WB Отзывы"])


@router.post("/sync", summary="Синхронизировать отзывы WB с БД")
def sync_reviews(
    request: Request,
    force_full: bool = Query(False),
    db: Session = Depends(get_db),
):
    organization_id = getattr(request.state, "organization_id", None)
    if organization_id != legacy_sync_organization_id():
        raise HTTPException(
            status_code=409,
            detail="WB-кабинет для этой организации ещё не подключён. Синхронизация станет доступна после настройки подключения маркетплейса.",
        )
    return sync_wb_reviews(db, force_full=force_full)


@router.get("/db-count", summary="Статистика отзывов WB из БД")
def db_count(db: Session = Depends(get_db)):
    total = int(db.query(func.count(WBReview.id)).scalar() or 0)
    answered = int(
        db.query(func.count(WBReview.id))
        .filter(WBReview.seller_has_answer.is_(True))
        .scalar()
        or 0
    )
    unanswered = int(
        db.query(func.count(WBReview.id))
        .filter(_actionable_unanswered_filter())
        .scalar()
        or 0
    )
    rating_only = int(
        db.query(func.count(WBReview.id))
        .filter(
            WBReview.seller_has_answer.is_(False),
            WBReview.rating.is_not(None),
            not_(_has_review_content()),
        )
        .scalar()
        or 0
    )
    last_sync = db.query(func.max(WBReview.last_synced_at)).scalar()
    return {
        "status": "ok",
        "source": "DB",
        "total_reviews": total,
        "answered": answered,
        "unanswered": unanswered,
        "rating_only": rating_only,
        "last_sync": last_sync.isoformat() if last_sync else None,
    }
