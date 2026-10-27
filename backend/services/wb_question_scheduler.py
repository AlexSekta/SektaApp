import os
import threading
import time

from backend.database import SessionLocal
from backend.auth.tenant import clear_tenant_context, legacy_sync_organization_id, set_tenant_context, set_app_db_role, reset_app_db_role
from backend.logging_config import get_logger
from backend.services.wb_question_sync import sync_wb_questions

logger = get_logger("wb_questions_scheduler")
_started = False
_lock = threading.Lock()


def _interval_minutes() -> int:
    try:
        return max(5, int(os.getenv("WB_QUESTIONS_SYNC_INTERVAL_MINUTES", "15")))
    except ValueError:
        return 15


def _run_once(reason: str):
    db = SessionLocal()
    try:
        organization_id = legacy_sync_organization_id()
        if organization_id is None:
            logger.info("%s | reason=%s", "SCHEDULER_SKIPPED_NO_ORGANIZATION", reason)
            return
        set_app_db_role(db)
        set_tenant_context(db, organization_id)
        result = sync_wb_questions(db, force_full=False)
        logger.info(
            "WB_QUESTIONS_AUTO_SYNC_OK | reason=%s new=%s updated=%s total=%s unanswered=%s",
            reason,
            result.get("new_questions"),
            result.get("updated_questions"),
            result.get("total_questions"),
            result.get("unanswered"),
        )
    except Exception:
        db.rollback()
        logger.exception("WB_QUESTIONS_AUTO_SYNC_FAILED | reason=%s", reason)
    finally:
        clear_tenant_context(db)
        reset_app_db_role(db)
        db.close()


def _loop():
    time.sleep(10)
    _run_once("startup")
    while True:
        time.sleep(_interval_minutes() * 60)
        _run_once("scheduled")


def start_wb_questions_scheduler():
    global _started
    with _lock:
        if _started:
            return
        _started = True
    logger.info(
        "WB_QUESTIONS_SCHEDULER_STARTED | interval_minutes=%s",
        _interval_minutes(),
    )
    threading.Thread(target=_loop, name="wb-questions-sync", daemon=True).start()
