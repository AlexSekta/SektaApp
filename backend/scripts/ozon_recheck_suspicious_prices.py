"""Recheck suspicious Ozon posting customer prices, preserving raw values; read only.
Run from repository root: python -m backend.scripts.ozon_recheck_suspicious_prices
"""
import argparse
import json
import time
from collections import Counter
from datetime import datetime
from decimal import Decimal, InvalidOperation
from pathlib import Path
from zoneinfo import ZoneInfo

from backend.database import SessionLocal
from backend.models.auth import Organization  # register relationship model before credentials query
from backend.services.marketplace_clients import get_ozon_client
from backend.services.ozon_order_details import DETAIL_PATHS

MOSCOW = ZoneInfo('Europe/Moscow')


def dec(value):
    if isinstance(value, dict):
        value = value.get('amount')
    if value is None or value == '':
        return None
    try:
        return Decimal(str(value))
    except (InvalidOperation, ValueError, TypeError):
        return None


def dt_moscow(value):
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace('Z', '+00:00')).astimezone(MOSCOW).date().isoformat()
    except (ValueError, TypeError, AttributeError):
        return None


def suspect(entry):
    findings = []
    for index, item in enumerate(entry.get('products') or []):
        price, customer = dec(item.get('price')), dec(item.get('customer_price'))
        if price is None or customer is None or price <= 0:
            continue
        reason = 'above_seller_price' if customer > price else 'below_ten_percent' if customer / price < Decimal('.1') else None
        if reason:
            findings.append({'index': index, 'sku': item.get('sku'), 'offer_id': item.get('offer_id'), 'reason': reason, 'old_customer_price': str(customer), 'seller_price': str(price)})
    return findings


def new_lines(posting, old_entry):
    financial = ((posting.get('financial_data') or {}).get('products') or [])
    product_lines = posting.get('products') or []
    result = []
    for i, fp in enumerate(financial):
        if not isinstance(fp, dict):
            continue
        matched = next((p for p in product_lines if isinstance(p, dict) and fp.get('sku') is not None and str(p.get('sku')) == str(fp.get('sku'))), None)
        if matched is None and i < len(product_lines) and isinstance(product_lines[i], dict):
            matched = product_lines[i]
        matched = matched or {}
        v = fp.get('customer_price')
        amount = v.get('amount') if isinstance(v, dict) else v
        result.append({'sku': fp.get('sku') or matched.get('sku'),
                       'offer_id': fp.get('offer_id') or matched.get('offer_id'),
                       'raw_customer_price': v if isinstance(v, (int, float, str, dict, type(None))) else 'unsupported_type',
                       'raw_type': type(v).__name__,
                       'parsed_customer_price': str(dec(v)) if dec(v) is not None else None,
                       'price': str(dec(fp.get('price'))) if dec(fp.get('price')) is not None else None,
                       'quantity': str(dec(fp.get('quantity') or matched.get('quantity'))) if dec(fp.get('quantity') or matched.get('quantity')) is not None else None})
    return result


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--checkpoint', default='ozon_price_diagnostic/checkpoint_2026-10-12.json')
    parser.add_argument('--day', default='2026-10-12')
    parser.add_argument('--delay', type=float, default=0.5)
    args = parser.parse_args()
    cp = Path(args.checkpoint)
    if not cp.exists():
        raise SystemExit(f'Checkpoint not found: {cp.resolve()}')
    old = json.loads(cp.read_text(encoding='utf-8'))
    selected = [(key, data, suspect(data)) for key, data in old.items() if isinstance(data, dict)]
    selected = [(key, data, flagged) for key, data, flagged in selected if flagged]
    print(f'Checkpoint: {len(old)} entries; suspicious: {len(selected)} postings / {sum(len(s[2]) for s in selected)} lines', flush=True)
    output = []
    db = SessionLocal()
    try:
        client = get_ozon_client(db)
        for idx, (key, old_entry, flags) in enumerate(selected, 1):
            scheme = old_entry.get('scheme')
            posting_number = old_entry.get('posting_number')
            if scheme not in DETAIL_PATHS or not posting_number:
                output.append({'key': key, 'error': 'invalid source key'})
                continue
            raw = client.post_raw(DETAIL_PATHS[scheme], {'posting_number': posting_number, 'with': {'analytics_data': False, 'financial_data': True}})
            item = {'key': key, 'scheme': scheme, 'posting_number': posting_number, 'http_status': raw.get('status_code'), 'suspects': flags}
            if raw.get('status_code') == 200 and isinstance(raw.get('body'), dict):
                body = raw['body']; posting = body.get('result') if isinstance(body.get('result'), dict) else body
                item['status_name'] = posting.get('status')
                date_value = posting.get('created_at') if scheme == 'fbo' else posting.get('in_process_at')
                item['moscow_proxy_date'] = dt_moscow(date_value)
                item['fresh_lines'] = new_lines(posting, old_entry)
                # Do not store raw posting/order objects or any buyer details.
            else:
                item['error'] = 'API error; full response deliberately omitted'
            output.append(item)
            print(f'{idx}/{len(selected)} {scheme}: HTTP {item["http_status"]}', flush=True)
            time.sleep(max(args.delay, .2))
    finally:
        db.close()
    out_dir = Path('ozon_price_diagnostic'); out_dir.mkdir(exist_ok=True)
    out = out_dir / f'price_recheck_{args.day}.json'
    report = {'day': args.day, 'source_count': len(old), 'suspicious_postings': len(selected), 'suspicious_lines': sum(len(s[2]) for s in selected), 'result_count': len(output), 'all_http_200': all(row.get('http_status') == 200 for row in output), 'results': output,
              'note': 'Raw price fields from fresh posting-detail API calls only, no buyer data. Do not infer the soldRevenue formula from this probe.'}
    tmp = out.with_suffix('.tmp'); tmp.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8'); tmp.replace(out)
    print(f'Saved: {out.resolve()}', flush=True)

if __name__ == '__main__':
    main()
