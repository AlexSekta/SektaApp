import os
os.environ.setdefault('DATABASE_URL','sqlite://')
from unittest.mock import Mock
from backend.services import ozon_fbs_sticker_monitor_43 as m


def test_timestamp_no_fabrication():
    assert m.parse_ozon_created(None) is None
    assert m.parse_ozon_created('broken') is None
    assert m.parse_ozon_created('2026-11-18T11:00:00Z').utcoffset().total_seconds() == 0


def test_no_create_without_explicit_candidate(monkeypatch):
    db=Mock()
    client=Mock()
    m.process_one(db,2,client,{'posting_number':'p','label_task_id':None,'eligible_create':False})
    client.post_raw.assert_not_called()
    db.execute.assert_not_called()


def test_no_create_when_guard_fails(monkeypatch):
    db=Mock()
    db.execute.return_value.first.return_value=None
    client=Mock()
    m.process_one(db,2,client,{'posting_number':'p','label_task_id':None,'eligible_create':True})
    client.post_raw.assert_not_called()


def test_eligible_guard_claims_first_and_logs(monkeypatch):
    db=Mock()
    db.execute.return_value.first.return_value=('p',)
    client=Mock()
    client.post_raw.return_value={'status_code':200,'body':{'tasks':[{'task_id':4,'task_type':'small_label'}]}}
    monkeypatch.setattr(m,'paced',lambda f:f())
    m.process_one(db,2,client,{'posting_number':'p','label_task_id':None,'eligible_create':True})
    client.post_raw.assert_called_once()
    assert client.post_raw.call_args.args[0].endswith('/package-label/create')
    assert db.commit.call_count == 2


def test_failed_creation_never_retries_blindly(monkeypatch):
    import pytest
    db=Mock()
    db.execute.return_value.first.return_value=('p',)
    client=Mock()
    client.post_raw.side_effect=TimeoutError()
    monkeypatch.setattr(m,'paced',lambda f:f())
    with pytest.raises(TimeoutError):
        m.process_one(db,2,client,{'posting_number':'p','label_task_id':None,'eligible_create':True})
    assert db.commit.call_count == 1


def test_pdf_candidate_query_is_guarded():
    db=Mock()
    db.execute.return_value.mappings.return_value.all.return_value=[]
    m.pdf_candidates(db,2,5)
    sql=str(db.execute.call_args.args[0])
    assert 'auto_create_enabled' in sql
    assert 'a.ready_from_new=true' not in sql
    assert 'ready_detected_at' in sql
    assert 'label_requested_at IS NULL' in sql
