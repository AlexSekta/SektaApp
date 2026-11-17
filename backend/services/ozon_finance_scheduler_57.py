"""Opt-in Ozon finance scheduler with bounded retries and historical backfill.

A single worker is guarded by a PostgreSQL session advisory lock. Each finance
operation independently locks its (organization, date) in sync_day(). Only the
selected date is written. Older incomplete days are backfilled independently of
refreshes of the last four dates.
"""
import logging
import os
import threading
import time
from datetime import date, timedelta

from sqlalchemy import text

from backend.database import engine
from backend.services.advisory_lock_connection_58_18 import lock_connection
from backend.services.marketplace_clients import get_ozon_client
from backend.services.ozon_finance_56 import open_context, close_context, sync_day

log = logging.getLogger('ozon_finance_scheduler')
_stop = threading.Event()
_thread = None
_LOCK = 76155721
_REFRESH_INTERVALS = ((0, 1800), (1, 10800), (2, 86400), (3, 86400))
# Avoid hot loops on a failing day. Other dates can still be processed.
_RETRY_SECONDS = (300, 900, 1800, 3600)


def _org_ids():
    with engine.connect() as conn:
        return [int(row[0]) for row in conn.execute(text('''
            SELECT DISTINCT organization_id FROM marketplace_connections
            WHERE marketplace='OZON' AND enabled AND credentials_encrypted IS NOT NULL
            ORDER BY organization_id
        '''))]


def _oldest_day():
    raw = os.getenv('OZON_FINANCE_BACKFILL_FROM', '2025-01-01')
    try:
        value = date.fromisoformat(raw)
    except ValueError:
        raise ValueError('OZON_FINANCE_BACKFILL_FROM must be YYYY-MM-DD')
    if value < date(2025, 1, 1):
        raise ValueError('OZON_FINANCE_BACKFILL_FROM cannot precede 2025-01-01')
    return value


def _next_day(org, *, today=None, oldest=None, excluded=()):
    """Newest incomplete historical date, excluding four actively refreshed days."""
    today = today or date.today()
    oldest = oldest or _oldest_day()
    latest = today - timedelta(days=4)
    if oldest > latest:
        return None
    db = open_context(org)
    try:
        # Exclude failed dates that are cooling down using the query itself.
        candidate = db.execute(text('''
            SELECT d::date FROM generate_series(
                CAST(:oldest AS date), CAST(:latest AS date), interval '1 day') d
            LEFT JOIN ozon_finance_days s
              ON s.organization_id=:org AND s.day=d::date
            WHERE s.status IS DISTINCT FROM 'complete'
              AND NOT (d::date = ANY(CAST(:excluded AS date[])))
            ORDER BY d DESC LIMIT 1
        '''), {'oldest': oldest, 'latest': latest, 'org': org,
               'excluded': list(excluded)}).scalar()
        return candidate
    finally:
        close_context(db)


def _refresh_type_catalog(org):
    db = open_context(org)
    try:
        client = get_ozon_client(db)
        response = client.post_raw('/v1/finance/accrual/types', {})
        if response.get('status_code') != 200:
            raise RuntimeError('Ozon types endpoint HTTP ' + str(response.get('status_code')))
        body = response.get('body') or {}
        values = body.get('accrual_types')
        if not isinstance(values, list) or not values:
            raise ValueError('Ozon types response missing accrual_types')
        for item in values:
            if not isinstance(item, dict) or not isinstance(item.get('id'), int):
                continue
            db.execute(text('''INSERT INTO ozon_finance_type_catalog
                (organization_id,type_id,name,description,updated_at)
                VALUES (:o,:id,:name,:description,now())
                ON CONFLICT (organization_id,type_id) DO UPDATE SET
                name=EXCLUDED.name,description=EXCLUDED.description,updated_at=now()'''),
                {'o':org,'id':item['id'],'name':str(item.get('name') or ''),
                 'description':str(item.get('description') or '')})
        db.commit()
        log.info('OZON_FINANCE_TYPES_SYNCED org=%s count=%s', org, len(values))
    finally:
        close_context(db)


def _choose_jobs(org, now, last_attempt, retry_until, pending=(), *, today=None, oldest=None):
    """Provide one due refresh AND one backfill independently per cycle."""
    today = today or date.today()
    jobs = []
    for offset, period in _REFRESH_INTERVALS:
        day = today - timedelta(days=offset)
        key = (org, day)
        if now < retry_until.get(key, 0):
            continue
        if key in pending or now - last_attempt.get(key, -1e12) >= period:
            jobs.append((day, True))
            break
    excluded = [d for (o, d), until in retry_until.items() if o == org and until > now]
    backfill = _next_day(org, today=today, oldest=oldest, excluded=excluded)
    if backfill is not None:
        jobs.append((backfill, False))
    return jobs


def _loop():
    with lock_connection() as lock_conn:
        if not lock_conn.execute(text('SELECT pg_try_advisory_lock(:k)'), {'k':_LOCK}).scalar():
            log.warning('OZON_FINANCE_AUTO_ALREADY_RUNNING')
            return
        lock_conn.commit()
        try:
            if _stop.wait(15):
                return
            oldest = _oldest_day()
            log.info('OZON_FINANCE_AUTO_STARTED oldest=%s today_provisional=true', oldest)
            last_attempt = {}
            catalog_last = {}
            retry_until = {}
            failures = {}
            pending = set()
            resume = set()
            while not _stop.is_set():
                try:
                    for org in _org_ids():
                        if _stop.is_set():
                            break
                        now = time.monotonic()
                        if now - catalog_last.get(org, -1e12) >= 86400:
                            try:
                                _refresh_type_catalog(org)
                                catalog_last[org] = now
                            except Exception as exc:
                                log.warning('OZON_FINANCE_TYPES_RETRY org=%s reason=%s', org, type(exc).__name__)
                                catalog_last[org] = now - 82800  # retry in one hour
                        try:
                            jobs = _choose_jobs(org, now, last_attempt, retry_until, pending, oldest=oldest)
                        except Exception:
                            log.exception('OZON_FINANCE_JOB_SELECT_FAILED org=%s', org)
                            continue
                        for day, refresh in jobs:
                            if _stop.is_set():
                                break
                            key = (org, day)
                            actual_refresh = refresh and key not in resume
                            last_attempt[key] = time.monotonic()
                            try:
                                result = sync_day(org, day, max_pages=100, delay=2, refresh=actual_refresh)
                                status = result.get('status')
                                log.info('OZON_FINANCE_AUTO_DAY org=%s day=%s refresh=%s status=%s rows=%s',
                                         org, day, actual_refresh, status, result.get('rows'))
                                if status == 'busy':
                                    pending.add(key)
                                    retry_until[key] = time.monotonic() + 300
                                elif status == 'loading':
                                    resume.add(key)
                                    pending.add(key)
                                    failures.pop(key, None)
                                    retry_until[key] = time.monotonic() + 60
                                elif status == 'complete':
                                    resume.discard(key)
                                    pending.discard(key)
                                    failures.pop(key, None)
                                    retry_until.pop(key, None)
                                else:
                                    raise RuntimeError('Unexpected status: ' + str(status))
                            except Exception as exc:
                                count = failures.get(key, 0) + 1
                                failures[key] = count
                                resume.add(key)
                                pending.add(key)
                                backoff = _RETRY_SECONDS[min(count-1, len(_RETRY_SECONDS)-1)]
                                retry_until[key] = time.monotonic() + backoff
                                log.warning('OZON_FINANCE_AUTO_RETRY org=%s day=%s refresh=%s reason=%s retry_seconds=%s',
                                            org, day, actual_refresh, type(exc).__name__, backoff)
                            if _stop.wait(2):
                                break
                except Exception:
                    log.exception('OZON_FINANCE_AUTO_CYCLE_ERROR')
                if _stop.wait(60):
                    return
        finally:
            lock_conn.execute(text('SELECT pg_advisory_unlock(:k)'), {'k':_LOCK})
            lock_conn.commit()


def start_ozon_finance_scheduler():
    global _thread
    if os.getenv('OZON_FINANCE_AUTO_ENABLED', 'false').lower() not in ('1','true','yes'):
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
