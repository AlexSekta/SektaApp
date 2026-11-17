from backend.services.catalog_dimension_issues_24 import dimension_issue


def test_matches():
    assert dimension_issue([7, 7, 24], [7, 7, 24]) is None


def test_mismatch():
    assert dimension_issue([7, 7, 24], [26.2, 9.1, 10.2])['code'] == 'DIFFERENT'


def test_unknown_remote_not_false_missing():
    assert dimension_issue([7, 7, 24], [None, None, None], 'API_ERROR') is None
    assert dimension_issue([7, 7, 24], [None, None, None], 'UNKNOWN') is None


def test_missing():
    assert dimension_issue([7, 7, 24], [None, None, None])['code'] == 'MARKETPLACE_MISSING'
    assert dimension_issue([None, None, None], [7, 7, 24])['code'] == 'CATALOG_MISSING'


def test_rounding_tolerance():
    assert dimension_issue([7, 7, 24], [7.03, 7.0, 24.0]) is None
