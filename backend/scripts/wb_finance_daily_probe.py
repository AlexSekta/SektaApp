"""Read-only diagnostic for WB Finance *daily* report headers and a limited detail page.

Uses existing encrypted organization credentials and the Finance client from probe #42.
Does not print identifiers of bank accounts, raw lines, token, or API response bodies.
"""
import argparse
from datetime import date
from decimal import Decimal, InvalidOperation

from backend.database import SessionLocal
from backend.auth.tenant import set_app_db_role, set_tenant_context, clear_tenant_context, reset_app_db_role
from backend.services.marketplace_clients import get_wb_client
from backend.scripts.wb_finance_probe import post_finance


def num(value):
    try:
        return Decimal(str(value or 0))
    except (InvalidOperation, TypeError, ValueError):
        return Decimal(0)


def list_daily(token, day):
    print(f'WB_DAILY_LIST day={day}')
    rows = post_finance(token, '/api/finance/v1/sales-reports/list', {
        'dateFrom': day.isoformat(), 'dateTo': day.isoformat(), 'period': 'daily',
        'limit': 100, 'offset': 0,
    })
    if rows is None:
        print('WB_DAILY_ERROR list_request_failed')
        return 2
    print(f'WB_DAILY_COUNT {len(rows)}')
    for r in rows:
        if not isinstance(r, dict):
            continue
        print('WB_DAILY_REPORT report_id={} from={} to={} created={} type={}'.format(
            r.get('reportId'), r.get('dateFrom'), r.get('dateTo'),
            r.get('createDate') or r.get('createdAt'), r.get('reportType')))
        for k in sorted(r):
            # Restrict printed data to aggregate financial fields, never raw financial metadata.
            if k in ('reportId', 'dateFrom', 'dateTo', 'createDate', 'createdAt', 'reportType'):
                continue
            if isinstance(r[k], (int, float, str)) and any(s in k.lower() for s in
                ('sum', 'penalty', 'deduction', 'storage', 'delivery', 'commission',
                 'acquiring', 'payment', 'sale', 'return', 'forpay', 'amount', 'acceptance')):
                print(f'WB_DAILY_FIELD {k}={r[k]}')
    if len(rows) == 100:
        print('WB_DAILY_WARNING list_page_full; more reports may exist')
    return 0


def details_daily(token, report_id, limit):
    print(f'WB_DAILY_DETAIL report_id={report_id} limit={limit} (sample only)')
    rows = post_finance(token, f'/api/finance/v1/sales-reports/detailed/{report_id}', {
        'limit': limit, 'rrdId': 0, 'fields': [],
    })
    if rows is None:
        return 2
    print(f'WB_DAILY_DETAIL_ROWS {len(rows)}')
    keys = sorted({k for r in rows if isinstance(r, dict) for k in r})
    print('WB_DAILY_FIELDS ' + ','.join(keys))
    amounts = ('retailAmount', 'retailPriceWithDisc', 'forPay', 'ppvzSalesCommission',
               'acquiringFee', 'deliveryService', 'deliveryAmount', 'paidStorage',
               'paidAcceptance', 'penalty', 'deduction', 'additionalPayment',
               'rebillLogisticCost', 'paymentProcessing', 'returnAmount')
    for k in amounts:
        present = sum(1 for r in rows if isinstance(r, dict) and r.get(k) is not None)
        if present:
            total = sum((num(r.get(k)) for r in rows if isinstance(r, dict)), Decimal(0))
            print(f'WB_DAILY_DETAIL_AGG field={k} rows={present} sum={total}')
    reasons = {}
    for r in rows:
        if not isinstance(r, dict):
            continue
        name = str(r.get('sellerOperName') or r.get('bonusTypeName') or r.get('docTypeName') or 'Без основания')
        if num(r.get('penalty')) or num(r.get('deduction')):
            previous = reasons.get(name, (0, Decimal(0), Decimal(0)))
            reasons[name] = (previous[0]+1, previous[1]+num(r.get('penalty')), previous[2]+num(r.get('deduction')))
    for name, (count, penalty, deduction) in sorted(reasons.items(), key=lambda item: -(item[1][1]+item[1][2]))[:15]:
        print(f'WB_DAILY_EXPENSE_REASON count={count} penalty={penalty} deduction={deduction} reason={name[:100]!r}')
    print('WB_DAILY_NOTE These are sample-page sums, NOT a complete financial reconciliation. Reports have distinct operation types and may include reversals.')
    if len(rows) >= limit:
        print('WB_DAILY_PARTIAL page_full=true; use pagination for a full report')
    return 0


def main():
    p = argparse.ArgumentParser(description='Diagnostic daily WB finance report without database writes')
    p.add_argument('--org', type=int, required=True)
    group = p.add_mutually_exclusive_group(required=True)
    group.add_argument('--date', type=date.fromisoformat)
    group.add_argument('--report-id', type=int)
    p.add_argument('--limit', type=int, default=300)
    args = p.parse_args()
    if not 1 <= args.limit <= 1000:
        p.error('--limit must be between 1 and 1000')
    db = SessionLocal()
    try:
        set_app_db_role(db)
        set_tenant_context(db, args.org)
        client = get_wb_client(db)
        token = client.headers.get('Authorization') or client.headers.get('authorization')
        if not token:
            print('WB_DAILY_ERROR missing WB token')
            return 2
        return list_daily(token, args.date) if args.date else details_daily(token, args.report_id, args.limit)
    except Exception as exc:
        print(f'WB_DAILY_ERROR type={type(exc).__name__}; details suppressed to protect credentials')
        return 3
    finally:
        try:
            clear_tenant_context(db)
            reset_app_db_role(db)
        finally:
            db.close()

if __name__ == '__main__':
    raise SystemExit(main())
