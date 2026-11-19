"""Pure-function checks without production DB credentials."""
import ast
from datetime import datetime, timezone
from pathlib import Path
import pytest

source = Path(__file__).resolve().parents[1] / 'scripts' / 'ozon_fbs_created_backfill_58.py'
module = ast.parse(source.read_text(encoding='utf-8'))
functions = [node for node in module.body if isinstance(node, ast.FunctionDef) and node.name in {'parse_date', 'extract_date'}]
namespace = {'datetime': datetime, 'timezone': timezone}
exec(compile(ast.Module(body=functions, type_ignores=[]), str(source), 'exec'), namespace)
parse_date = namespace['parse_date']
extract_date = namespace['extract_date']


def test_extract_valid():
    dt = extract_date({'result': {'posting_number': 'abc', 'in_process_at': '2026-11-18T11:34:57Z'}}, 'abc')
    assert dt == datetime(2026, 11, 18, 11, 34, 57, tzinfo=timezone.utc)


def test_reject_wrong_posting():
    with pytest.raises(ValueError, match='posting mismatch'):
        extract_date({'result': {'posting_number': 'other', 'in_process_at': '2026-11-18T11:34:57Z'}}, 'abc')


def test_reject_missing_or_invalid_date():
    for value in (None, '', 'not-a-date', '2026-11-18T11:34:57'):
        with pytest.raises(ValueError, match='missing/invalid'):
            extract_date({'result': {'posting_number': 'abc', 'in_process_at': value}}, 'abc')


def test_parse_date_utc():
    assert parse_date('2026-11-18T14:34:57+03:00') == datetime(2026,11,18,11,34,57,tzinfo=timezone.utc)


def test_script_has_no_label_or_status_mutation():
    text = source.read_text(encoding='utf-8')
    assert 'package-label/create' not in text
    assert "'/v3/posting/fbs/get'" in text
    assert 'SET ozon_created_at=:created' in text
