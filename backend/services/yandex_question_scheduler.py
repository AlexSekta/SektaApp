import os
import threading
import time

from backend.database import SessionLocal
from backend.auth.tenant import clear_tenant_context, legacy_sync_organization_id, set_tenant_context, set_app_db_role, reset_app_db_role
from backend.logging_config import get_logger
from backend.marketplaces.yandex.client import YandexAPIError
from backend.services.marketplace_clients import get_yandex_client, get_yandex_business_id
from backend.services.yandex_question_sync import (
    ensure_yandex_question_tables,
    sync_yandex_questions,
)

logger = get_logger("yandex_question_scheduler")

DEFAULT_INTERVAL_MINUTES = 15
INITIAL_DELAY_SECONDS = 10

_scheduler_thread: threading.Thread | None = None
_stop_event = threading.Event()
_start_lock = threading.Lock()


def _interval_seconds() -> int:
    raw = os.getenv(
        "YANDEX_QUESTIONS_SYNC_INTERVAL_MINUTES",
        str(DEFAULT_INTERVAL_MINUTES),
    )
    try:
        minutes = max(1, int(raw))
    except (TypeError, ValueError):
        minutes = DEFAULT_INTERVAL_MINUTES
    return minutes * 60


def _resolve_business_id(db) -> int:
    client = get_yandex_client(db)
    return get_yandex_business_id(db, client)


def _run_sync(reason: str) -> None:
    db = SessionLocal()
    try:
        organization_id = legacy_sync_organization_id()
        if organization_id is None:
            logger.info("%s | reason=%s", "SCHEDULER_SKIPPED_NO_ORGANIZATION", reason)
            return
        set_app_db_role(db)
        set_tenant_context(db, organization_id)
        ensure_yandex_question_tables()
        business_id = _resolve_business_id(db)
        result = sync_yandex_questions(
            db,
            business_id,
            force_full=False,
        )
        logger.info(
            "YANDEX_QUESTIONS_AUTO_SYNC_OK reason=%s business_id=%s "
            "new_or_seen=%s total=%s waiting=%s seller_answered=%s errors=%s",
            reason,
            business_id,
            result.get("synced_from_api", 0),
            result.get("total_questions", 0),
            result.get("waiting_for_seller", 0),
            result.get("answered_by_seller", 0),
            len(result.get("answer_sync_errors", []) or []),
        )
    except YandexAPIError as error:
        db.rollback()
        logger.warning(
            "YANDEX_QUESTIONS_AUTO_SYNC_API_ERROR reason=%s status=%s message=%s",
            reason,
            error.status_code,
            error.message,
        )
    except Exception:
        db.rollback()
        logger.exception(
            "YANDEX_QUESTIONS_AUTO_SYNC_ERROR reason=%s",
            reason,
        )
    finally:
        clear_tenant_context(db)
        reset_app_db_role(db)
        db.close()


def _worker() -> None:
    interval = _interval_seconds()
    logger.info(
        "YANDEX_QUESTIONS_SCHEDULER_STARTED interval_minutes=%s",
        interval // 60,
    )

    if _stop_event.wait(INITIAL_DELAY_SECONDS):
        return

    while not _stop_event.is_set():
        _run_sync("scheduled")
        if _stop_event.wait(interval):
            break

    logger.info("YANDEX_QUESTIONS_SCHEDULER_STOPPED")


def start_yandex_question_scheduler() -> None:
    global _scheduler_thread

    with _start_lock:
        if _scheduler_thread and _scheduler_thread.is_alive():
            return

        _stop_event.clear()
        _scheduler_thread = threading.Thread(
            target=_worker,
            name="yandex-question-sync",
            daemon=True,
        )
        _scheduler_thread.start()


def stop_yandex_question_scheduler() -> None:
    global _scheduler_thread

    with _start_lock:
        _stop_event.set()
        thread = _scheduler_thread
        _scheduler_thread = None

    if thread and thread.is_alive():
        thread.join(timeout=5)
