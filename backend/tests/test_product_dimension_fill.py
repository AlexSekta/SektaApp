from types import SimpleNamespace
from backend.services.product_dimension_fill import plan_fill
from backend.services.product_dimensions_audit import dimension_issues


def test_only_blank_fields_filled_and_others_untouched():
    master = SimpleNamespace(length_cm=None, width_cm=9, height_cm=None)
    changes = plan_fill(master, {'length_cm': 9, 'width_cm': 11, 'height_cm': 8})
    assert [(c['field'], c['new_cm']) for c in changes] == [('length_cm', 9.0), ('height_cm', 8.0)]
    assert master.length_cm is None and master.width_cm == 9


def test_missing_remote_dimension_never_filled_but_audited():
    master = SimpleNamespace(length_cm=None, width_cm=None, height_cm=4)
    remote = {'length_cm': 9, 'width_cm': None, 'height_cm': None}
    assert [c['field'] for c in plan_fill(master, remote)] == ['length_cm']
    assert {c['code'] for c in dimension_issues(master, remote)} == {'CATALOG_DIMENSION_MISSING', 'MARKETPLACE_DIMENSION_MISSING'}


def test_invalid_values_and_overprecise_values_not_imported():
    m = SimpleNamespace(length_cm=None, width_cm=None, height_cm=None)
    assert plan_fill(m, {'length_cm': 0, 'width_cm': -1, 'height_cm': 'NaN'}) == []
    assert plan_fill(m, {'length_cm': 2.555, 'width_cm': 999999999, 'height_cm': 4}) == [
        {'field': 'height_cm', 'old_cm': None, 'new_cm': 4.0}]


def test_no_change_for_existing_catalog_values():
    m = SimpleNamespace(length_cm=10, width_cm=10, height_cm=10)
    assert plan_fill(m, {'length_cm': 5, 'width_cm': 0, 'height_cm': 10}) == []
