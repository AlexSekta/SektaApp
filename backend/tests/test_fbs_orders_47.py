"""No network, no production database access."""
from datetime import date
from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from backend.api.fbs_orders_47 import _dates, _filters, group_for_status, orders_list


def test_status_groups_are_explicit():
    assert group_for_status('awaiting_packaging') == 'new'
    assert group_for_status('awaiting_deliver') == 'assembly'
    assert group_for_status('delivering') == 'delivery'
    assert group_for_status('delivered') == 'delivery'
    assert group_for_status('cancelled') == 'other'


def test_dates_reject_inverted_and_long_period():
    with pytest.raises(HTTPException) as err:
        _dates(date(2026, 11, 19), date(2026, 11, 18))
    assert err.value.status_code == 422
    with pytest.raises(HTTPException):
        _dates(date(2024, 1, 1), date(2026, 11, 18))


def test_filter_search_length():
    with pytest.raises(HTTPException):
        _filters(date(2026, 11, 1), date(2026, 11, 18), 'x' * 101)


def test_market_not_connected_is_explicit_not_zero():
    req = SimpleNamespace(state=SimpleNamespace(user=object(), organization_id=2))
    for market in ('WB', 'YANDEX'):
        result = orders_list(req, market, 'new', date(2026,11,1), date(2026,11,18), '', 50, 0, db=None)
        assert result['available'] is False
        assert result['total'] is None
        assert result['counts'] is None


def test_auth_required_before_any_query():
    req = SimpleNamespace(state=SimpleNamespace(user=None, organization_id=2))
    with pytest.raises(HTTPException) as err:
        orders_list(req, 'OZON', 'all', date(2026,11,1), date(2026,11,18), '', 50, 0, db=None)
    assert err.value.status_code == 401
