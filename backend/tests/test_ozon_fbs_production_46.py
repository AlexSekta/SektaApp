import os
os.environ.setdefault('DATABASE_URL', 'sqlite://')
from unittest.mock import Mock

import pytest

from backend.services import ozon_fbs_sticker_monitor_43 as m


def test_allowlist_includes_verified_ozon_pdf_host(monkeypatch):
    monkeypatch.delenv('OZON_FBS_LABEL_HOST_SUFFIXES', raising=False)
    assert m.allowed_pdf_url('https://ir.ozone.ru/file.pdf?token=opaque')
    assert not m.allowed_pdf_url('http://ir.ozone.ru/file.pdf')
    assert not m.allowed_pdf_url('https://ir.ozone.ru.attacker.invalid/file.pdf')
    assert not m.allowed_pdf_url('https://127.0.0.1/file.pdf')


def test_pdf_queue_only_with_scanit_and_stable_ordering():
    class DB:
        def execute(self, query, params):
            sql = str(query)
            assert "NULLIF(a.scanit,'') IS NOT NULL" in sql
            assert 'a.sticker_pdf IS NULL' in sql
            assert 'a.label_next_attempt_at<=now()' in sql
            assert "a.label_task_id IS NOT NULL OR" in sql
            assert params == {'org': 2, 'limit': 2}
            return Mock(mappings=lambda: Mock(all=lambda: []))
    assert m.pdf_candidates(DB(), 2, 2) == []


def test_pdf_worker_independent_when_listing_fails(monkeypatch):
    seen=[]
    monkeypatch.setattr(m, 'listing_cycle', lambda: (_ for _ in ()).throw(RuntimeError('listing down')))
    monkeypatch.setattr(m, 'identifiers_cycle', lambda: seen.append('scanit'))
    monkeypatch.setattr(m, 'pdf_cycle', lambda: seen.append('pdf'))
    monkeypatch.setattr(m, 'PDF_ENABLED', True)
    m.cycle()
    assert seen == ['scanit', 'pdf']


def test_pdf_worker_does_not_run_until_explicit_opt_in(monkeypatch):
    seen=[]
    monkeypatch.setattr(m, 'listing_cycle', lambda: seen.append('list'))
    monkeypatch.setattr(m, 'identifiers_cycle', lambda: seen.append('scanit'))
    monkeypatch.setattr(m, 'pdf_cycle', lambda: seen.append('pdf'))
    monkeypatch.setattr(m, 'PDF_ENABLED', False)
    m.cycle()
    assert seen == ['list', 'scanit']


def test_start_runs_independent_workers(monkeypatch):
    seen=[]
    class FakeThread:
        def __init__(self, **kw):
            seen.append(kw['name'])
        def start(self):
            pass
    monkeypatch.setattr(m.threading, 'Thread', FakeThread)
    monkeypatch.setattr(m, 'ensure_schema', lambda: None)
    monkeypatch.setenv('OZON_FBS_STICKERS_ENABLED', 'true')
    monkeypatch.setattr(m, 'PDF_ENABLED', True)
    monkeypatch.setattr(m, 'STARTED', False)
    m.start()
    assert set(seen) == {'ozon-fbs-list','ozon-fbs-scanit','ozon-fbs-pdf'}
    m.stop()
    monkeypatch.setattr(m, 'STARTED', False)
    m.STOP.clear()


def test_api_pacing_reentrant_single_call(monkeypatch):
    monkeypatch.setattr(m, '_NEXT_API_CALL', 0.0)
    result = m.paced(lambda: 42)
    assert result == 42


def test_pdf_save_does_not_log_success_when_no_db_rows_updated(monkeypatch):
    # Simulate another worker already having persisted the PDF.
    class DB:
        def execute(self, q, params):
            assert 'sticker_pdf IS NULL' in str(q)
            return Mock(rowcount=0)
        def commit(self):
            pass
    pdf=b'%PDF-1.7\ntest'
    monkeypatch.setattr(m, 'download_pdf',lambda u: pdf)
    monkeypatch.setattr(m, 'parse_task_status',lambda b: ('completed','https://ir.ozone.ru/l.pdf'))
    monkeypatch.setattr(m, 'paced',lambda fn: fn())
    info=[]
    monkeypatch.setattr(m.log, 'info',lambda *args: info.append(args))
    m.process_one(DB(), 2, Mock(post_raw=lambda *a: {'status_code':200,'body':{}}),
                  {'posting_number':'p1','label_task_id':22})
    assert not info
