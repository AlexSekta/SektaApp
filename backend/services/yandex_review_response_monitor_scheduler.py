import os
import threading
from backend.database import SessionLocal
from backend.auth.tenant import clear_tenant_context, legacy_sync_organization_id, reset_app_db_role, set_app_db_role, set_tenant_context
from backend.logging_config import get_logger
from backend.services.yandex_review_response_monitor import ensure_yandex_review_response_schema, monitor_yandex_review_responses

logger=get_logger('yandex_review_response_monitor_scheduler')
_started=False
_lock=threading.Lock()
_stop=threading.Event()

def _interval():
    try:return max(2,int(os.getenv('YANDEX_REVIEW_MONITOR_INTERVAL_MINUTES','2')))
    except ValueError:return 2

def _run(reason):
    db=SessionLocal()
    try:
        org=legacy_sync_organization_id()
        if org is None:
            logger.warning('YANDEX_REVIEW_MONITOR_NO_ORGANIZATION')
            return
        set_app_db_role(db)
        set_tenant_context(db,org)
        result=monitor_yandex_review_responses(db,org)
        logger.info('YANDEX_REVIEW_MONITOR_OK reason=%s result=%s',reason,result)
    except Exception:
        db.rollback()
        logger.exception('YANDEX_REVIEW_MONITOR_FAILED reason=%s',reason)
    finally:
        clear_tenant_context(db)
        reset_app_db_role(db)
        db.close()

def _loop():
    if not _stop.wait(35):_run('startup')
    while not _stop.wait(_interval()*60):_run('scheduled')

def start_yandex_review_response_monitor_scheduler():
    global _started
    with _lock:
        if _started:return
        ensure_yandex_review_response_schema()
        _started=True
    threading.Thread(target=_loop,name='yandex-review-response-monitor',daemon=True).start()
    logger.info('YANDEX_REVIEW_MONITOR_STARTED interval_minutes=%s',_interval())

def stop_yandex_review_response_monitor_scheduler():
    _stop.set()
