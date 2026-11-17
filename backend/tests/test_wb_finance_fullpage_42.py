from decimal import Decimal
import pytest

from backend.services.wb_finance_fullpage_42 import (
    FULL_LIMIT, FullPageValidationError, needs_recovery, validate_full_page,
)


def test_normal_forward_pages_stay_on_regular_pagination():
    assert not needs_recovery([{'rrdId': 11}, {'rrdId': 12}], 10)
    assert not needs_recovery([], 10)


def test_backwards_end_page_triggers_recovery():
    assert needs_recovery([{'rrdId': 101}, {'rrdId': 102}, {'rrdId': 30}], 100)
    assert needs_recovery([{'rrdId': 5}, {'rrdId': 6}], 50)
    assert needs_recovery([{'rrdId': 51}, {'rrdId': 51}], 50)


def row(rrd, *, doc='Продажа', amount='10', logistics='2'):
    return {'rrdId': rrd, 'docTypeName': doc, 'retailAmount': amount,
            'forPay': amount, 'deliveryService': logistics}


def expected(**changes):
    data = {'expected_retail': Decimal('10'), 'expected_for_pay': Decimal('10'),
            'expected_logistics': Decimal('4'), 'expected_storage': Decimal(0),
            'expected_acceptance': Decimal(0), 'expected_penalty': Decimal(0),
            'expected_deduction': Decimal(0), 'expected_additional_payment': Decimal(0)}
    data.update(changes)
    return data


def test_out_of_order_complete_data_is_valid_when_all_totals_match():
    result = validate_full_page([row(2, amount='20'), row(1, doc='Возврат', amount='10')], expected())
    assert result['count'] == 2
    assert result['max_rrd'] == 2
    assert result['ids'] == {1, 2}


def test_return_sign_from_operation_when_doc_missing():
    rows = [row(2, amount='20'), {**row(1, amount='10'), 'docTypeName': '', 'sellerOperName': 'Возврат'}]
    assert validate_full_page(rows, expected())['count'] == 2


@pytest.mark.parametrize('rows,limit,reason', [
    ([row(1),row(1)], FULL_LIMIT, 'full_page_duplicate_rrd'),
    ([row(1)], 1, 'full_page_missing_or_truncated'),
    ([], FULL_LIMIT, 'full_page_missing_or_truncated'),
    ([row(0)], FULL_LIMIT, 'full_page_invalid_rrd'),
    ([row(1,amount='NaN')], FULL_LIMIT, 'full_page_nonfinite_amount'),
])
def test_reject_ambiguous_source(rows,limit,reason):
    with pytest.raises(FullPageValidationError, match=reason):
        validate_full_page(rows,expected(),limit=limit)


def test_reject_bad_financial_control():
    with pytest.raises(FullPageValidationError, match='full_page_totals_mismatch'):
        validate_full_page([row(1)],expected())


def test_reject_unknown_controls():
    with pytest.raises(FullPageValidationError, match='full_page_no_control_totals'):
        validate_full_page([row(1)],{key:None for key in expected()})


def test_probe_keeps_default_timeout_and_override():
    from unittest.mock import Mock,patch
    from backend.scripts.wb_finance_probe import post_finance
    response=Mock(status_code=204)
    with patch('backend.scripts.wb_finance_probe.requests.post', return_value=response) as p:
        assert post_finance('TEST','/dummy',{'limit':10}) == []
        assert p.call_args.kwargs['timeout'] == (15,75)
        assert post_finance('TEST','/dummy',{'limit':10},timeout=(20,240)) == []
        assert p.call_args.kwargs['timeout'] == (20,240)
