"""Bounded, tenant/report-scoped retry delays for the existing WB Finance worker.

No schema change. Persisted `updated_at` gives a minimum retry pause across restarts;
additional exponential delay is held in this worker's memory only.
"""
from datetime import datetime, timezone
import os
import time

BASE_SECONDS = max(300, int(os.getenv('WB_FINANCE_RETRY_BASE_SECONDS', '900')))
MAX_SECONDS = max(BASE_SECONDS, int(os.getenv('WB_FINANCE_RETRY_MAX_SECONDS', '14400')))
_failures = {}


def delay_seconds(attempt):
    return min(MAX_SECONDS, BASE_SECONDS * 2 ** min(16, max(0, attempt - 1)))


def eligible(kind, org, row, now=None, monotonic=None):
    """Return true for queued/loading or for retries whose pause has elapsed."""
    if row['status'] != 'retry':
        return True
    now = now or datetime.now(timezone.utc)
    monotonic = time.monotonic() if monotonic is None else monotonic
    key = (kind, int(org), int(row['report_id']))
    state = _failures.get(key)
    if state and monotonic < state['next_at']:
        return False
    updated = row.get('updated_at')
    if updated is not None:
        if updated.tzinfo is None:
            # The current DB's timestamps use the local server clock.
            updated = updated.astimezone()
        if (now - updated.astimezone(timezone.utc)).total_seconds() < BASE_SECONDS:
            return False
    return True


def pick(kind, org, rows, now=None, monotonic=None):
    for row in rows:
        if eligible(kind, org, row, now=now, monotonic=monotonic):
            return row
    return None


def record_result(kind, org, report_id, status, monotonic=None):
    key = (kind, int(org), int(report_id))
    if status != 'retry':
        _failures.pop(key, None)
        return 0
    monotonic = time.monotonic() if monotonic is None else monotonic
    count = _failures.get(key, {}).get('attempts', 0) + 1
    seconds = delay_seconds(count)
    _failures[key] = {'attempts': count, 'next_at': monotonic + seconds}
    return seconds


def clear():
    _failures.clear()
