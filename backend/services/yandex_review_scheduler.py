import os
import threading
import time

from backend.database import SessionLocal
from backend.auth.tenant import clear_tenant_context, legacy_sync_organization_id, set_tenant_context, set_app_db_role, reset_app_db_role
from backend.logging_config import get_logger
from backend.services.yandex_review_sync import sync_yandex_reviews

logger = get_logger("yandex_reviews_scheduler")
_started = False
_lock = threading.Lock()


def _interval_minutes():
    try:
        return max(5, int(os.getenv("YANDEX_REVIEWS_SYNC_INTERVAL_MINUTES", "15")))
    except ValueError:
        return 15


def _run_once(reason):
    db = SessionLocal()
    try:
        organization_id = legacy_sync_organization_id()
        if organization_id is None:
            logger.info("%s | reason=%s", "SCHEDULER_SKIPPED_NO_ORGANIZATION", reason)
            return
        set_app_db_role(db)
        set_tenant_context(db, organization_id)
        result = sync_yandex_reviews(db, force_full=False)
        logger.info(
            "YANDEX_REVIEWS_AUTO_SYNC_OK | reason=%s new=%s updated=%s total=%s unanswered=%s comments_new=%s errors=%s",
            reason,
            result.get("new_reviews", 0),
            result.get("updated_reviews", 0),
            result.get("total_reviews", 0),
            result.get("unanswered", 0),
            result.get("new_comments", 0),
            len(result.get("comment_sync_errors", []) or []),
        )
    except Exception:
        db.rollback()
        logger.exception("YANDEX_REVIEWS_AUTO_SYNC_FAILED | reason=%s", reason)
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


def start_yandex_reviews_scheduler():
    global _started
    with _lock:
        if _started:
            return
        _started = True
    logger.info("YANDEX_REVIEWS_SCHEDULER_STARTED | interval_minutes=%s", _interval_minutes())
    threading.Thread(target=_loop, name="yandex-reviews-sync", daemon=True).start()
