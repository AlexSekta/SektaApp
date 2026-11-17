import json
import sqlite3
from decimal import Decimal
from pathlib import Path

from openpyxl import Workbook
from backend.scripts.wb_finance_stage_38 import FIELDS, METADATA, stage, audit, dec, signed


def test_amount_and_sign():
    assert dec('1 234,50') == Decimal('1234.50')
    assert signed(' Возврат ', Decimal('12.5')) == Decimal('-12.5')
    assert signed('Продажа', Decimal('12.5')) == Decimal('12.5')


def test_stage_isolated_and_does_not_overwrite(tmp_path):
    source = tmp_path / 'weekly.xlsx'
    stage_file = tmp_path / 'staging.sqlite'
    wb = Workbook()
    ws = wb.active
    headers = list(FIELDS.values()) + METADATA
    ws.append(headers)
    ws.append([100, 70, 10, 2, 0, 1, 3, 'Продажа', 'Продажа', 'hs001', 'abc'])
    ws.append([30, 20, 4, 0, 0, 0, 0, 'Возврат', 'Возврат', 'hs001', 'def'])
    wb.save(source)
    summary = stage(source, stage_file, 511856341)
    assert summary['source_rows'] == 2
    assert summary['source_totals']['retail'] == '70.00'
    assert summary['source_totals']['for_pay'] == '50.00'
    assert summary['source_totals']['logistics'] == '14.00'
    with sqlite3.connect(stage_file) as conn:
        assert conn.execute('SELECT COUNT(*) FROM source_rows').fetchone()[0] == 2
        assert json.loads(conn.execute("SELECT value FROM stage_meta WHERE key='contains_rrd_id'").fetchone()[0]) is False
    try:
        stage(source, stage_file, 511856341)
        assert False, 'must refuse existing staging'
    except FileExistsError:
        pass
    result = audit(summary, None)
    assert result['safe_to_merge'] is False
    assert result['production_db_changed'] is False


def test_missing_field_does_not_leave_stage(tmp_path):
    src = tmp_path / 'bad.xlsx'
    dst = tmp_path / 'bad.sqlite'
    wb = Workbook()
    wb.active.append(['invalid'])
    wb.save(src)
    try:
        stage(src, dst, 1)
        assert False
    except ValueError:
        pass
    assert not dst.exists()
