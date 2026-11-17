"""Refresh current WB funnel snapshots and gradually recheck recent saved dates.

One older day per cycle (round-robin per organization), shared Funnel API throttle
with the history worker. Never overwrite a saved snapshot on API failure.
"""
import os
import threading
from datetime import date, datetime, timedelta, timezone

from backend.auth.tenant import tenant_session
from backend.api.wb_sales_daily import fetch_one_day
from backend.models.marketplace_connection import MarketplaceConnection
from backend.models.wb_sales_daily import WBSalesDaily
from backend.services.wb_sales_history_scheduler import _organization_ids
from backend.services.wb_sales_funnel_throttle import fetch_throttled
from backend.logging_config import get_logger

log = get_logger('wb_sales_live_scheduler')
_stop = threading.Event()
_worker = None
_INTERVAL = max(900, int(os.getenv('WB_SALES_LIVE_INTERVAL_SECONDS', '1800')))
_RECOVERY_DAYS = min(14, max(2, int(os.getenv('WB_SALES_LIVE_RECOVERY_DAYS', '7'))))
# Avoid polling a historic day on every cycle, including after a restart.
_OLDER_MIN_AGE = timedelta(hours=6)
_MSK = timezone(timedelta(hours=3))
_next_older_offset = {}  # per-org in-process round-robin cursor; range 2.._RECOVERY_DAYS-1


def _today():
    return datetime.now(_MSK).date()


def _older_candidates(today, recovery_days, start_offset):
    """Rotate older days without favoring the first stale day every cycle."""
    if recovery_days <= 2:
        return []
    width = recovery_days - 2
    start = (start_offset - 2) % width
    return [today - timedelta(days=2 + (start + i) % width) for i in range(width)]


def _needs_refresh(snapshot, now):
    if snapshot is None:
        return True
    if snapshot.synced_at is None:
        return True
    return now - snapshot.synced_at >= _OLDER_MIN_AGE


def _run_org(org):
    today = _today()
    with tenant_session(org) as db:
        conn = db.query(MarketplaceConnection).filter_by(organization_id=org, marketplace='WB', enabled=True).first()
        if conn is None or not conn.credentials_encrypted:
            return
        # Today and yesterday always take priority. Pick at most one older day
        # each cycle, including existing snapshots, to repair partial-day data.
        dates = [today, today - timedelta(days=1)]
        candidates = _older_candidates(today, _RECOVERY_DAYS, _next_older_offset.get(org, 2))
        now = datetime.utcnow()
        for old_day in candidates:
            record = db.query(WBSalesDaily).filter_by(organization_id=org, sale_date=old_day).one_or_none()
            if _needs_refresh(record, now):
                dates.append(old_day)
                break
        if candidates:
            # Move cursor even after a failed request: a bad day must not starve
            # other dates. On the next rotation it will be retried.
            selected = dates[-1] if len(dates) > 2 else candidates[0]
            age = (today - selected).days
            _next_older_offset[org] = 2 + (age - 1) % (_RECOVERY_DAYS - 2)
        for d in dates:
            if _stop.is_set():
                return
            try:
                totals, count = fetch_throttled(fetch_one_day, db, d)
                record = db.query(WBSalesDaily).filter_by(organization_id=org, sale_date=d).one_or_none()
                if record is None:
                    record = WBSalesDaily(organization_id=org, sale_date=d)
                    db.add(record)
                record.order_count = totals['orderCount']
                record.order_sum = totals['orderSum']
                record.cancel_count = totals['cancelCount']
                record.cancel_sum = totals['cancelSum']
                record.products_count = count
                record.synced_at = datetime.utcnow()
                db.commit()
                log.info('WB_LIVE_OK org=%s day=%s products=%s units=%s revenue=%s',
                         org, d, count, record.order_count, record.order_sum)
            except Exception as exc:
                db.rollback()
                log.warning('WB_LIVE_ERROR org=%s day=%s error=%s', org, d, str(getattr(exc, 'detail', str(exc)))[:350])
                if getattr(exc, 'status_code', None) == 429:
                    return


def _loop():
    if _stop.wait(120):
        return
    while not _stop.is_set():
        try:
            for org in _organization_ids():
                if _stop.is_set():
                    return
                _run_org(org)
        except Exception:
            log.exception('WB_LIVE_LOOP_ERROR')
        if _stop.wait(_INTERVAL):
            return


def start_wb_sales_live_scheduler():
    global _worker
    if os.getenv('WB_SALES_LIVE_AUTO', '1') == '0':
        log.info('WB_LIVE_DISABLED')
        return
    if _worker and _worker.is_alive():
        return
    _stop.clear()
    _worker = threading.Thread(target=_loop, name='wb-sales-live', daemon=True)
    _worker.start()
    log.info('WB_LIVE_STARTED interval_seconds=%s recovery_days=%s older_per_cycle=1', _INTERVAL, _RECOVERY_DAYS)


def stop_wb_sales_live_scheduler():
    _stop.set()
    if _worker and _worker.is_alive():
        _worker.join(timeout=3)
