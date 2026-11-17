"""Patch40 pure tests: API rows can be out of order; never silently deduplicate."""
from decimal import Decimal
import pytest
from patch40_fullpage.wb_finance_fullpage_511856341 import analyze, SUM_FIELDS


def expectations(**overrides):
    data={name: Decimal('0') for name in SUM_FIELDS}
    data.update(overrides)
    return data


def test_out_of_order_page_preserved_and_sums():
    rows=[{'rrdId': 900, 'docTypeName': 'Продажа', 'forPay': '10.00'},
          {'rrdId': 1200, 'docTypeName': 'Возврат', 'forPay': '3.00'},
          {'rrdId': 100, 'docTypeName': 'Продажа', 'forPay': '2.00'}]
    audit=analyze(rows, expectations(for_pay=Decimal('9.00')))
    assert audit['order_breaks']==1
    assert audit['last_rrd']==100 and audit['max_rrd']==1200
    assert audit['unique_rrd']==3 and audit['duplicates']==0
    assert audit['sums']['for_pay']=='9.00'
    assert audit['all_expected_match']


def test_duplicate_rrd_detected():
    audit=analyze([{'rrdId': 1},{'rrdId':1}], expectations())
    assert audit['duplicates']==1
    assert not audit['unique_rows_match_excel']


def test_invalid_row_rejected():
    with pytest.raises(ValueError):
        analyze([{'docTypeName':'Продажа'}], expectations())


def test_real_expected_sums_schema():
    expected=expectations(retail=Decimal('5505301.23'), for_pay=Decimal('5882492.65'))
    audit=analyze([],expected)
    assert audit['matches']['retail'] is False
    assert audit['matches']['for_pay'] is False
