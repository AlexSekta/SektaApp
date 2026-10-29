"""Conservative Ozon Finance backfill, descending days, per-organization isolation.

Opt-in: OZON_FINANCE_AUTO_ENABLED=true. One day per organization per cycle.
Do not include today/yesterday: same-day settlements can change.
"""
import logging
import os
import threading
import time
import time
from backend.services.marketplace_clients import get_ozon_client
from datetime import date, timedelta
from sqlalchemy import text
from backend.database import engine
from backend.services.advisory_lock_connection_58_18 import lock_connection
from backend.services.ozon_finance_56 import open_context, close_context, sync_day

log = logging.getLogger('ozon_finance_scheduler')
_stop = threading.Event()
_thread = None
# Dedicated postgres advisory lock, preventing duplicate schedulers across processes.
_LOCK = 76155721


def _org_ids():
    with engine.connect() as conn:
        return [int(row[0]) for row in conn.execute(text('''
            SELECT DISTINCT organization_id FROM marketplace_connections
            WHERE marketplace='OZON' AND enabled AND credentials_encrypted IS NOT NULL
            ORDER BY organization_id
        '''))]


def _next_day(org):
    """Pick newest non-complete date. No day rows means not processed yet."""
    end = date.today()
    if end < date(2025, 1, 1):
        return None
    db = open_context(org)
    try:
        # generate_series is bounded to historical horizon. Completed days excluded.
        candidate = db.execute(text('''
            SELECT d::date FROM generate_series(
                CAST(:oldest AS date), CAST(:latest AS date), interval '1 day') d
            LEFT JOIN ozon_finance_days s
              ON s.organization_id=:org AND s.day=d::date
            WHERE s.status IS DISTINCT FROM 'complete'
            ORDER BY d DESC LIMIT 1
        '''), {'oldest': date(2025,1,1), 'latest': end, 'org': org}).scalar()
        return candidate
    finally:
        close_context(db)


def _refresh_type_catalog(org):
    db=open_context(org)
    try:
        client=get_ozon_client(db)
        response=client.post_raw('/v1/finance/accrual/types',{})
        if response.get('status_code')!=200:
            raise RuntimeError('Ozon types endpoint HTTP '+str(response.get('status_code')))
        body=response.get('body') or {}
        values=body.get('accrual_types')
        if not isinstance(values,list) or not values:
            raise ValueError('Ozon types response missing accrual_types')
        for item in values:
            if not isinstance(item,dict) or not isinstance(item.get('id'),int):continue
            db.execute(text("""INSERT INTO ozon_finance_type_catalog
                (organization_id,type_id,name,description,updated_at)
                VALUES (:o,:id,:name,:description,now())
                ON CONFLICT (organization_id,type_id) DO UPDATE SET
                name=EXCLUDED.name,description=EXCLUDED.description,updated_at=now()"""),
                {'o':org,'id':item['id'],'name':str(item.get('name') or ''),
                 'description':str(item.get('description') or '')})
        db.commit()
        log.info('OZON_FINANCE_TYPES_SYNCED org=%s count=%s',org,len(values))
    finally:
        close_context(db)


def _loop():
    # This connection owns the advisory lock until the loop stops.
    with lock_connection() as lock_conn:
        if not lock_conn.execute(text('SELECT pg_try_advisory_lock(:k)'), {'k':_LOCK}).scalar():
            log.warning('OZON_FINANCE_AUTO_ALREADY_RUNNING')
            return
        lock_conn.commit()  # End transaction; session advisory lock remains held.
        try:
            if _stop.wait(15):
                return
            log.info('OZON_FINANCE_AUTO_STARTED current_day_provisional=true oldest=2025-01-01')
            last_refresh = {}
            catalog_last={}
            while not _stop.is_set():
                try:
                    for org in _org_ids():
                        if time.monotonic()-catalog_last.get(org,-100000)>86400:
                            try:
                                _refresh_type_catalog(org)
                                catalog_last[org]=time.monotonic()
                            except Exception as exc:
                                log.warning('OZON_FINANCE_TYPES_RETRY org=%s reason=%s',org,type(exc).__name__)
                                catalog_last[org]=time.monotonic()-82800
                        if _stop.is_set():
                            break
                        # Refresh current day every 30 minutes, yesterday every 3 hours,
                        # and 2-3 days ago once a day. Other cycles backfill older gaps.
                        today = date.today()
                        refresh_day = None
                        for offset, every in ((0,1800),(1,10800),(2,86400),(3,86400)):
                            d = today - timedelta(days=offset)
                            key = (org,d)
                            if time.monotonic() - last_refresh.get(key,0) >= every:
                                refresh_day = d
                                last_refresh[key] = time.monotonic()
                                break
                        day = refresh_day or _next_day(org)
                        if day is None:
                            continue
                        try:
                            result = sync_day(org, day, max_pages=100, delay=2, refresh=refresh_day is not None)
                            log.info('OZON_FINANCE_AUTO_DAY org=%s day=%s status=%s rows=%s',
                                     org, day, result.get('status'), result.get('rows'))
                        except Exception as exc:
                            log.warning('OZON_FINANCE_AUTO_RETRY org=%s day=%s reason=%s', org, day, type(exc).__name__)
                            if _stop.wait(3600):
                                return
                        if _stop.wait(60):
                            return
                except Exception:
                    log.exception('OZON_FINANCE_AUTO_CYCLE_ERROR')
                if _stop.wait(300):
                    return
        finally:
            lock_conn.execute(text('SELECT pg_advisory_unlock(:k)'), {'k':_LOCK})
            lock_conn.commit()  # Do not leave an open transaction.


def start_ozon_finance_scheduler():
    global _thread
    if os.getenv('OZON_FINANCE_AUTO_ENABLED','false').lower() not in ('1','true','yes'):
        log.info('OZON_FINANCE_AUTO_DISABLED set OZON_FINANCE_AUTO_ENABLED=true to opt in')
        return
    if _thread is not None and _thread.is_alive():
        return
    _stop.clear()
    _thread = threading.Thread(target=_loop, daemon=True, name='ozon-finance-auto')
    _thread.start()


def stop_ozon_finance_scheduler():
    _stop.set()
    if _thread is not None:
        _thread.join(timeout=3)
