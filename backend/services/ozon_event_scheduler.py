"""Current-day return refresh every 30min; expensive delivery history rescan every 6 hours."""
import os
import threading
from datetime import datetime, timedelta
from backend.database import SessionLocal
from backend.auth.tenant import (legacy_sync_organization_id, set_app_db_role,
    set_tenant_context, clear_tenant_context, reset_app_db_role)
from backend.services.ozon_event_sync import sync_returns_day, sync_posting_events_window
from backend.services.ozon_order_sync import MOSCOW
from backend.services.ozon_sync_guard import sync_guard
from backend.logging_config import get_logger

log = get_logger('ozon_event_scheduler')
_stop = threading.Event()
_started = False
_INTERVAL_SECONDS = max(1800, int(os.getenv('OZON_EVENT_SYNC_INTERVAL_SECONDS', '1800')))


def _run_with_db(org, fn):
    db = SessionLocal()
    try:
        set_app_db_role(db)
        set_tenant_context(db, org)
        return fn(db)
    except Exception:
        db.rollback()
        raise
    finally:
        clear_tenant_context(db)
        reset_app_db_role(db)
        db.close()


def _loop():
    if _stop.wait(180):
        return
    cycle = 0
    while not _stop.is_set():
        org = legacy_sync_organization_id()
        if org is not None:
            if sync_guard.acquire(timeout=1):
                try:
                    today = datetime.now(MOSCOW).date()
                    # Populate missing historical coverage for 7-day dashboard.
                    # Refresh today's and yesterday's return snapshots each cycle.
                    from backend.models.ozon_event import OzonEventCoverage
                    for ago in range(7, -1, -1):
                        if _stop.is_set():
                            break
                        day = today - timedelta(days=ago)
                        try:
                            def process(db, day=day, ago=ago):
                                exists = db.query(OzonEventCoverage).filter_by(
                                    organization_id=org, event_type='returned', event_date=day).first()
                                if ago > 1 and exists:
                                    return None
                                return sync_returns_day(db, org, day)
                            result = _run_with_db(org, process)
                            if result:
                                log.info('OZON_RETURN_AUTO_SYNC_OK day=%s units=%s provisional=%s',
                                         day, result['units'], day == today)
                        except Exception:
                            log.exception('OZON_RETURN_AUTO_SYNC_FAILED day=%s', day)
                    # Full posting history scan is deliberately less frequent.
                    if cycle % 12 == 0 and not _stop.is_set():
                        try:
                            _run_with_db(org, lambda db: sync_posting_events_window(
                                db, org, today - timedelta(days=14), today))
                        except Exception:
                            log.exception('OZON_POSTING_EVENT_AUTO_SYNC_FAILED')
                finally:
                    sync_guard.release()
            else:
                log.info('OZON_EVENT_SYNC_SKIPPED concurrent collector; next cycle will retry')
        cycle += 1
        _stop.wait(_INTERVAL_SECONDS)


def start_ozon_event_scheduler():
    global _started
    if _started:
        return
    _stop.clear()
    _started = True
    threading.Thread(target=_loop, daemon=True, name='ozon-event-sync').start()
    log.info('OZON_EVENT_SCHEDULER_STARTED interval_seconds=%s live_day=true', _INTERVAL_SECONDS)


def stop_ozon_event_scheduler():
    _stop.set()
