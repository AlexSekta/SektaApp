r"""Read-only WB Finance API diagnostic.

First: python -m backend.scripts.wb_finance_probe --org 2 --from 2026-10-12 --to 2026-10-18
Then, after at least 65 seconds:
  python -m backend.scripts.wb_finance_probe --org 2 --report-id 123456789

No database writes or storage of financial source records. Never prints tokens or raw API responses.
"""
import argparse
from collections import Counter
from datetime import date
from decimal import Decimal, InvalidOperation
from urllib.parse import urljoin

import requests
from backend.database import SessionLocal
from backend.auth.tenant import set_app_db_role, set_tenant_context, clear_tenant_context, reset_app_db_role
from backend.services.marketplace_clients import get_wb_client

HOST = 'https://finance-api.wildberries.ru'


def amount(value):
    try:
        return Decimal(str(value or 0))
    except (InvalidOperation, ValueError, TypeError):
        return Decimal(0)


def post_finance(token, path, payload):
    try:
        resp = requests.post(urljoin(HOST, path), headers={'Authorization': token, 'Content-Type': 'application/json'}, json=payload, timeout=(15, 75), allow_redirects=False)
    except requests.RequestException as err:
        print(f'WB_FINANCE_NETWORK_ERROR type={type(err).__name__}')
        return None
    print(f'WB_FINANCE_HTTP status={resp.status_code}')
    if resp.status_code == 204:
        print('WB_FINANCE_NO_DATA')
        return []
    if resp.status_code != 200:
        print('WB_FINANCE_ERROR: verify Finance permission, method parameters and rate limit; response hidden')
        return None
    try:
        result = resp.json()
    except ValueError:
        print('WB_FINANCE_ERROR response_non_json')
        return None
    if isinstance(result, dict):
        # Do not assume a response wrapper in advance.
        for key in ('data', 'items', 'reports', 'rows'):
            if isinstance(result.get(key), list):
                result = result[key]
                break
    if not isinstance(result, list):
        print(f'WB_FINANCE_UNEXPECTED_RESPONSE type={type(result).__name__} keys={list(result)[:12] if isinstance(result, dict) else []}')
        return None
    return result


def report_list(token, start, end):
    payload = {'dateFrom': start.isoformat(), 'dateTo': end.isoformat(), 'period': 'weekly', 'limit': 100, 'offset': 0}
    print(f'WB_FINANCE_LIST from={start} to={end}')
    rows = post_finance(token, '/api/finance/v1/sales-reports/list', payload)
    if rows is None:
        return 2
    print(f'WB_FINANCE_LIST_ROWS count={len(rows)}')
    for r in rows:
        if not isinstance(r, dict):
            continue
        print('WB_FINANCE_REPORT report_id={} date_from={} date_to={} penalty={} deduction={} for_pay={}'.format(
            r.get('reportId'), r.get('dateFrom'), r.get('dateTo'),
            r.get('penaltySum'), r.get('deductionSum'), r.get('forPaySum')))
    if len(rows) >= 100:
        print('WB_FINANCE_LIST_PAGINATION_REQUIRED: limit reached')
    return 0


def details(token, report_id, limit):
    print(f'WB_FINANCE_DETAIL report_id={report_id} max_rows={limit}')
    rows = post_finance(token, f'/api/finance/v1/sales-reports/detailed/{report_id}',
                        {'limit': limit, 'rrdId': 0, 'fields': []})
    if rows is None:
        return 2
    print(f'WB_FINANCE_DETAIL_ROWS count={len(rows)}')
    fields = sorted({key for row in rows if isinstance(row, dict) for key in row})
    print('WB_FINANCE_FIELDS ' + ','.join(fields))
    stats = Counter()
    totals = Counter()
    reasons = Counter()
    for r in rows:
        if not isinstance(r, dict):
            continue
        sku = r.get('nmId') or r.get('vendorCode') or r.get('saName')
        has_sku = bool(sku)
        for label, key in [('penalty', 'penalty'), ('deduction', 'deduction'), ('additional_payment', 'additionalPayment')]:
            value = amount(r.get(key))
            if value:
                stats[f'{label}_rows'] += 1
                totals[f'{label}_{"with_sku" if has_sku else "without_sku"}'] += value
                reason = str(r.get('bonusTypeName') or r.get('supplierOperName') or r.get('docTypeName') or 'unknown')[:90]
                reasons[(label, reason, bool(has_sku))] += 1
    for k in sorted(stats):
        print(f'WB_FINANCE_STAT {k}={stats[k]}')
    for k in sorted(totals):
        print(f'WB_FINANCE_AMOUNT {k}={totals[k]}')
    for (kind, reason, has_sku), n in reasons.most_common(20):
        print(f'WB_FINANCE_REASON type={kind} sku_present={has_sku} rows={n} reason={reason!r}')
    if len(rows) >= limit:
        print('WB_FINANCE_DETAIL_PARTIAL: page limit reached; do NOT treat totals as full report. Use rrdId pagination in future implementation.')
    print('WB_FINANCE_NOTE: sku_present is only an identification check; NOT a final expense allocation rule.')
    return 0


def main():
    parser = argparse.ArgumentParser(description='Read-only WB Finance API diagnostic')
    parser.add_argument('--org', type=int, required=True)
    parser.add_argument('--from', dest='start', type=date.fromisoformat)
    parser.add_argument('--to', dest='end', type=date.fromisoformat)
    parser.add_argument('--report-id', type=int)
    parser.add_argument('--limit', type=int, default=300)
    args = parser.parse_args()
    if args.report_id is None:
        if not args.start or not args.end or args.start > args.end or (args.end - args.start).days > 31:
            parser.error('provide --from and --to (up to 32 days) or --report-id')
    if not (1 <= args.limit <= 1000):
        parser.error('--limit must be between 1 and 1000')
    db = SessionLocal()
    try:
        set_app_db_role(db)
        set_tenant_context(db, args.org)
        wb = get_wb_client(db)
        auth = wb.headers.get('Authorization') or wb.headers.get('authorization')
        if not auth:
            print('WB_FINANCE_ERROR no WB authorization in saved credentials')
            return 2
        return details(auth, args.report_id, args.limit) if args.report_id is not None else report_list(auth, args.start, args.end)
    except Exception as exc:
        # Redact potentially sensitive error text; no credential material in console.
        print(f'WB_FINANCE_ERROR type={type(exc).__name__}; check configured WB key and tenant permissions')
        return 3
    finally:
        try:
            clear_tenant_context(db)
            reset_app_db_role(db)
        finally:
            db.close()


if __name__ == '__main__':
    raise SystemExit(main())
