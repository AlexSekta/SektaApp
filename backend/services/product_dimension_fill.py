"""Pure, conservative WB -> master catalog fill planning."""
from decimal import Decimal
from backend.services.product_dimensions_audit import FIELDS, positive


def plan_fill(master, remote):
    """Only missing/invalid catalog fields and positive finite WB centimeters."""
    changes = []
    for field in FIELDS:
        existing = positive(getattr(master, field, None))
        incoming = positive((remote or {}).get(field))
        if getattr(master, field, None) is None and incoming is not None:
            # Reject values not representable by master_products Numeric(10,2).
            if incoming > Decimal('99999999.99') or incoming != incoming.quantize(Decimal('0.01')):
                continue
            changes.append({'field': field, 'old_cm': None, 'new_cm': float(incoming)})
    return changes
