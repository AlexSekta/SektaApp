r"""Read-only complete WB Finance report diagnosis using the saved organization's WB API key.

Usage:
  python -m backend.scripts.wb_finance_full_probe --org 2 --report-id 875856102 \
      --expected-penalty 21726.73 --expected-deduction 42990

No database modifications and no source-row exports. A page request is spaced by 65 s.
"""
import argparse
import time
from collections import defaultdict
from decimal import Decimal, InvalidOperation

from backend.database import SessionLocal
from backend.auth.tenant import (
    set_app_db_role, set_tenant_context, clear_tenant_context, reset_app_db_role,
)
from backend.services.marketplace_clients import get_wb_client
from backend.scripts.wb_finance_probe import post_finance


def decimal_of(value):
    if value is None or value == '':
        return Decimal(0)
    try:
        return Decimal(str(value))
    except (InvalidOperation, ValueError, TypeError):
        raise ValueError('invalid amount in finance response')


def normalize_identifier(value):
    if value is None:
        return None
    value = str(value).strip()
    if not value or value == '0':
        return None
    return value


def read_report(token, report_id, limit, gap, max_pages):
    cursor = 0
    seen_rrd = set()
    seen_pages = set()
    stats = defaultdict(lambda: {'rows': 0, 'amount': Decimal(0)})
    totals = defaultdict(Decimal)
    page = 0
    total_rows = 0
    while page < max_pages:
        if page:
            time.sleep(gap)
        page += 1
        print(f'WB_FINANCE_PAGE_REQUEST page={page} rrd_id={cursor} limit={limit}', flush=True)
        rows = post_finance(token, f'/api/finance/v1/sales-reports/detailed/{report_id}',
                            {'limit': limit, 'rrdId': cursor, 'fields': []})
        if rows is None:
            print('WB_FINANCE_INCOMPLETE: HTTP or response error; no final reconciliation')
            return 2
        if not rows:
            print('WB_FINANCE_END empty_page')
            break
        if any(not isinstance(r, dict) or r.get('rrdId') is None for r in rows):
            print('WB_FINANCE_INCOMPLETE: missing rrdId / unexpected row')
            return 2
        ids = []
        try:
            ids = [int(r['rrdId']) for r in rows]
        except (ValueError, TypeError):
            print('WB_FINANCE_INCOMPLETE: invalid rrdId')
            return 2
        signature = (ids[0], ids[-1], len(ids))
        if signature in seen_pages or max(ids) <= cursor:
            print('WB_FINANCE_INCOMPLETE: repeating or non-advancing page')
            return 2
        seen_pages.add(signature)
        new_count = 0
        for row, rid in zip(rows, ids):
            if rid in seen_rrd:
                continue
            seen_rrd.add(rid)
            new_count += 1
            has_product = any(normalize_identifier(row.get(k)) for k in ('nmId', 'vendorCode', 'sku'))
            reason = str(row.get('bonusTypeName') or row.get('sellerOperName') or row.get('docTypeName') or 'Не указана').replace('\n', ' ')[:110]
            for kind, field in (('Штраф', 'penalty'), ('Удержание', 'deduction'), ('Доплата', 'additionalPayment')):
                try:
                    amt = decimal_of(row.get(field))
                except ValueError:
                    print(f'WB_FINANCE_INCOMPLETE: invalid {field} value')
                    return 2
                totals[kind] += amt
                if amt:
                    mode = 'есть_идентификатор_товара' if has_product else 'нет_идентификатора_товара'
                    x = stats[(kind, mode, reason)]
                    x['rows'] += 1
                    x['amount'] += amt
        total_rows += new_count
        next_cursor = max(ids)
        print(f'WB_FINANCE_PAGE_OK page={page} received={len(rows)} unique_new={new_count} rrd_next={next_cursor}', flush=True)
        if next_cursor <= cursor:
            print('WB_FINANCE_INCOMPLETE: cursor did not advance')
            return 2
        cursor = next_cursor
        if len(rows) < limit:
            print('WB_FINANCE_END short_page')
            break
    else:
        print('WB_FINANCE_INCOMPLETE: max-pages safety limit reached')
        return 2
    print(f'WB_FINANCE_COMPLETE pages={page} unique_rows={total_rows}')
    for kind in ('Штраф', 'Удержание', 'Доплата'):
        print(f'WB_FINANCE_TOTAL kind={kind} amount={totals[kind]}')
    print('WB_FINANCE_GROUPS: sorted by absolute total; groups with no product identifier are not necessarily general costs')
    for (kind, mode, reason), obj in sorted(stats.items(), key=lambda x: abs(x[1]['amount']), reverse=True):
        print(f'WB_FINANCE_GROUP kind={kind} link={mode} rows={obj["rows"]} amount={obj["amount"]} reason={reason!r}')
    print('WB_FINANCE_NOTE: product identifier is preliminary only; final allocation requires reason-based validation.')
    return totals


def main():
    p = argparse.ArgumentParser(description='WB Finance complete report, read-only')
    p.add_argument('--org', required=True, type=int)
    p.add_argument('--report-id', required=True, type=int)
    p.add_argument('--limit', type=int, default=1000)
    p.add_argument('--request-gap', type=int, default=65)
    p.add_argument('--max-pages', type=int, default=300)
    p.add_argument('--expected-penalty', type=Decimal)
    p.add_argument('--expected-deduction', type=Decimal)
    args = p.parse_args()
    if args.limit < 1 or args.limit > 1000 or args.request_gap < 65 or args.max_pages < 1:
        p.error('limit 1..1000, request-gap >=65, max-pages >=1')
    db = SessionLocal()
    try:
        set_app_db_role(db)
        set_tenant_context(db, args.org)
        wb = get_wb_client(db)
        token = wb.headers.get('Authorization') or wb.headers.get('authorization')
        if not token:
            print('WB_FINANCE_ERROR missing Finance token')
            return 2
        result = read_report(token, args.report_id, args.limit, args.request_gap, args.max_pages)
        if isinstance(result, int):
            return result
        for label, kind, expected in (('penalty', 'Штраф', args.expected_penalty), ('deduction', 'Удержание', args.expected_deduction)):
            if expected is not None:
                difference = result[kind] - expected
                print(f'WB_FINANCE_RECONCILE kind={label} expected={expected} details={result[kind]} difference={difference} matches={difference == 0}')
        return 0
    except Exception as ex:
        # Avoid printing API tokens or financial data in exception messages.
        print(f'WB_FINANCE_ERROR type={type(ex).__name__}; details hidden')
        return 3
    finally:
        try:
            clear_tenant_context(db)
            reset_app_db_role(db)
        finally:
            db.close()


if __name__ == '__main__':
    raise SystemExit(main())
