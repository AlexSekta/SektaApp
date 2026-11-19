import os
os.environ.setdefault('DATABASE_URL', 'sqlite://')
from unittest.mock import Mock
from backend.services import ozon_fbs_sticker_monitor_43 as m


def test_status_refresh_query_is_scoped_and_bounded():
    db=Mock()
    db.execute.return_value.mappings.return_value.all.return_value=[]
    m.status_refresh_candidates(db, 2, 'awaiting_deliver', 8)
    sql=str(db.execute.call_args.args[0])
    assert 'organization_id=:org' in sql
    assert 'status=:status' in sql
    assert 'status_verified_at' in sql
    assert 'status_next_attempt_at' in sql
    assert db.execute.call_args.args[1] == {'org':2,'status':'awaiting_deliver','limit':8}


def test_status_refresh_checks_identity_without_writes(monkeypatch):
    client=Mock()
    client.post_raw.return_value={'status_code':200,'body':{'result':{'posting_number':'n','status':'delivering'}}}
    monkeypatch.setattr(m,'paced',lambda fn:fn())
    import backend.services.ozon_order_sync as sync
    monkeypatch.setattr(sync,'retry_ozon_request',lambda fn,**kw:fn())
    record=m.read_status_detail(client,'n')
    assert record['status']=='delivering'
    assert client.post_raw.call_args.args[0]=='/v3/posting/fbs/get'


def test_status_refresh_preserves_state_on_failure(monkeypatch):
    db=Mock()
    monkeypatch.setattr(m,'read_status_detail',lambda client,number: (_ for _ in ()).throw(RuntimeError('API down')))
    monkeypatch.setattr(m,'persist_postings',lambda *args: (_ for _ in ()).throw(AssertionError('must not write posting')))
    result=m.refresh_one_status(db,2,Mock(),'n')
    assert result is None
    assert db.rollback.called
    sql=str(db.execute.call_args.args[0])
    assert 'status_next_attempt_at' in sql
    assert 'SET status=' not in sql


def test_in_process_at_is_used_for_archive_date():
    from pathlib import Path
    source=Path(m.__file__).read_text(encoding='utf-8')
    assert "item.get('in_process_at')" in source
    assert 'ready_detected_at=CASE' in source
    assert "'/v3/posting/fbs/package-label/create'" in source  # existing gated PDF logic unchanged
