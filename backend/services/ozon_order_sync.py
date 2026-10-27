"""Idempotent Ozon FBO/FBS order import, no buyer personal data persisted.

Customer price uses buyer currency. CBR FX is an ESTIMATE, not Ozon soldRevenue.
"""
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation
from functools import lru_cache
from threading import Lock
import time

from backend.database import Base, engine
from backend.models.ozon_order import OzonOrderLine, OzonOrderSyncDay
from backend.services.marketplace_clients import get_ozon_client
from backend.services.ozon_order_details import get_posting_details
from backend.logging_config import get_logger

log = get_logger('ozon_order_sync')
MOSCOW = timezone(timedelta(hours=3))
_LOCK = Lock()


def ensure_ozon_order_tables():
    Base.metadata.create_all(bind=engine, tables=[OzonOrderLine.__table__, OzonOrderSyncDay.__table__])
    with engine.begin() as conn:
        for table in ('ozon_order_lines', 'ozon_order_sync_days'):
            conn.exec_driver_sql(f'GRANT SELECT, INSERT, UPDATE, DELETE ON TABLE {table} TO marketplace_app')
            conn.exec_driver_sql(f'GRANT USAGE, SELECT, UPDATE ON SEQUENCE {table}_id_seq TO marketplace_app')
            conn.exec_driver_sql(f'ALTER TABLE {table} ENABLE ROW LEVEL SECURITY')
            conn.exec_driver_sql(f'ALTER TABLE {table} FORCE ROW LEVEL SECURITY')
            conn.exec_driver_sql(f'DROP POLICY IF EXISTS tenant_isolation ON {table}')
            conn.exec_driver_sql(f'''CREATE POLICY tenant_isolation ON {table}
                USING (organization_id = current_setting('app.organization_id', true)::integer)
                WITH CHECK (organization_id = current_setting('app.organization_id', true)::integer)''')


def dec(value):
    try:
        return Decimal(str(value))
    except (TypeError, ValueError, InvalidOperation):
        raise ValueError('Missing or invalid financial price/quantity')


def moscow_day(value):
    if not value:
        raise ValueError('Order timestamp missing')
    return datetime.fromisoformat(str(value).replace('Z', '+00:00')).astimezone(MOSCOW).date()


@lru_cache(maxsize=120)
def fx_for_day(day):
    # Reuse the already-tested Ozon diagnostic CBR parser with verified TLS.
    # The CSV rates Ozon uses may differ; this is deliberately an estimate.
    from backend.scripts.ozon_currency_audit import rub_rates
    rates, _url, _published = rub_rates(day.isoformat())
    return rates


def retry_ozon_request(call, *, scheme, operation, posting_number=None):
    """Retry only transient API/network failures; never treat missing data as success."""
    wait_seconds = (2, 4, 8, 15, 25, 40)
    transient_codes = {429, 500, 502, 503, 504}
    for attempt in range(len(wait_seconds) + 1):
        reply = call()
        status = reply.get('status_code') if isinstance(reply, dict) else None
        if status == 200:
            return reply
        if status not in transient_codes or attempt == len(wait_seconds):
            raise RuntimeError(
                f'{scheme} {operation} failed (HTTP {status}), '
                f'posting={posting_number or "-"}, attempts={attempt + 1}'
            )
        delay = wait_seconds[attempt]
        log.warning('OZON_ORDER_API_RETRY scheme=%s operation=%s posting=%s http=%s attempt=%s wait_seconds=%s',
                    scheme, operation, posting_number or '-', status, attempt + 1, delay)
        time.sleep(delay)

def list_postings(client, scheme, since, until):
    cursor = ''
    seen = set()
    result = {}
    for _ in range(100):
        fn = client.list_fbo_postings_raw if scheme == 'fbo' else client.list_fbs_postings_raw
        response = retry_ozon_request(
            lambda: fn(since=since, to=until, cursor=cursor, limit=100),
            scheme=scheme, operation='listing'
        )
        body = response.get('body') or {}
        for item in body.get('postings') or []:
            posting_no = item.get('posting_number')
            if posting_no:
                result[str(posting_no)] = item
        if not body.get('has_next'):
            return result
        next_cursor = body.get('cursor')
        if not next_cursor or next_cursor in seen:
            raise RuntimeError('Ozon pagination returned missing/repeated cursor')
        seen.add(next_cursor)
        cursor = next_cursor
    raise RuntimeError('Ozon pagination safety limit reached')


def extract_lines(posting, scheme, day, fx):
    fin = ((posting.get('financial_data') or {}).get('products') or [])
    product_list = posting.get('products') or []
    product_by_sku = {str(p.get('sku')): p for p in product_list if p.get('sku') is not None}
    rows = []
    for i, f in enumerate(fin):
        product = product_by_sku.get(str(f.get('product_id'))) or {}
        if not product and len(product_list) == 1:
            product = product_list[0]
        # Never guess correspondence by list order in multi-product postings.
        if not product:
            raise ValueError(f'Financial SKU mapping missing, index {i}')
        sku = str(product.get('sku') or '')
        if not sku:
            raise ValueError('SKU missing')
        quantity_dec = dec(f.get('quantity') or product.get('quantity') or 1)
        if quantity_dec != int(quantity_dec) or quantity_dec < 1:
            raise ValueError('Invalid quantity')
        quantity = int(quantity_dec)
        currency = str(f.get('customer_currency_code') or '').upper()
        if not currency or currency not in fx:
            raise ValueError(f'Unknown currency: {currency}')
        customer = dec(f.get('customer_price'))
        seller = dec(f['price']) if f.get('price') is not None else None
        rows.append({
            'scheme': scheme, 'posting_number': str(posting['posting_number']),
            'line_index': i, 'sale_date': day, 'sku': sku,
            'offer_id': str(product.get('offer_id') or ''),
            'order_number': str(posting.get('order_number') or ''),
            'status': str(posting.get('status') or ''), 'quantity': quantity,
            'customer_currency': currency, 'customer_unit_price': customer,
            'seller_unit_price_rub': seller, 'fx_rate_rub': fx[currency],
            'estimated_rub': customer * quantity * fx[currency],
        })
    if not rows:
        raise ValueError('No financial products')
    return rows


def sync_day(db, organization_id, day):
    """Entire day committed atomically: an incomplete API response never replaces a good day."""
    if not _LOCK.acquire(blocking=False):
        raise RuntimeError('Ozon order sync is already running')
    try:
        start = datetime.combine(day, datetime.min.time(), tzinfo=MOSCOW).astimezone(timezone.utc)
        finish = start + timedelta(days=1) - timedelta(milliseconds=1)
        since = start.isoformat(timespec='milliseconds').replace('+00:00','Z')
        until = finish.isoformat(timespec='milliseconds').replace('+00:00','Z')
        client = get_ozon_client(db)
        fx = fx_for_day(day)
        all_rows = []
        count = 0
        skipped_outside_day = {'fbo': 0, 'fbs': 0}
        for scheme in ('fbo','fbs'):
            postings = list_postings(client, scheme, since, until)
            for number in postings:
                reply = retry_ozon_request(
                    lambda: get_posting_details(client, scheme, number),
                    scheme=scheme, operation='details', posting_number=number
                )
                body = reply.get('body') or {}
                posting = body.get('result') if isinstance(body.get('result'), dict) else body
                stamp = posting.get('created_at') if scheme == 'fbo' else posting.get('in_process_at')
                if moscow_day(stamp) != day:
                    # Ozon's posting list may include records around the day boundary.
                    # Do not attribute them to the wrong day or abort the entire import.
                    skipped_outside_day[scheme] += 1
                    log.warning('OZON_ORDER_OUTSIDE_DAY requested=%s scheme=%s posting=%s timestamp=%s',
                                day, scheme, number, stamp)
                    continue
                all_rows.extend(extract_lines(posting, scheme, day, fx))
                count += 1
        # Replace snapshot for this day only after every request succeeded.
        db.query(OzonOrderLine).filter(OzonOrderLine.organization_id == organization_id,
                                       OzonOrderLine.sale_date == day).delete(synchronize_session=False)
        for data in all_rows:
            db.add(OzonOrderLine(organization_id=organization_id, **data))
        marker = db.query(OzonOrderSyncDay).filter(OzonOrderSyncDay.organization_id == organization_id,
                                                   OzonOrderSyncDay.sale_date == day).one_or_none()
        if marker is None:
            marker = OzonOrderSyncDay(organization_id=organization_id, sale_date=day,
                                     posting_count=count, line_count=len(all_rows))
            db.add(marker)
        else:
            marker.posting_count = count
            marker.line_count = len(all_rows)
            marker.last_synced_at = datetime.utcnow()
        db.commit()
        log.info('OZON_ORDER_SYNC_OK day=%s postings=%s lines=%s skipped_outside_day=%s',
                 day, count, len(all_rows), skipped_outside_day)
        return {'day': day.isoformat(), 'postings': count, 'lines': len(all_rows),
                'skipped_outside_day': skipped_outside_day, 'status':'ok'}
    except Exception:
        db.rollback()
        raise
    finally:
        _LOCK.release()


def daily_totals(db, date_from, date_to):
    lines = db.query(OzonOrderLine).filter(OzonOrderLine.sale_date >= date_from,
                                          OzonOrderLine.sale_date <= date_to).all()
    marks = db.query(OzonOrderSyncDay).filter(OzonOrderSyncDay.sale_date >= date_from,
                                               OzonOrderSyncDay.sale_date <= date_to).all()
    by_day = {}
    for line in lines:
        key = line.sale_date.isoformat()
        item = by_day.setdefault(key, {'date':key, 'estimated_rub':Decimal(0), 'units':0,
                                       'fbo_postings':set(), 'fbs_postings':set(), 'foreign_units':0})
        item['estimated_rub'] += line.estimated_rub
        item['units'] += line.quantity
        item[f'{line.scheme}_postings'].add(line.posting_number)
        if line.customer_currency != 'RUB':
            item['foreign_units'] += line.quantity
    data = []
    for mark in sorted(marks, key=lambda r:r.sale_date):
        key = mark.sale_date.isoformat()
        row = by_day.get(key, {'date':key, 'estimated_rub':Decimal(0),'units':0,
                               'fbo_postings':set(),'fbs_postings':set(),'foreign_units':0})
        data.append({'date':key,'estimated_rub':round(float(row['estimated_rub']),2),
                     'units':row['units'],'fbo_postings':len(row['fbo_postings']),
                     'fbs_postings':len(row['fbs_postings']),'foreign_units':row['foreign_units'],
                     'last_synced_at':mark.last_synced_at.isoformat()})
    expected = (date_to - date_from).days + 1
    return {'status':'ok','source':'ozon_postings_cbr_estimate','rows':data,'complete_period':len(data) == expected and date_to < datetime.now(MOSCOW).date(),
            'current_day_provisional':date_from <= datetime.now(MOSCOW).date() <= date_to,
            'totals':{'estimated_rub':round(sum(r['estimated_rub'] for r in data),2),
                      'units':sum(r['units'] for r in data),'days':len(data)},
            'note':'Расчётная цена покупателя: RUB + BYN/KZT/UZS по курсу ЦБ; включает отмены. Не soldRevenue Ozon.'}
