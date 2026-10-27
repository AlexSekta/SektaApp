"""Read-only order/status audit for comparing Yandex sales-funnel report to orders API.
Run: python -m backend.scripts.yandex_sales_status_audit --day 2026-10-14
No API credentials, buyer details or raw orders are saved.
"""
import argparse
import json
from collections import defaultdict
from datetime import date, timedelta
from decimal import Decimal
from pathlib import Path

from backend.database import SessionLocal
from backend.models.auth import Organization  # noqa: F401
from backend.auth.tenant import (
    legacy_sync_organization_id, set_app_db_role, set_tenant_context,
    clear_tenant_context, reset_app_db_role,
)
from backend.services.marketplace_clients import get_yandex_client, get_yandex_business_id
from backend.scripts.yandex_sales_probe import money, order_local_day, get_page

TARGET_SKUS = {'HS063', 'HS172', 'HS176'}


def _amount(item):
    prices = item.get('prices') or {}
    result = {}
    for field in ('payment', 'cashback', 'subsidy'):
        value, currency = money(prices, field)
        if currency and currency != 'RUR':
            raise ValueError(f'Unexpected currency {currency} for {field}')
        result[field] = value
    return result


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--day', type=date.fromisoformat, default=date(2026, 10, 14))
    args = parser.parse_args()
    db = SessionLocal()
    try:
        org = legacy_sync_organization_id()
        if org is None:
            raise RuntimeError('Organization not configured')
        set_app_db_role(db)
        set_tenant_context(db, org)
        client = get_yandex_client(db)
        business_id = get_yandex_business_id(db, client)
        payload = {
            'dates': {'creationDateFrom': args.day.isoformat(),
                      'creationDateTo': (args.day + timedelta(days=1)).isoformat()},
            'fake': False,
            'sourcePlatforms': ['MARKET'],
        }
        token, tokens, pages, orders = None, set(), 0, {}
        while True:
            response = get_page(client, business_id, payload, token)
            if not isinstance(response, dict) or not isinstance(response.get('orders'), list):
                raise ValueError('Unexpected orders API response')
            pages += 1
            for order in response['orders']:
                orders[str(order['orderId'])] = order
            token = (response.get('paging') or {}).get('nextPageToken')
            if not token:
                break
            if token in tokens or pages >= 500:
                raise RuntimeError('Pagination incomplete')
            tokens.add(token)
        by_status = defaultdict(lambda: {'orders': 0, 'units': 0, 'rub': Decimal(0)})
        details = []
        totals = {'all_units': 0, 'all_rub': Decimal(0), 'noncancelled_units': 0, 'noncancelled_rub': Decimal(0)}
        for order in orders.values():
            if order_local_day(order) != args.day:
                continue
            status = str(order.get('status') or 'UNKNOWN')
            program = str(order.get('programType') or 'UNKNOWN')
            by_status[status]['orders'] += 1
            for item in order.get('items') or []:
                sku = str(item.get('offerId') or 'UNKNOWN')
                qty = int(item.get('count') or 0)
                prices = _amount(item)
                rub = sum(prices.values(), Decimal(0))
                by_status[status]['units'] += qty
                by_status[status]['rub'] += rub
                totals['all_units'] += qty
                totals['all_rub'] += rub
                if status != 'CANCELLED':
                    totals['noncancelled_units'] += qty
                    totals['noncancelled_rub'] += rub
                if status == 'CANCELLED' or sku in TARGET_SKUS:
                    details.append({
                        'order_id': str(order['orderId']), 'status': status, 'program': program,
                        'sku': sku, 'units': qty,
                        'payment_rub': str(prices['payment']),
                        'cashback_rub': str(prices['cashback']),
                        'subsidy_rub': str(prices['subsidy']),
                        'total_rub': str(rub),
                    })
        report = {
            'date': args.day.isoformat(), 'business_id': business_id, 'pages': pages,
            'orders': sum(v['orders'] for v in by_status.values()),
            'totals': {k: str(v) for k, v in totals.items()},
            'by_status': {k: {p: str(v) for p, v in values.items()} for k, values in sorted(by_status.items())},
            'target_skus': sorted(TARGET_SKUS), 'cancelled_and_target_sku_lines': details,
            'note': 'Order-line prices are already extended totals; do not multiply by quantity. No buyer details stored.',
        }
        path = Path('yandex_sales_diagnostic') / f'status_audit_{args.day}.json'
        path.parent.mkdir(exist_ok=True, parents=True)
        path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
        print(f"Orders: {report['orders']} / pages: {pages}")
        for status, val in report['by_status'].items():
            print(f"{status}: {val['orders']} orders, {val['units']} units, {val['rub']} RUB")
        print('Non-cancelled:', totals['noncancelled_units'], 'units,', totals['noncancelled_rub'], 'RUB')
        print('Target & cancelled order lines:')
        for line in details:
            print('  {order_id} | {status} | {sku} | {units} pcs | {total_rub} RUB'.format(**line))
        print('Saved:', path)
    finally:
        try:
            clear_tenant_context(db)
            reset_app_db_role(db)
        finally:
            db.close()


if __name__ == '__main__':
    main()
