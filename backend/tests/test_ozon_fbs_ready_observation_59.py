import os
os.environ.setdefault('DATABASE_URL', 'sqlite://')
from unittest.mock import Mock
from backend.services import ozon_fbs_sticker_monitor_43 as m


def test_first_seen_ready_sets_ready_time_and_no_backdating():
    db = Mock()
    m.persist_postings(db, 2, {'test': {'status': 'awaiting_deliver'}})
    sql = str(db.execute.call_args.args[0])
    assert "CASE WHEN :status='awaiting_deliver' THEN now() ELSE NULL END" in sql
    assert "EXCLUDED.status='awaiting_deliver'" in sql
    assert "ozon_fbs_sticker_archive.ready_detected_at IS NULL" in sql
    assert "THEN now() ELSE ozon_fbs_sticker_archive.ready_detected_at END" in sql
    assert 'first_seen_at + make_interval' not in sql
    assert db.execute.call_args.args[1]['status'] == 'awaiting_deliver'


def test_scanning_ready_order_initializes_ready_time():
    db = Mock()
    m.save_identifiers(db, 2, {'posting_number':'test','order_number':'abc',
        'status':'awaiting_deliver','scanit':'ii1','upper_barcode':'x','lower_barcode':'x'})
    sql = str(db.execute.call_args.args[0])
    assert "CASE WHEN :status='awaiting_deliver' THEN now() ELSE NULL END" in sql
    assert "ozon_fbs_sticker_archive.ready_detected_at IS NULL" in sql


def test_candidate_and_atomic_claim_have_same_delay_without_ready_from_new():
    db=Mock()
    db.execute.return_value.mappings.return_value.all.return_value=[]
    m.pdf_candidates(db,2,3)
    sql=str(db.execute.call_args.args[0])
    assert 'a.ready_from_new=true' not in sql
    assert "a.status='awaiting_deliver'" in sql
    assert 'a.ready_detected_at IS NOT NULL' in sql
    assert 'make_interval(mins => COALESCE(s.delay_minutes,20))' in sql
    assert 'a.label_requested_at IS NULL' in sql
    assert '(a.label_task_id IS NOT NULL OR' in sql
    assert 'COALESCE(s.auto_create_enabled,false)' in sql

    db=Mock()
    db.execute.return_value.first.return_value=None
    m.process_one(db,2,Mock(),{'posting_number':'test','label_task_id':None,'eligible_create':True})
    sql=str(db.execute.call_args.args[0])
    assert 'ready_from_new=true' not in sql
    assert "status='awaiting_deliver'" in sql
    assert 'ready_detected_at IS NOT NULL' in sql
    assert 'label_requested_at IS NULL' in sql
    assert 'settings.auto_create_enabled=true' in sql
    assert 'make_interval(mins => settings.delay_minutes)' in sql
