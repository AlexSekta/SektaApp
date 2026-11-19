"""Empty scanit is an Ozon data condition, not automatically an exception."""
import os
os.environ.setdefault('DATABASE_URL', 'sqlite://')
from unittest.mock import Mock
from backend.services import ozon_fbs_sticker_monitor_43 as m


def test_queue_only_ready_orders():
    db = Mock()
    db.execute.return_value.mappings.return_value.all.return_value = []
    assert m.collect_missing_identifiers(db, 2, Mock()) == 0
    sql = str(db.execute.call_args.args[0])
    assert "status='awaiting_deliver'" in sql
    assert 'organization_id=:org' in sql
    assert 'scanit_next_attempt_at' in sql


def test_empty_scanit_status_decisions():
    assert m.missing_scanit_action('awaiting_deliver') == 'retry'
    for status in ('awaiting_packaging', 'cancelled', 'delivering', 'delivered'):
        assert m.missing_scanit_action(status) == 'skip'


def test_ready_empty_scanit_is_saved_and_backed_off(monkeypatch):
    db = Mock()
    db.execute.return_value.mappings.return_value.all.return_value = [{'posting_number':'p1'}]
    saved, backoffs = [], []
    monkeypatch.setattr(m, 'detail_posting', lambda client, number: {
        'posting_number':number, 'status':'awaiting_deliver', 'scanit':'',
        'order_number':'', 'upper_barcode':'123', 'lower_barcode':'123'})
    monkeypatch.setattr(m, 'save_identifiers', lambda db, org, row: saved.append(row))
    monkeypatch.setattr(m, 'scanit_backoff', lambda db, org, no, err: backoffs.append(err))
    monkeypatch.setattr(m.STOP, 'wait', lambda seconds: False)
    assert m.collect_missing_identifiers(db, 2, Mock()) == 0
    assert saved[0]['upper_barcode'] == '123'
    assert backoffs == ['scanit_empty_awaiting_deliver']
    assert not db.rollback.called


def test_live_cancelled_exits_without_backoff(monkeypatch):
    db = Mock()
    db.execute.return_value.mappings.return_value.all.return_value = [{'posting_number':'p1'}]
    monkeypatch.setattr(m, 'detail_posting', lambda client, number: {
        'posting_number':number, 'status':'cancelled', 'scanit':'',
        'order_number':'', 'upper_barcode':'123', 'lower_barcode':'123'})
    monkeypatch.setattr(m.STOP, 'wait', lambda seconds: False)
    assert m.collect_missing_identifiers(db, 2, Mock()) == 0
    sqls = [str(call.args[0]) for call in db.execute.call_args_list]
    assert any('scanit_next_attempt_at=NULL' in sql for sql in sqls)
    assert db.commit.called
    assert not db.rollback.called
