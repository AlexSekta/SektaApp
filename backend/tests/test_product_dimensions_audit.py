"""Dimension audit is pure and must not modify the product."""
from types import SimpleNamespace
from backend.services.product_dimensions_audit import dimension_issues


def test_missing_remote_dimension_is_problem_even_when_catalog_filled():
    product = SimpleNamespace(length_cm=13, width_cm=6, height_cm=23)
    issues = dimension_issues(product, {'length_cm': 13, 'width_cm': None, 'height_cm': 23})
    assert [(p['code'], p['field']) for p in issues] == [('MARKETPLACE_DIMENSION_MISSING', 'width_cm')]
    assert product.width_cm == 6


def test_empty_local_and_mismatch_reported_separately():
    product = SimpleNamespace(length_cm=None, width_cm=6, height_cm=23)
    issues = dimension_issues(product, {'length_cm': 13, 'width_cm': 7, 'height_cm': 23})
    assert {p['code'] for p in issues} == {'CATALOG_DIMENSION_MISSING', 'DIMENSION_MISMATCH'}


def test_all_remote_dimensions_absent_reports_three_issues():
    product = SimpleNamespace(length_cm=13, width_cm=6, height_cm=23)
    assert len(dimension_issues(product, None)) == 3


def test_equal_sizes_ignore_tiny_rounding_difference():
    product = SimpleNamespace(length_cm=13, width_cm=6, height_cm=23)
    assert dimension_issues(product, {'length_cm': 13, 'width_cm': 6, 'height_cm': 23}) == []
