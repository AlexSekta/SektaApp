import os
import threading
import time

from backend.auth.tenant import (
    clear_tenant_context,
    legacy_sync_organization_id,
    reset_app_db_role,
    set_app_db_role,
    set_tenant_context,
)
from backend.database import SessionLocal
from backend.logging_config import get_logger
from backend.services.wb_question_response_monitor import (
    ensure_wb_question_response_monitor_schema,
    monitor_wb_question_responses,
)

logger = get_logger("wb_question_response_monitor_scheduler")
_started = False
_stop_event = threading.Event()
_lock = threading.Lock()


def _interval_minutes():
    try:
        return max(
            2,
            int(os.getenv("WB_QUESTION_RESPONSE_MONITOR_INTERVAL_MINUTES", "2")),
        )
    except ValueError:
        return 2


def _run_once(reason):
    db = SessionLocal()
    try:
        organization_id = legacy_sync_organization_id()
        if organization_id is None:
            logger.info(
                "WB_QUESTION_RESPONSE_MONITOR_SKIPPED_NO_ORGANIZATION | reason=%s",
                reason,
            )
            return

        set_app_db_role(db)
        set_tenant_context(db, organization_id)

        result = monitor_wb_question_responses(
            db,
            organization_id,
        )

        logger.info(
            "WB_QUESTION_RESPONSE_MONITOR_RUN | reason=%s current=%s "
            "new=%s left=%s finalized=%s",
            reason,
            result.get("current_unanswered"),
            result.get("new_tracked"),
            result.get("left_queue"),
            result.get("answered_finalized"),
        )

    except Exception:
        db.rollback()
        logger.exception(
            "WB_QUESTION_RESPONSE_MONITOR_FAILED | reason=%s",
            reason,
        )

    finally:
        clear_tenant_context(db)
        reset_app_db_role(db)
        db.close()


def _loop():
    time.sleep(14)
    _run_once("startup")

    while not _stop_event.wait(_interval_minutes() * 60):
        _run_once("scheduled")


def start_wb_question_response_monitor_scheduler():
    global _started

    with _lock:
        if _started:
            return
        _started = True

    ensure_wb_question_response_monitor_schema()

    logger.info(
        "WB_QUESTION_RESPONSE_MONITOR_STARTED | interval_minutes=%s",
        _interval_minutes(),
    )

    threading.Thread(
        target=_loop,
        name="wb-question-response-monitor",
        daemon=True,
    ).start()


def stop_wb_question_response_monitor_scheduler():
    _stop_event.set()
