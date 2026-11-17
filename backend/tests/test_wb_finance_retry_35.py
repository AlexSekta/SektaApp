"""Pure tests; do not connect to the tenant database or WB API."""
from datetime import datetime, timedelta, timezone
from backend.services import wb_finance_retry_35 as r


def setup_function():
    r.clear()


def test_retry_pauses_but_other_report_is_selected():
    now = datetime.now(timezone.utc)
    rows = [
        dict(report_id=111, status='retry', updated_at=now, report_day=now.date()),
        dict(report_id=222, status='queued', updated_at=now, report_day=now.date()),
    ]
    assert r.pick('weekly', 2, rows, now=now, monotonic=100) == rows[1]


def test_retry_becomes_eligible_after_persisted_delay():
    now = datetime.now(timezone.utc)
    row = dict(report_id=111, status='retry', updated_at=now - timedelta(seconds=r.BASE_SECONDS + 1))
    assert r.eligible('weekly', 2, row, now=now, monotonic=100)


def test_backoff_doubles_and_is_bounded():
    assert r.delay_seconds(1) == r.BASE_SECONDS
    assert r.delay_seconds(2) == min(r.MAX_SECONDS, r.BASE_SECONDS * 2)
    assert r.delay_seconds(999) == r.MAX_SECONDS


def test_record_result_resets_and_tenants_isolated():
    t = datetime.now(timezone.utc)
    row = dict(report_id=42, status='retry', updated_at=t - timedelta(days=1))
    assert r.record_result('weekly', 2, 42, 'retry', monotonic=100) == r.BASE_SECONDS
    assert not r.eligible('weekly', 2, row, now=t, monotonic=101)
    assert r.eligible('weekly', 3, row, now=t, monotonic=101)
    assert r.eligible('daily', 2, row, now=t, monotonic=101)
    assert r.record_result('weekly', 2, 42, 'complete', monotonic=101) == 0
    assert r.eligible('weekly', 2, row, now=t, monotonic=101)


def test_existing_loading_job_not_delayed():
    now = datetime.now(timezone.utc)
    assert r.eligible('weekly', 2, dict(report_id=42, status='loading', updated_at=now), now=now)
