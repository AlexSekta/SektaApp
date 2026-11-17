"""No database/API needed: regression tests for the WB live refresh rotation."""
from datetime import date, datetime, timedelta
from types import SimpleNamespace

# Extract pure selection helpers without initializing the production DB on import.
import ast
from pathlib import Path

source = Path(__file__).resolve().parents[1] / "services" / "wb_sales_live_scheduler.py"
tree = ast.parse(source.read_text(encoding="utf-8"))
selected = [node for node in tree.body if isinstance(node, ast.FunctionDef)
            and node.name in ("_needs_refresh", "_older_candidates")]
namespace = {"timedelta": timedelta, "_OLDER_MIN_AGE": timedelta(hours=6)}
exec(compile(ast.Module(body=selected, type_ignores=[]), str(source), "exec"), namespace)
_needs_refresh = namespace["_needs_refresh"]
_older_candidates = namespace["_older_candidates"]


def test_rotation_covers_all_older_dates():
    today = date(2026, 11, 16)
    want = {today - timedelta(days=n) for n in range(2, 7)}
    assert set(_older_candidates(today, 7, 2)) == want
    assert set(_older_candidates(today, 7, 5)) == want
    assert _older_candidates(today, 2, 2) == []


def test_rotation_starts_at_requested_day_and_wraps():
    today = date(2026, 11, 16)
    seq = _older_candidates(today, 7, 5)
    assert [(today - d).days for d in seq] == [5, 6, 2, 3, 4]


def test_existing_snapshot_is_refreshed_after_six_hours():
    now = datetime(2026, 11, 16, 12)
    assert _needs_refresh(None, now)
    assert _needs_refresh(SimpleNamespace(synced_at=None), now)
    assert not _needs_refresh(SimpleNamespace(synced_at=now - timedelta(hours=5)), now)
    assert _needs_refresh(SimpleNamespace(synced_at=now - timedelta(hours=6)), now)


def test_fourteen_day_window():
    today = date(2026, 11, 16)
    offsets = [(today - d).days for d in _older_candidates(today, 14, 2)]
    assert offsets == list(range(2, 14))
