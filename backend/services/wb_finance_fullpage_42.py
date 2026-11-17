"""Validation for safe WB weekly report full-page recovery (no DB writes).

WB may return out-of-order rrdId in otherwise valid report detail pages.
A full response with all row IDs and expected totals is a safe recovery source.
"""
from decimal import Decimal

FULL_LIMIT = 100000
FIELD_MAP = {
    'expected_retail': 'retailAmount',
    'expected_for_pay': 'forPay',
    'expected_logistics': 'deliveryService',
    'expected_storage': 'paidStorage',
    'expected_acceptance': 'paidAcceptance',
    'expected_penalty': 'penalty',
    'expected_deduction': 'deduction',
    'expected_additional_payment': 'additionalPayment',
}


class FullPageValidationError(ValueError):
    pass


def needs_recovery(rows, cursor):
    """Non-increasing, duplicate or backwards IDs make normal cursor pagination unsafe."""
    ids = [int(r['rrdId']) for r in rows]
    return bool(ids) and (len(ids) != len(set(ids)) or
                          any(b <= a for a, b in zip(ids, ids[1:])) or
                          any(rid <= cursor for rid in ids))


def validate_full_page(rows, expected, *, limit=FULL_LIMIT):
    """Reject ambiguous/truncated responses before touching production entries."""
    if not isinstance(rows, list) or not rows or len(rows) >= limit:
        raise FullPageValidationError('full_page_missing_or_truncated')
    ids = []
    totals = {field: Decimal('0') for field in FIELD_MAP}
    for row in rows:
        if not isinstance(row, dict):
            raise FullPageValidationError('full_page_invalid_row')
        try:
            rid = int(row['rrdId'])
        except (KeyError, TypeError, ValueError, OverflowError) as exc:
            raise FullPageValidationError('full_page_invalid_rrd') from exc
        if rid <= 0:
            raise FullPageValidationError('full_page_invalid_rrd')
        ids.append(rid)
        doc = str(row.get('docTypeName') or '').strip().lower()
        operation = str(row.get('sellerOperName') or '').strip().lower()
        sign = -1 if ((doc == 'возврат') if doc else (operation == 'возврат')) else 1
        for key, field in FIELD_MAP.items():
            try:
                value = Decimal(str(row.get(field) or 0))
            except (ValueError, TypeError) as exc:
                raise FullPageValidationError('full_page_invalid_amount') from exc
            if not value.is_finite():
                raise FullPageValidationError('full_page_nonfinite_amount')
            totals[key] += sign * value if key in ('expected_retail','expected_for_pay') else value
    if len(set(ids)) != len(ids):
        raise FullPageValidationError('full_page_duplicate_rrd')
    # An independently fetched, bounded full page is only considered complete
    # when EVERY available WB control total matches. Unknown totals are not evidence.
    if not any(expected.get(key) is not None for key in totals):
        raise FullPageValidationError('full_page_no_control_totals')
    mismatches = [key for key, val in totals.items() if expected.get(key) is not None
                  and abs(Decimal(str(expected[key])) - val) > Decimal('0.02')]
    if mismatches:
        raise FullPageValidationError('full_page_totals_mismatch:' + ','.join(mismatches))
    return {'count': len(ids), 'max_rrd': max(ids), 'ids': set(ids), 'totals': totals}
