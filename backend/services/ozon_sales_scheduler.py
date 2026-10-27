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
from backend.services.ozon_sales_sync import (
    DEFAULT_HISTORY_DAYS,
    ensure_ozon_sales_tables,
    sync_ozon_sales,
)

logger = get_logger("ozon_sales_scheduler")

_started = False
_stop_event = threading.Event()
_lock = threading.Lock()


def _interval_minutes() -> int:
    try:
        return max(
            60,
            int(os.getenv("OZON_SALES_SYNC_INTERVAL_MINUTES", "60")),
        )
    except ValueError:
        return 60


def _history_days() -> int:
    try:
        return max(
            1,
            min(
                int(
                    os.getenv(
                        "OZON_SALES_HISTORY_DAYS",
                        str(DEFAULT_HISTORY_DAYS),
                    )
                ),
                90,
            ),
        )
    except ValueError:
        return DEFAULT_HISTORY_DAYS


def _run_once(reason: str):
    db = SessionLocal()
    try:
        organization_id = legacy_sync_organization_id()
        if organization_id is None:
            logger.info(
                "OZON_SALES_AUTO_SYNC_SKIPPED | reason=%s no_organization",
                reason,
            )
            return

        set_app_db_role(db)
        set_tenant_context(db, organization_id)

        result = sync_ozon_sales(
            db,
            organization_id=organization_id,
            history_days=_history_days(),
        )

        logger.info(
            "OZON_SALES_AUTO_SYNC_OK | reason=%s date_from=%s "
            "date_to=%s rows=%s",
            reason,
            result.get("date_from"),
            result.get("date_to"),
            result.get("rows_saved"),
        )
    except Exception:
        db.rollback()
        logger.exception(
            "OZON_SALES_AUTO_SYNC_FAILED | reason=%s",
            reason,
        )
    finally:
        clear_tenant_context(db)
        reset_app_db_role(db)
        db.close()


def _loop():
    # /v1/analytics/data has a 1-request-per-minute limit.
    # Leave a safety window after backend startup so a manual diagnostic
    # request made immediately before restart does not collide with the
    # first scheduled sync.
    time.sleep(65)
    _run_once("startup")

    while not _stop_event.wait(_interval_minutes() * 60):
        _run_once("scheduled")


def start_ozon_sales_scheduler():
    global _started

    with _lock:
        if _started:
            return
        _started = True

    ensure_ozon_sales_tables()

    logger.info(
        "OZON_SALES_SCHEDULER_STARTED | interval_minutes=%s history_days=%s",
        _interval_minutes(),
        _history_days(),
    )

    threading.Thread(
        target=_loop,
        name="ozon-sales-sync",
        daemon=True,
    ).start()


def stop_ozon_sales_scheduler():
    _stop_event.set()
