"""Regression checks: only confirmed 429 can enter bounded create retry."""
import os
os.environ.setdefault('DATABASE_URL', 'sqlite://')
from unittest.mock import Mock
import pytest

from backend.services import ozon_fbs_sticker_monitor_43 as m


class FakeDB:
    def __init__(self):
        self.sql = []
        self.commits = 0
        self.claimed = True
        self.failures = 1

    def execute(self, query, params):
        sql = str(query)
        self.sql.append((sql, params))
        if 'RETURNING label_create_429_retries' in sql:
            return Mock(first=lambda: (self.failures,))
        if 'RETURNING posting_number' in sql:
            return Mock(first=lambda: ('p1',) if self.claimed else None)
        return Mock()

    def commit(self):
        self.commits += 1


def test_candidates_only_retry_explicit_429_and_keep_task_priority():
    db = Mock()
    db.execute.return_value.mappings.return_value.all.return_value = []
    m.pdf_candidates(db, 2, 6)
    sql = str(db.execute.call_args.args[0])
    assert "a.label_error LIKE '%label create HTTP 429%'" in sql
    assert 'a.label_create_429_retries < :max_retries' in sql
    assert "a.status='awaiting_deliver'" in sql
    assert 'a.ready_detected_at' in sql
    assert 'a.label_next_attempt_at<=now()' in sql
    assert 'a.label_task_id IS NOT NULL' in sql


def test_429_is_scheduled_and_recorded_without_ambiguous_exception(monkeypatch):
    monkeypatch.setattr(m, 'paced', lambda call: call())
    db = FakeDB()
    client = Mock(post_raw=lambda *a, **kw: {'status_code': 429})
    m.process_one(db, 2, client, {'posting_number': 'p1', 'label_task_id': None, 'eligible_create': True})
    assert db.commits == 2
    claim, mark = db.sql
    assert 'label_error=\'create_requested_unconfirmed\'' in claim[0]
    assert "label_error='label create HTTP 429'" in mark[0]
    assert 'label_create_429_retries=label_create_429_retries+1' in mark[0]
    assert 'label_requested_at=COALESCE(label_requested_at,now())' in claim[0]


def test_504_does_not_release_claim_or_retry(monkeypatch):
    monkeypatch.setattr(m, 'paced', lambda call: call())
    db = FakeDB()
    client = Mock(post_raw=lambda *a, **kw: {'status_code': 504})
    with pytest.raises(RuntimeError, match='label create HTTP 504'):
        m.process_one(db, 2, client, {'posting_number': 'p1', 'label_task_id': None, 'eligible_create': True})
    assert db.commits == 1
    assert len(db.sql) == 1


def test_timeout_does_not_release_claim(monkeypatch):
    monkeypatch.setattr(m, 'paced', lambda call: call())
    db = FakeDB()
    client = Mock(post_raw=Mock(side_effect=TimeoutError('timeout')))
    with pytest.raises(TimeoutError):
        m.process_one(db, 2, client, {'posting_number': 'p1', 'label_task_id': None, 'eligible_create': True})
    assert db.commits == 1
    assert len(db.sql) == 1


def test_claim_guards_retry_with_limit_and_status():
    db = FakeDB()
    db.claimed = False
    client = Mock()
    m.process_one(db, 2, client, {'posting_number': 'p1', 'label_task_id': None, 'eligible_create': True})
    client.post_raw.assert_not_called()
    sql, params = db.sql[0]
    assert 'label_create_429_retries < :max_retries' in sql
    assert params['max_retries'] == m.CREATE_429_MAX_RETRIES
    assert "status='awaiting_deliver'" in sql
    assert 'ready_detected_at + make_interval' in sql


def test_schema_migrates_retry_counter():
    import inspect
    source = inspect.getsource(m.ensure_schema)
    assert 'label_create_429_retries INTEGER NOT NULL DEFAULT 0' in source
