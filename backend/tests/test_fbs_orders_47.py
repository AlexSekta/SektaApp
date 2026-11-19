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
    assert group_for_status('cancelled') == 'cancelled'


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


def test_ozon_date_filter_cancelled_count_and_sort_order():
    from backend.api.fbs_orders_47 import _base_where, _group_sql
    assert 'COALESCE(ozon_created_at, first_seen_at)>=:start' in _base_where()
    assert 'COALESCE(ozon_created_at, first_seen_at)<:end' in _base_where()
    assert "WHEN status='cancelled' THEN 'cancelled'" in _group_sql()

    class Result:
        def __init__(self, value): self.value = value
        def mappings(self): return self
        def one(self): return self.value
        def all(self): return self.value
        def scalar(self): return self.value
        def scalar_one(self): return self.value

    class DB:
        def __init__(self): self.sql = []
        def execute(self, query, params=None):
            sql = str(query)
            self.sql.append(sql)
            if 'to_regclass' in sql: return Result('ozon_fbs_sticker_archive')
            if 'count(*) FILTER' in sql: return Result(dict(new_count=1, assembly_count=2, delivery_count=3, cancelled_count=4, all_count=10))
            if 'SELECT count(*) FROM' in sql: return Result(4)
            if 'SELECT posting_number' in sql: return Result([])
            raise AssertionError(sql)

    req = SimpleNamespace(state=SimpleNamespace(user=object(), organization_id=2))
    db = DB()
    result = orders_list(req, 'OZON', 'cancelled', date(2026,11,1), date(2026,11,18), '', 50, 0, db=db)
    assert result['total'] == 4
    assert result['counts']['cancelled_count'] == 4
    assert any('ORDER BY COALESCE(ozon_created_at, first_seen_at) DESC' in sql for sql in db.sql)
    assert any("WHEN status='cancelled' THEN 'cancelled'" in sql for sql in db.sql)
