"""Regression guards for the bounded one-time Ozon batch runner."""
import ast
from pathlib import Path

SOURCE = Path(__file__).resolve().parents[1] / 'scripts' / 'ozon_fbs_batch_54.py'
TEXT = SOURCE.read_text(encoding='utf-8')
TREE = ast.parse(TEXT)


def test_run_all_and_manual_commands_present():
    methods = {n.name for n in TREE.body if isinstance(n, ast.FunctionDef)}
    assert {'run_all', '_run_all_locked', 'work_one', 'run_batch', 'snapshot', 'status'} <= methods
    assert "'run-all'" in TEXT


def test_frozen_snapshot_and_live_status_guard_kept():
    assert "state IN ('pending','awaiting_pdf')" in TEXT
    assert "live_status != 'awaiting_deliver'" in TEXT
    assert 'batch54_create_requested_unconfirmed' in TEXT
    assert "if archive['label_requested_at'] is not None:" in TEXT


def test_concurrency_and_backpressure_guards():
    assert 'pg_try_advisory_lock' in TEXT
    assert 'pg_advisory_unlock' in TEXT
    assert 'open_tasks < max_open_tasks' in TEXT
    assert "state='awaiting_pdf' AND updated_at <= now()" in TEXT
    assert 'max_task_attempts' in TEXT
    assert 'max_new_reviews' in TEXT


def test_no_automatic_scheduler_or_new_snapshot_in_run_all():
    fn = next(n for n in TREE.body if isinstance(n, ast.FunctionDef) and n.name == '_run_all_locked')
    invoked = [n.func.id for n in ast.walk(fn) if isinstance(n, ast.Call) and isinstance(n.func, ast.Name)]
    assert 'snapshot' not in invoked
    assert 'ensure_schema' not in invoked
    assert 'work_one' in invoked
