r"""Read-only diagnostic of WB Finance API reconciliation for one daily report.

Usage:
 python -m backend.scripts.wb_finance_formula_probe --org 2 --report-id 1190640202610261
No persistent data writes; prints aggregates only, never credentials or raw financial rows.
"""
import argparse
from collections import defaultdict
from decimal import Decimal, InvalidOperation
from backend.database import SessionLocal
from backend.auth.tenant import set_app_db_role, set_tenant_context, clear_tenant_context, reset_app_db_role
from backend.services.marketplace_clients import get_wb_client
from backend.scripts.wb_finance_probe import post_finance

MONEY_FIELDS = (
    'retailAmount', 'retailPriceWithDisc', 'forPay', 'ppvzSalesCommission',
    'vw', 'vwNds', 'acquiringFee', 'paymentProcessing', 'deliveryService',
    'paidStorage', 'paidAcceptance', 'penalty', 'deduction', 'additionalPayment',
    'rebillLogisticCost', 'cashbackAmount', 'cashbackDiscount',
    'returnAmount', 'deliveryAmount', 'ppvzReward', 'kvw', 'kvwBase',
)

def dec(value):
    try:
        return Decimal(str(value if value is not None else 0))
    except (InvalidOperation, ValueError, TypeError):
        return Decimal(0)

def run(token: str, report_id: int, limit: int) -> int:
    print(f'WB_FORMULA_REQUEST report_id={report_id} limit={limit}')
    rows = post_finance(token, f'/api/finance/v1/sales-reports/detailed/{report_id}',
                        {'limit': limit, 'rrdId': 0, 'fields': []})
    if rows is None:
        return 2
    if not rows:
        print('WB_FORMULA_EMPTY')
        return 0
    if not all(isinstance(r, dict) for r in rows):
        print('WB_FORMULA_INVALID_ROWS')
        return 2
    totals = {f: sum((dec(r.get(f)) for r in rows), Decimal(0)) for f in MONEY_FIELDS}
    seen = {f: sum(1 for r in rows if r.get(f) is not None) for f in MONEY_FIELDS}
    print(f'WB_FORMULA_ROWS count={len(rows)} complete_candidate={len(rows)<limit}')
    if len(rows) >= limit:
        print('WB_FORMULA_PARTIAL: full pagination required before any reconciliation')
    for field in MONEY_FIELDS:
        print(f'WB_FORMULA_FIELD name={field} sum={totals[field]} present={seen[field]}')
    report_total = totals['retailAmount']
    for_fee = totals['ppvzSalesCommission']
    acquiring = totals['acquiringFee']
    forpay = totals['forPay']
    discrepancy = report_total - for_fee - acquiring - forpay
    print(f'WB_FORMULA_RESIDUAL retail_minus_commission_acquiring_forpay={discrepancy}')
    print(f'WB_FORMULA_VAT_TEST reported_vwNds={totals["vwNds"]} delta_from_residual={discrepancy - totals["vwNds"]}')
    print(f'WB_FORMULA_VW_TEST reported_vw={totals["vw"]} reported_ppvzSalesCommission={for_fee}')
    types = defaultdict(lambda: defaultdict(Decimal))
    counts = defaultdict(int)
    for r in rows:
        kind = str(r.get('docTypeName') or r.get('sellerOperName') or 'Не указано')[:90]
        counts[kind] += 1
        for field in ('retailAmount','forPay','ppvzSalesCommission','vw','vwNds','acquiringFee','deliveryService','penalty','deduction'):
            types[kind][field] += dec(r.get(field))
    for kind, count in sorted(counts.items(), key=lambda pair: (-pair[1],pair[0])):
        t = types[kind]
        print(f'WB_FORMULA_OPERATION type={kind!r} rows={count} retail={t["retailAmount"]} forpay={t["forPay"]} commission={t["ppvzSalesCommission"]} vat={t["vwNds"]} acquiring={t["acquiringFee"]} logistics={t["deliveryService"]} penalty={t["penalty"]} deduction={t["deduction"]}')
    print('WB_FORMULA_NOTE: This is a field comparison, not a confirmed VAT allocation until checked against Excel per-operation semantics.')
    return 0

def main() -> int:
    ap = argparse.ArgumentParser(description='Read-only daily WB Finance field reconciliation')
    ap.add_argument('--org', type=int, required=True)
    ap.add_argument('--report-id', type=int, required=True)
    ap.add_argument('--limit', type=int, default=1000)
    args = ap.parse_args()
    if not 1 <= args.limit <= 1000:
        ap.error('--limit must be between 1 and 1000')
    db = SessionLocal()
    try:
        set_app_db_role(db)
        set_tenant_context(db, args.org)
        token = get_wb_client(db).headers.get('Authorization')
        if not token:
            print('WB_FORMULA_ERROR missing WB API key')
            return 2
        return run(token, args.report_id, args.limit)
    except Exception as exc:
        print(f'WB_FORMULA_ERROR type={type(exc).__name__}')
        return 3
    finally:
        try:
            clear_tenant_context(db)
            reset_app_db_role(db)
        finally:
            db.close()

if __name__ == '__main__':
    raise SystemExit(main())
