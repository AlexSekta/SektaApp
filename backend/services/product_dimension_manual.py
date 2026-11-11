"""Validate and plan an explicit, per-product change of package dimensions."""
from decimal import Decimal
from backend.services.product_dimensions_audit import FIELDS, positive

MAX_CM = Decimal('99999999.99')


def plan_manual_dimensions(master, proposed):
    if not isinstance(proposed, dict) or set(proposed) != set(FIELDS):
        raise ValueError('Передайте длину, ширину и высоту')
    changes = []
    for field in FIELDS:
        raw = proposed[field]
        value = positive(raw)
        if (value is None or value > MAX_CM or
                value != value.quantize(Decimal('0.01'))):
            raise ValueError('Все габариты должны быть положительными числами с точностью до 0,01 см')
        old = getattr(master, field, None)
        old_value = Decimal(str(old)) if old is not None else None
        if old_value != value:
            changes.append({'field': field, 'old_cm': float(old_value) if old_value is not None else None,
                            'new_cm': float(value)})
    return changes
