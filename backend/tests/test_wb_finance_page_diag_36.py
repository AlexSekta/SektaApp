"""No database or API access."""
from backend.services.wb_finance_page_diag_36 import summarize_page


def test_empty():
    info = summarize_page([], 10)
    assert info['page_rows'] == 0
    assert info['page_last'] is None
    assert info['ahead'] == 0


def test_normal_ascending():
    info = summarize_page([{'rrdId': 11}, {'rrdId': 12}, {'rrdId': 13}], 10)
    assert info['page_first'] == 11
    assert info['page_last'] == 13
    assert info['ahead'] == 3
    assert info['asc_breaks'] == 0
    assert info['last_is_max'] is True


def test_non_monotonic_and_last_not_max():
    info = summarize_page([{'rrdId': 15}, {'rrdId': 18}, {'rrdId': 16}], 14)
    assert info['page_last'] == 16
    assert info['page_max'] == 18
    assert info['asc_breaks'] == 1
    assert info['last_is_max'] is False


def test_stalled_cursor_and_repeat_ids():
    info = summarize_page([{'rrdId': 2}, {'rrdId': 2}, {'rrdId': 5}], 10)
    assert info['ahead'] == 0
    assert info['at_or_behind'] == 3
    assert info['distinct'] == 2


def test_mixed_ahead_and_behind():
    info = summarize_page([{'rrdId': 100}, {'rrdId': 110}], 100)
    assert info['ahead'] == 1
    assert info['at_or_behind'] == 1
