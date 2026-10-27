"""Incremental Yandex Market sales polling, 30-minute cycle."""
import os
import threading
from datetime import datetime, timedelta
from backend.database import SessionLocal
from backend.auth.tenant import legacy_sync_organization_id, set_app_db_role, set_tenant_context, clear_tenant_context, reset_app_db_role
from backend.logging_config import get_logger
from backend.models.yandex_sales_order import YandexSalesSyncDay
from backend.services.yandex_sales_order_sync import MOSCOW, sync_yandex_sales_day

log = get_logger('yandex_sales_order_scheduler')
_stop = threading.Event()
_started = False
_interval = max(1800, int(os.getenv('YANDEX_SALES_SYNC_INTERVAL_SECONDS', '1800')))

def _run(cycle):
    org = legacy_sync_organization_id()
    if org is None:
        return
    today = datetime.now(MOSCOW).date()
    history = max(1, min(30, int(os.getenv('YANDEX_SALES_INITIAL_DAYS', '7'))))
    for ago in range(history, -1, -1):
        if _stop.is_set():
            break
        day = today - timedelta(days=ago)
        db = SessionLocal()
        try:
            set_app_db_role(db)
            set_tenant_context(db, org)
            row = db.query(YandexSalesSyncDay).filter_by(organization_id=org, sale_date=day).first()
            if row and ago > 1:
                continue
            if row and ago == 1 and cycle % 12:
                continue
            sync_yandex_sales_day(db, org, day)
        except Exception:
            db.rollback()
            log.exception('YANDEX_SALES_ORDER_AUTO_SYNC_FAILED day=%s', day)
        finally:
            clear_tenant_context(db)
            reset_app_db_role(db)
            db.close()

def _loop():
    if _stop.wait(180):
        return
    cycle = 0
    while not _stop.is_set():
        _run(cycle)
        cycle += 1
        _stop.wait(_interval)

def start_yandex_sales_order_scheduler():
    global _started
    if _started:
        return
    _stop.clear()
    _started = True
    threading.Thread(target=_loop, name='yandex-sales-order-sync', daemon=True).start()
    log.info('YANDEX_SALES_ORDER_SCHEDULER_STARTED interval_seconds=%s live_day=true', _interval)

def stop_yandex_sales_order_scheduler():
    _stop.set()
