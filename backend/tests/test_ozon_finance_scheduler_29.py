"""No-network regression checks for Ozon Finance retry/backfill behavior."""
from contextlib import contextmanager
from datetime import date, timedelta
from unittest.mock import patch

import pytest

from backend.services import ozon_finance_scheduler_57 as scheduler
from backend.services import ozon_finance_56 as finance


DAY = date(2026, 11, 16)


def test_default_backfill_starts_2025(monkeypatch):
    monkeypatch.delenv('OZON_FINANCE_BACKFILL_FROM', raising=False)
    assert scheduler._oldest_day() == date(2025, 1, 1)


def test_backfill_start_can_be_limited(monkeypatch):
    monkeypatch.setenv('OZON_FINANCE_BACKFILL_FROM', '2026-11-01')
    assert scheduler._oldest_day() == date(2026, 11, 1)


def test_invalid_backfill_setting_fails_closed(monkeypatch):
    monkeypatch.setenv('OZON_FINANCE_BACKFILL_FROM', 'tomorrow')
    with pytest.raises(ValueError):
        scheduler._oldest_day()


def test_historical_backfill_and_refresh_in_one_cycle():
    with patch.object(scheduler, '_next_day', return_value=date(2026, 11, 11)) as next_day:
        jobs = scheduler._choose_jobs(2, 100, {}, {}, today=DAY)
    assert jobs == [(DAY, True), (date(2026, 11, 11), False)]
    assert next_day.call_args.kwargs['today'] == DAY


def test_retry_cooldown_only_blocks_affected_day():
    yesterday = DAY - timedelta(days=1)
    recent = DAY - timedelta(days=2)
    with patch.object(scheduler, '_next_day', return_value=date(2026, 11, 11)):
        jobs = scheduler._choose_jobs(2, 100, {}, {(2, DAY):200}, today=DAY)
    assert jobs[0] == (yesterday, True)
    assert jobs[1] == (date(2026, 11, 11), False)


def test_failed_refresh_retries_after_cooldown_without_waiting_a_day():
    old = DAY - timedelta(days=3)
    last = {(2, DAY):100, (2, DAY-timedelta(days=1)):100,
            (2, DAY-timedelta(days=2)):100, (2, old):100}
    pending = {(2, old)}
    with patch.object(scheduler, '_next_day', return_value=None):
        jobs = scheduler._choose_jobs(2, 500, last, {(2, old):400}, pending, today=DAY)
    assert jobs == [(old, True)]


def test_oldest_later_than_historical_window_shortcircuits():
    assert scheduler._next_day(2, today=DAY, oldest=DAY) is None


def test_day_lock_uses_unique_keys_per_day_and_org():
    keys = []
    class FakeConnection:
        def execute(self, query, params):
            if 'pg_try_advisory_lock' in str(query):
                keys.append(params['k'])
                return type('R', (), {'scalar': lambda self: True})()
            return type('R', (), {'scalar': lambda self: True})()
        def commit(self):
            pass
    @contextmanager
    def fake_conn():
        yield FakeConnection()
    with patch.object(finance, 'lock_connection', fake_conn):
        with finance._day_lock(2, DAY) as acquired:
            assert acquired
        with finance._day_lock(2, DAY-timedelta(days=1)) as acquired:
            assert acquired
        with finance._day_lock(3, DAY) as acquired:
            assert acquired
    assert len(set(keys)) == 3


def test_busy_day_does_not_write_or_call_api():
    @contextmanager
    def busy(org, day):
        yield False
    with patch.object(finance, '_day_lock', busy), patch.object(finance, '_sync_day_locked') as loader:
        result = finance.sync_day(2, DAY)
    assert result['status'] == 'busy'
    loader.assert_not_called()


def test_successful_lock_delegates_once():
    @contextmanager
    def acquired(org, day):
        yield True
    with patch.object(finance, '_day_lock', acquired), patch.object(finance, '_sync_day_locked', return_value={'status':'complete'}) as loader:
        result=finance.sync_day(2,DAY,refresh=False)
    assert result['status']=='complete'
    loader.assert_called_once_with(2,DAY,max_pages=100,delay=2,refresh=False)
