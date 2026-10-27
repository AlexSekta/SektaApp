from fastapi import APIRouter, Depends, Query, Request, HTTPException
from sqlalchemy.orm import Session

from backend.dependencies import get_db
from backend.models.wb_question import WBQuestion
from backend.services.wb_question_sync import sync_wb_questions
from backend.auth.tenant import legacy_sync_organization_id

router = APIRouter(prefix="/wb/questions", tags=["WB Вопросы"])


@router.post("/sync", summary="Синхронизировать вопросы WB с БД")
def sync_questions(
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
    return sync_wb_questions(db, force_full=force_full)


@router.get("/db-count", summary="Получить количество вопросов WB в БД")
def db_count(db: Session = Depends(get_db)):
    total = db.query(WBQuestion).count()
    unanswered = db.query(WBQuestion).filter(WBQuestion.seller_has_answer.is_(False)).count()
    answered = total - unanswered
    last_sync = db.query(WBQuestion.last_synced_at).order_by(WBQuestion.last_synced_at.desc()).first()
    return {
        "status": "ok",
        "source": "WB",
        "total_questions": total,
        "answered": answered,
        "unanswered": unanswered,
        "last_sync": last_sync[0].isoformat() if last_sync and last_sync[0] else None,
    }
