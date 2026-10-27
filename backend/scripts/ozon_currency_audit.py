"""Read-only Ozon customer_price currency audit for checkpoint postings.
Run: python -m backend.scripts.ozon_currency_audit
Does not update DB. CBR rates are diagnostic and may not equal Ozon's conversion rates.
"""
import argparse
import json
import ssl
import time
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from collections import Counter, defaultdict
from datetime import date, datetime, timezone
from decimal import Decimal, InvalidOperation
from pathlib import Path
from zoneinfo import ZoneInfo

from backend.database import SessionLocal
from backend.models.auth import Organization  # noqa: F401 - register mapper
from backend.services.marketplace_clients import get_ozon_client
from backend.services.ozon_order_details import DETAIL_PATHS

MOSCOW = ZoneInfo('Europe/Moscow')


def d(value):
    if isinstance(value, dict):
        value = value.get('amount')
    try:
        return Decimal(str(value)) if value not in (None, '') else None
    except (ValueError, InvalidOperation, TypeError):
        return None


def code(value):
    if isinstance(value, dict):
        value = value.get('code') or value.get('currencyCode')
    return (str(value).upper().strip() if value is not None else 'UNKNOWN') or 'UNKNOWN'


def moscow_day(value):
    try:
        return datetime.fromisoformat(str(value).replace('Z', '+00:00')).astimezone(MOSCOW).date().isoformat()
    except Exception:
        return None


def rub_rates(day):
    """Fetch nominal-adjusted RUB rate per one foreign unit from official CBR archive."""
    dt = date.fromisoformat(day)
    qs = urllib.parse.urlencode({'date_req': dt.strftime('%d/%m/%Y')})
    url = 'https://www.cbr.ru/scripts/XML_daily.asp?' + qs
    req = urllib.request.Request(url, headers={'User-Agent': 'OzonCurrencyAudit/1.0'})
    # Prefer certifi's maintained CA bundle; never disable TLS verification.
    try:
        import certifi
    except ImportError as exc:
        raise RuntimeError('Missing certifi: python -m pip install certifi') from exc
    context = ssl.create_default_context(cafile=certifi.where())
    with urllib.request.urlopen(req, timeout=25, context=context) as response:
        xml = response.read(300000)
    root = ET.fromstring(xml)
    published = root.attrib.get('Date')
    if not published:
        raise ValueError('CBR response has no rate effective date')
    effective_date = datetime.strptime(published, '%d.%m.%Y').date()
    if effective_date > dt:
        raise ValueError(f'CBR returned future effective date: {published} for {day}')
    if (dt - effective_date).days > 10:
        raise ValueError(f'CBR effective date unexpectedly old: {published} for {day}')
    result = {'RUB': Decimal('1')}
    for node in root.findall('Valute'):
        ticker = node.findtext('CharCode')
        nominal = d(node.findtext('Nominal'))
        value = d((node.findtext('Value') or '').replace(',', '.'))
        if ticker and nominal and value is not None:
            result[ticker.upper()] = value / nominal
    return result, url, effective_date.isoformat()


def extract(entry, body):
    post = body.get('result') if isinstance(body.get('result'), dict) else body
    fin = ((post.get('financial_data') or {}).get('products') or [])
    products = post.get('products') or []
    lines = []
    for idx, fp in enumerate(fin):
        if not isinstance(fp, dict):
            continue
        sku = fp.get('sku')
        match = next((p for p in products if isinstance(p, dict) and sku is not None and str(p.get('sku')) == str(sku)), None)
        if match is None and idx < len(products) and isinstance(products[idx], dict):
            match = products[idx]
        match = match or {}
        qty = d(fp.get('quantity'))
        if qty is None:
            qty = d(match.get('quantity'))
        lines.append({
            'sku': sku or match.get('sku'), 'offer_id': fp.get('offer_id') or match.get('offer_id'),
            'quantity': str(qty) if qty is not None else None,
            'seller_price': str(d(fp.get('price'))) if d(fp.get('price')) is not None else None,
            'seller_currency': code(fp.get('currency_code')),
            'customer_price': str(d(fp.get('customer_price'))) if d(fp.get('customer_price')) is not None else None,
            'customer_currency': code(fp.get('customer_currency_code')),
        })
    return lines


def summarize(cache, day, rates):
    totals = defaultdict(Decimal); counts = Counter(); uncoded = 0
    issues = []
    for key, item in cache.items():
        if item.get('http_status') != 200:
            issues.append({'scheme': item.get('scheme'), 'reason': f'HTTP {item.get("http_status")}'})
            continue
        scheme = item.get('scheme')
        # FBS in_process_at is a proxy, not a confirmed order-created date.
        dt = moscow_day(item.get('created_at') if scheme == 'fbo' else item.get('in_process_at'))
        if dt != day:
            continue
        status = 'cancelled' if item.get('status_name') in ('cancelled', 'canceled') else 'not_cancelled'
        for line in item.get('lines', []):
            qty = d(line.get('quantity'))
            value = d(line.get('customer_price'))
            curr = code(line.get('customer_currency'))
            counts[f'{scheme}|{status}|{curr}'] += 1
            if qty is None or qty <= 0 or value is None:
                issues.append({'scheme': scheme, 'reason': 'missing quantity or customer price', 'currency': curr})
                continue
            totals[(scheme,status,curr)] += qty * value
    native = [{'scheme': s, 'status': st, 'currency': cur, 'amount': str(amt), 'lines': counts[f'{s}|{st}|{cur}'], 'cbr_rate_rub_per_unit': str(rates[cur]) if cur in rates else None, 'cbr_rub_estimate': str((amt * rates[cur]).quantize(Decimal('.01'))) if cur in rates else None} for (s,st,cur),amt in sorted(totals.items())]
    missing_fx = sorted({x['currency'] for x in native if x['cbr_rate_rub_per_unit'] is None})
    all_converted = not issues and not missing_fx
    estimate = sum((Decimal(x['cbr_rub_estimate']) for x in native if x['status'] == 'not_cancelled' and x['cbr_rub_estimate'] is not None), Decimal('0'))
    return {'native_currency_totals': native, 'missing_fx_currencies': missing_fx, 'issue_count': len(issues), 'issue_examples': issues[:10], 'can_compare_estimate': all_converted, 'cbr_estimate_not_cancelled_rub': str(estimate) if all_converted else None, 'reference_soldRevenue_rub': '1512469.00' if day == '2026-10-12' else None, 'difference_from_reference_rub': str(estimate - Decimal('1512469')) if all_converted and day == '2026-10-12' else None}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--day', default='2026-10-12')
    ap.add_argument('--checkpoint', default='ozon_price_diagnostic/checkpoint_2026-10-12.json')
    ap.add_argument('--delay', type=float, default=.45)
    args = ap.parse_args()
    src = Path(args.checkpoint)
    if not src.exists():
        raise SystemExit(f'Checkpoint missing: {src.resolve()}')
    old = json.loads(src.read_text(encoding='utf-8'))
    out_dir = Path('ozon_price_diagnostic')
    out_dir.mkdir(exist_ok=True)
    partial = out_dir / f'currency_checkpoint_{args.day}.json'
    cache = json.loads(partial.read_text(encoding='utf-8')) if partial.exists() else {}
    print(f'Source: {len(old)} postings; cached currency details: {len(cache)}', flush=True)
    pending = [(key, item) for key, item in old.items() if key not in cache or cache[key].get('http_status') != 200]
    print(f'API requests still needed: {len(pending)}', flush=True)
    db = SessionLocal() if pending else None
    try:
        client = get_ozon_client(db) if pending else None
        for i,(key, item) in enumerate(old.items(), 1):
            if key in cache and cache[key].get('http_status') == 200:
                continue
            scheme = item.get('scheme'); number = item.get('posting_number')
            if scheme not in DETAIL_PATHS or not number:
                cache[key] = {'scheme': scheme, 'http_status': 'invalid_source'}
                continue
            raw = client.post_raw(DETAIL_PATHS[scheme], {'posting_number': number, 'with': {'analytics_data': False, 'financial_data': True}})
            response = {'scheme': scheme, 'http_status': raw.get('status_code'), 'status_name': item.get('status_name'), 'created_at': item.get('created_at'), 'in_process_at': item.get('in_process_at')}
            if raw.get('status_code') == 200 and isinstance(raw.get('body'), dict):
                response['lines'] = extract(item, raw['body'])
            cache[key] = response
            if i % 20 == 0 or i == len(old):
                tmp = partial.with_suffix('.tmp')
                tmp.write_text(json.dumps(cache, ensure_ascii=False, indent=2), encoding='utf-8'); tmp.replace(partial)
                print(f'Processed {i}/{len(old)}; cached {len(cache)}', flush=True)
            time.sleep(max(.2, args.delay))
    finally:
        if db is not None:
            db.close()
    partial.write_text(json.dumps(cache, ensure_ascii=False, indent=2), encoding='utf-8')
    try:
        rates, url, effective_date = rub_rates(args.day)
        fx_error = None
    except Exception as exc:
        rates, url, effective_date, fx_error = {}, 'https://www.cbr.ru/scripts/XML_daily.asp', None, f'{type(exc).__name__}: {str(exc)[:150]}'
    summary = summarize(cache, args.day, rates)
    summary.update({'day': args.day, 'timezone': 'Europe/Moscow', 'posts_expected': len(old), 'postings_cached': len(cache), 'http_200': sum(v.get('http_status') == 200 for v in cache.values()), 'fx_reference': url, 'fx_rate_effective_date': effective_date, 'fx_error': fx_error, 'fx_is_exact_ozon_rate': False, 'date_caveat': 'FBS in_process_at is a proxy, not confirmed order creation date; CBR rates may differ from Ozon and are only diagnostic.'})
    target = out_dir / f'currency_summary_{args.day}.json'
    target.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding='utf-8')
    print('Saved summary:', target.resolve(), flush=True)
    print('Currency groups:', [(v['scheme'],v['currency'],v['amount']) for v in summary['native_currency_totals']], flush=True)
    print('Estimated RUB:', summary['cbr_estimate_not_cancelled_rub'], 'reference 1512469', flush=True)

if __name__ == '__main__':
    main()
