from types import SimpleNamespace
from decimal import Decimal
import pytest
from backend.services.product_dimension_manual import plan_manual_dimensions


def test_manual_update_existing_and_missing_fields():
    master = SimpleNamespace(length_cm=Decimal('10.00'), width_cm=None, height_cm=Decimal('8.00'))
    changes = plan_manual_dimensions(master, {'length_cm': 9, 'width_cm': 9, 'height_cm': 8})
    assert [c['field'] for c in changes] == ['length_cm', 'width_cm']
    assert changes[0]['old_cm'] == 10.0
    assert changes[1]['old_cm'] is None


def test_same_values_no_changes():
    master = SimpleNamespace(length_cm=9, width_cm=9, height_cm=8)
    assert plan_manual_dimensions(master, {'length_cm': 9, 'width_cm': 9, 'height_cm': 8}) == []


@pytest.mark.parametrize('invalid', [0, -1, None, 'nan', 'inf', '1.234', 100000000])
def test_reject_invalid_dimensions(invalid):
    master = SimpleNamespace(length_cm=1, width_cm=1, height_cm=1)
    with pytest.raises(ValueError):
        plan_manual_dimensions(master, {'length_cm': invalid, 'width_cm': 9, 'height_cm': 8})


def test_require_all_three_values():
    master = SimpleNamespace(length_cm=1, width_cm=1, height_cm=1)
    with pytest.raises(ValueError):
        plan_manual_dimensions(master, {'length_cm': 9})
