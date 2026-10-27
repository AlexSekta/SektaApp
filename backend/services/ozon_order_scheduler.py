"""30-minute incremental Ozon order snapshots; history loaded once, recent days refreshed."""
import os
import threading
from datetime import datetime, timedelta
from backend.auth.tenant import (clear_tenant_context, legacy_sync_organization_id,
    reset_app_db_role, set_app_db_role, set_tenant_context)
from backend.database import SessionLocal
from backend.logging_config import get_logger
from backend.services.ozon_order_sync import MOSCOW, sync_day
from backend.services.ozon_sync_guard import sync_guard

log = get_logger('ozon_order_scheduler')
_stop = threading.Event()
_started = False
_CYCLE_SECONDS = max(1800, int(os.getenv('OZON_ORDER_SYNC_INTERVAL_SECONDS', '1800')))


def _sync(cycle):
    org = legacy_sync_organization_id()
    if org is None:
        return
    from backend.models.ozon_order import OzonOrderSyncDay
    today = datetime.now(MOSCOW).date()
    history = max(1, min(30, int(os.getenv('OZON_ORDER_INITIAL_DAYS', '7'))))
    # Current day is a mutable snapshot. Refresh yesterday every 6 hours,
    # and any historical date with no completed initial import.
    days = list(range(history, -1, -1))
    for ago in days:
        if _stop.is_set():
            break
        day = today - timedelta(days=ago)
        db = SessionLocal()
        try:
            set_app_db_role(db)
            set_tenant_context(db, org)
            exists = db.query(OzonOrderSyncDay).filter_by(organization_id=org, sale_date=day).first()
            if exists and ago > 1:
                continue
            if exists and ago == 1 and cycle % 12 != 0:
                continue
            sync_day(db, org, day)
        except Exception:
            db.rollback()
            log.exception('OZON_ORDER_AUTO_SYNC_FAILED day=%s', day)
        finally:
            clear_tenant_context(db)
            reset_app_db_role(db)
            db.close()


def _loop():
    if _stop.wait(90):
        return
    cycle = 0
    while not _stop.is_set():
        # Both schedulers share this guard; never overlap intensive API/DB work.
        if sync_guard.acquire(timeout=1):
            try:
                _sync(cycle)
            except Exception:
                log.exception('OZON_ORDER_AUTO_SYNC_ERROR')
            finally:
                sync_guard.release()
        else:
            log.info('OZON_ORDER_SYNC_SKIPPED concurrent collector; next cycle will retry')
        cycle += 1
        _stop.wait(_CYCLE_SECONDS)


def start_ozon_order_scheduler():
    global _started
    if _started:
        return
    _stop.clear()
    _started = True
    threading.Thread(target=_loop, name='ozon-order-sync', daemon=True).start()
    log.info('OZON_ORDER_SCHEDULER_STARTED interval_seconds=%s live_day=true', _CYCLE_SECONDS)


def stop_ozon_order_scheduler():
    _stop.set()
