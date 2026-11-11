"""Read-only comparison of marketplace package dimensions against master catalog."""
from decimal import Decimal, InvalidOperation

FIELDS = ('length_cm', 'width_cm', 'height_cm')
LABELS = {'length_cm': 'Длина', 'width_cm': 'Ширина', 'height_cm': 'Высота'}


def positive(value):
    try:
        number = Decimal(str(value))
        return number if number.is_finite() and number > 0 else None
    except (ValueError, TypeError, InvalidOperation):
        return None


def dimension_issues(master, marketplace_dims):
    """Return observable issues; never infer that unknown remote values are zeros."""
    raw = marketplace_dims if isinstance(marketplace_dims, dict) else {}
    problems = []
    for field in FIELDS:
        local = positive(getattr(master, field, None))
        remote = positive(raw.get(field))
        if remote is None:
            code = 'MARKETPLACE_DIMENSION_MISSING'
        elif local is None:
            code = 'CATALOG_DIMENSION_MISSING'
        elif abs(local - remote) > Decimal('0.01'):
            code = 'DIMENSION_MISMATCH'
        else:
            continue
        problems.append({
            'code': code, 'field': field, 'field_label': LABELS[field],
            'catalog_cm': float(local) if local is not None else None,
            'marketplace_cm': float(remote) if remote is not None else None,
        })
    return problems
