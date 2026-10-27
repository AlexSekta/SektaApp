"""Read-only audit of Yandex Market business orders for one Moscow calendar day.
Run: python -m backend.scripts.yandex_sales_probe --day 2026-10-14
"""
import argparse
import json
import time
from collections import Counter, defaultdict
from datetime import date, timedelta, datetime
from decimal import Decimal, InvalidOperation
from pathlib import Path
from zoneinfo import ZoneInfo

from backend.database import SessionLocal
from backend.models.auth import Organization  # noqa: F401 — mapper initialization
from backend.auth.tenant import (legacy_sync_organization_id, set_app_db_role,
    set_tenant_context, clear_tenant_context, reset_app_db_role)
from backend.services.marketplace_clients import get_yandex_client, get_yandex_business_id
from backend.marketplaces.yandex.client import YandexAPIError

MOSCOW = ZoneInfo('Europe/Moscow')


def money(prices, field):
    v = (prices or {}).get(field)
    if v is None:
        return Decimal('0'), None
    if not isinstance(v, dict):
        raise ValueError(f'Unexpected price structure at {field}: {type(v).__name__}')
    currency = v.get('currencyId')
    try:
        amount = Decimal(str(v.get('value', 0)))
    except (ValueError, InvalidOperation) as e:
        raise ValueError(f'Invalid amount in {field}') from e
    return amount, currency


def order_local_day(order):
    stamp = order.get('creationDate')
    if not stamp:
        raise ValueError(f"Order {order.get('orderId')} lacks creationDate")
    parsed = datetime.fromisoformat(str(stamp).replace('Z', '+00:00'))
    if parsed.tzinfo is None:
        raise ValueError(f"Order {order.get('orderId')} has timezone-less creationDate")
    return parsed.astimezone(MOSCOW).date()


def get_page(client, business_id, payload, token):
    params = {'limit': 50}
    if token:
        params['pageToken'] = token
    for attempt in range(5):
        try:
            return client.post(f'/v1/businesses/{business_id}/orders', payload=payload, params=params)
        except YandexAPIError as exc:
            if exc.status_code not in (420, 429, 500, 502, 503, 504) or attempt == 4:
                raise
            delay = min(2 ** attempt * 2, 20)
            print(f'API retry HTTP {exc.status_code}, waiting {delay}s...', flush=True)
            time.sleep(delay)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--day', type=date.fromisoformat, default=date(2026, 10, 14))
    ap.add_argument('--reference-rub', type=Decimal, default=Decimal('131864'))
    ap.add_argument('--reference-units', type=int, default=58)
    args = ap.parse_args()
    db = SessionLocal()
    try:
        org = legacy_sync_organization_id()
        if org is None:
            raise RuntimeError('No organization found')
        set_app_db_role(db)
        set_tenant_context(db, org)
        client = get_yandex_client(db)
        business_id = get_yandex_business_id(db, client)
        print(f'Business ID: {business_id}; day: {args.day}; reference: {args.reference_units} units / {args.reference_rub} RUB', flush=True)
        payload = {
            'dates': {'creationDateFrom': args.day.isoformat(),
                      'creationDateTo': (args.day + timedelta(days=1)).isoformat()},
            'fake': False,
            'sourcePlatforms': ['MARKET'],
        }
        pages = 0
        next_token = None
        tokens = set()
        orders = {}
        while True:
            data = get_page(client, business_id, payload, next_token)
            if not isinstance(data, dict) or not isinstance(data.get('orders'), list):
                raise RuntimeError(f"Unexpected API payload keys: {list(data) if isinstance(data, dict) else type(data).__name__}")
            pages += 1
            for item in data['orders']:
                key = str(item['orderId'])
                orders[key] = item
            new_token = ((data.get('paging') or {}).get('nextPageToken'))
            if not new_token:
                break
            if new_token in tokens or pages >= 500:
                raise RuntimeError('Pagination stuck or limit reached; refusing incomplete totals')
            tokens.add(new_token)
            next_token = new_token
        totals = Counter()
        statuses = Counter()
        programs = Counter()
        currencies = Counter()
        sku = defaultdict(lambda: {'units': 0, 'payment': Decimal(0), 'cashback': Decimal(0), 'subsidy': Decimal(0)})
        out_of_day = []
        missing_items = 0
        missing_prices = 0
        for order in orders.values():
            if order_local_day(order) != args.day:
                out_of_day.append(str(order['orderId']))
                continue
            statuses[str(order.get('status'))] += 1
            programs[str(order.get('programType'))] += 1
            rows = order.get('items') or []
            if not rows:
                missing_items += 1
            for item in rows:
                qty = int(item.get('count') or 0)
                totals['units'] += qty
                sku_id = str(item.get('offerId') or 'UNKNOWN')
                sku[sku_id]['units'] += qty
                prices = item.get('prices') or {}
                if not prices or not prices.get('payment'):
                    missing_prices += 1
                for field in ('payment', 'cashback', 'subsidy'):
                    amount, currency = money(prices, field)
                    totals[field] += amount
                    sku[sku_id][field] += amount
                    if currency:
                        currencies[currency] += 1
        valid_orders = len(orders) - len(out_of_day)
        result = {
            'date': args.day.isoformat(), 'timezone': 'Europe/Moscow',
            'business_id': business_id, 'api_pages': pages, 'orders': valid_orders,
            'lines': sum(1 for o in orders.values() if order_local_day(o) == args.day for _ in (o.get('items') or [])),
            'units': totals['units'], 'reference_units': args.reference_units,
            'unit_difference': totals['units'] - args.reference_units,
            'status_order_counts': dict(statuses), 'program_order_counts': dict(programs),
            'currency_value_fields': dict(currencies),
            'payment_rub': str(totals['payment']), 'cashback_rub': str(totals['cashback']),
            'subsidy_rub': str(totals['subsidy']),
            'payment_plus_cashback_rub': str(totals['payment'] + totals['cashback']),
            'payment_plus_cashback_plus_subsidy_rub': str(totals['payment'] + totals['cashback'] + totals['subsidy']),
            'reference_rub': str(args.reference_rub),
            'difference_payment_cashback_rub': str(totals['payment'] + totals['cashback'] - args.reference_rub),
            'difference_including_subsidy_rub': str(totals['payment'] + totals['cashback'] + totals['subsidy'] - args.reference_rub),
            'missing_item_orders': missing_items, 'missing_item_prices': missing_prices,
            'outside_requested_day_count': len(out_of_day),
            'by_sku': [{'offer_id': key, 'units': value['units'], **{k: str(value[k]) for k in ('payment', 'cashback', 'subsidy')}} for key,value in sorted(sku.items())],
            'notes': ['No buyer data or API credentials are saved', 'This is a read-only diagnostic; item price fields are order-line totals and must not be multiplied by count', 'Cancelled orders are included for initial comparison; status grouping is provided for investigation'],
        }
        output = Path('yandex_sales_diagnostic') / f'orders_{args.day}.json'
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding='utf-8')
        print('\n' + '=' * 55)
        for key in ('api_pages','orders','lines','units','reference_units','unit_difference','payment_rub','cashback_rub','subsidy_rub','payment_plus_cashback_rub','payment_plus_cashback_plus_subsidy_rub','reference_rub','difference_payment_cashback_rub','difference_including_subsidy_rub','missing_item_prices','outside_requested_day_count'):
            print(f'{key}: {result[key]}')
        print('Statuses:', result['status_order_counts'])
        print('Models:', result['program_order_counts'])
        print('Currency codes:', result['currency_value_fields'])
        print('Saved summary:', output)
    finally:
        try:
            clear_tenant_context(db)
            reset_app_db_role(db)
        finally:
            db.close()


if __name__ == '__main__':
    main()
