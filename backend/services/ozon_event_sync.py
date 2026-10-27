"""Seller Ozon API event collection, using explicit event timestamps only.

Coverage is separated by event type. Missing cancellation date MUST NOT be guessed.
"""
from datetime import datetime, date, timedelta, timezone
from collections import defaultdict
from sqlalchemy import func
from backend.database import Base, engine
from backend.models.ozon_event import OzonEvent, OzonEventCoverage
from backend.services.marketplace_clients import get_ozon_client
from backend.services.ozon_order_sync import list_postings, retry_ozon_request, MOSCOW
from backend.services.ozon_order_details import get_posting_details
from backend.logging_config import get_logger

log = get_logger('ozon_event_sync')


def ensure_event_tables():
    Base.metadata.create_all(bind=engine, tables=[OzonEvent.__table__, OzonEventCoverage.__table__])
    with engine.begin() as conn:
        for table in ('ozon_events', 'ozon_event_coverage'):
            conn.exec_driver_sql(f'GRANT SELECT, INSERT, UPDATE, DELETE ON TABLE {table} TO marketplace_app')
            conn.exec_driver_sql(f'GRANT USAGE, SELECT, UPDATE ON SEQUENCE {table}_id_seq TO marketplace_app')
            conn.exec_driver_sql(f'ALTER TABLE {table} ENABLE ROW LEVEL SECURITY')
            conn.exec_driver_sql(f'ALTER TABLE {table} FORCE ROW LEVEL SECURITY')
            conn.exec_driver_sql(f'DROP POLICY IF EXISTS tenant_isolation ON {table}')
            conn.exec_driver_sql(f'''CREATE POLICY tenant_isolation ON {table}
                USING (organization_id = current_setting('app.organization_id', true)::integer)
                WITH CHECK (organization_id = current_setting('app.organization_id', true)::integer)''')


def parse_date(value):
    if not value or not isinstance(value, str):
        return None
    try:
        dt = datetime.fromisoformat(value.replace('Z', '+00:00'))
        if dt.tzinfo is None:
            return None
        return dt.astimezone(MOSCOW).date()
    except ValueError:
        return None


def bounds(day):
    start = datetime.combine(day, datetime.min.time(), tzinfo=MOSCOW).astimezone(timezone.utc)
    finish = start + timedelta(days=1) - timedelta(milliseconds=1)
    return (start.isoformat(timespec='milliseconds').replace('+00:00','Z'),
            finish.isoformat(timespec='milliseconds').replace('+00:00','Z'))


def _mark(db, org, kind, day):
    row = db.query(OzonEventCoverage).filter_by(organization_id=org, event_type=kind, event_date=day).one_or_none()
    if row is None:
        db.add(OzonEventCoverage(organization_id=org,event_type=kind,event_date=day))
    else:
        row.refreshed_at = datetime.utcnow()


def _replace_daily(db, org, kind, day, events):
    db.query(OzonEvent).filter_by(organization_id=org,event_type=kind,event_date=day).delete(synchronize_session=False)
    for e in events:
        db.add(OzonEvent(organization_id=org, event_type=kind, event_date=day, **e))
    _mark(db, org, kind, day)


def sync_returns_day(db, org, day):
    """Logistic return events from /v1/returns/list; full pagination or rollback."""
    client = get_ozon_client(db)
    since, until = bounds(day)
    last_id = 0
    seen = set()
    events = {}
    for _ in range(100):
        payload = {'filter': {'logistic_return_date': {'time_from': since, 'time_to': until}},
                   'limit': 500, 'last_id': last_id}
        response = retry_ozon_request(lambda: client.post_raw('/v1/returns/list', payload),
                                      scheme='returns', operation='listing')
        body = response.get('body') or {}
        if not isinstance(body.get('returns'), list):
            raise RuntimeError('Returns response missing returns array; cannot mark day complete')
        for item in body['returns']:
            if not isinstance(item, dict) or item.get('id') is None:
                raise RuntimeError('Return missing ID')
            key = str(item['id'])
            logistic = item.get('logistic') or {}
            event_day = parse_date(logistic.get('return_date'))
            if event_day != day:
                # Filter time can be interpreted differently; never assign wrong day.
                continue
            product = item.get('product') or {}
            try:
                quantity = int(product.get('quantity', 1))
            except (TypeError, ValueError):
                raise RuntimeError(f'Invalid return quantity for id {key}')
            if quantity < 1:
                raise RuntimeError(f'Invalid return quantity for id {key}')
            events[key] = {'event_key':key, 'posting_number':str(item.get('posting_number') or ''),
                           'scheme':str(item.get('schema') or '').lower()[:3], 'quantity':quantity}
        if not body.get('has_next'):
            _replace_daily(db,org,'returned',day,list(events.values()))
            db.commit()
            return {'date':day.isoformat(),'returns':len(events),'units':sum(e['quantity'] for e in events.values())}
        if not body['returns']:
            raise RuntimeError('Return pagination has_next with no rows')
        next_id = int(body['returns'][-1]['id'])
        if next_id in seen or next_id == last_id:
            raise RuntimeError('Return pagination repeated last_id')
        seen.add(next_id)
        last_id = next_id
    raise RuntimeError('Return pagination exceeded 100 pages')


def sync_posting_events_window(db, org, from_day, to_day):
    """Scan posting creation window and record events by actual dates, not order dates.

    FBO/FBS listing is filtered by creation/processing time, therefore old orders
    can deliver in a later period. Rescan windows spanning enough order history.
    Missing cancellation dates remain unsupported, never inferred.
    """
    client = get_ozon_client(db)
    if to_day < from_day:
        raise ValueError('to_day must be >= from_day')
    events = {}
    unknown_cancellation_dates = 0
    scanned = 0
    # Listing a full 14-day range can exceed list_postings' 100-page guard.
    # Query each Moscow day separately and de-duplicate postings across windows.
    seen_postings = set()
    day = from_day
    while day <= to_day:
        since, until = bounds(day)
        for scheme in ('fbo', 'fbs'):
            postings = list_postings(client, scheme, since, until)
            for number in postings:
                if (scheme, number) in seen_postings:
                    continue
                seen_postings.add((scheme, number))
                resp = retry_ozon_request(lambda: get_posting_details(client,scheme,number),
                                          scheme=scheme, operation='details', posting_number=number)
                body = resp.get('body') or {}
                item = body.get('result') if isinstance(body.get('result'),dict) else body
                scanned += 1
                products = item.get('products') or []
                units = sum(int(p.get('quantity') or 1) for p in products)
                if units < 1:
                    raise RuntimeError(f'No products in posting {number}')
                status = item.get('status')
                delivery = parse_date(item.get('fact_delivery_date'))
                if status == 'delivered' and delivery:
                    events[('delivered',scheme,number)] = {
                        'event_type':'delivered','event_key':f'{scheme}:{number}',
                        'event_date':delivery,'posting_number':number,'scheme':scheme,'quantity':units}
                if status == 'cancelled':
                    cancel = item.get('cancellation') or {}
                    cancelled_date = parse_date(cancel.get('cancelled_at') or cancel.get('cancellation_date') or item.get('cancelled_at'))
                    if cancelled_date:
                        events[('cancelled',scheme,number)] = {
                            'event_type':'cancelled','event_key':f'{scheme}:{number}',
                            'event_date':cancelled_date,'posting_number':number,'scheme':scheme,'quantity':units}
                    else:
                        unknown_cancellation_dates += 1
        day += timedelta(days=1)
    # Only upsert known events; never delete other historical events because
    # these are identified by order window, not event-day window.
    for row in events.values():
        existing = db.query(OzonEvent).filter_by(organization_id=org,event_type=row['event_type'],event_key=row['event_key']).one_or_none()
        if existing:
            existing.event_date=row['event_date']
            existing.quantity=row['quantity']
            existing.last_seen_at=datetime.utcnow()
        else:
            db.add(OzonEvent(organization_id=org,**row))
    db.commit()
    log.info('OZON_EVENT_SCAN_OK since=%s until=%s scanned=%s known_events=%s undated_cancellations=%s',
             from_day,to_day,scanned,len(events),unknown_cancellation_dates)
    return {'scanned':scanned,'known_events':len(events),'undated_cancellations':unknown_cancellation_dates}


def event_totals(db, from_day, to_day):
    org_days = db.query(OzonEventCoverage).filter(OzonEventCoverage.event_type=='returned',
                       OzonEventCoverage.event_date>=from_day,OzonEventCoverage.event_date<=to_day).all()
    expected = (to_day - from_day).days + 1
    has_all_return_dates = len({r.event_date for r in org_days}) == expected
    today = datetime.now(MOSCOW).date()
    covers_returns = has_all_return_dates and to_day < today
    rows = db.query(OzonEvent.event_type,func.sum(OzonEvent.quantity)).filter(
        OzonEvent.event_date >= from_day,OzonEvent.event_date <= to_day).group_by(OzonEvent.event_type).all()
    amounts = dict(rows)
    # No verified event-date completeness for delivery/cancel from order-based listing.
    return {'delivered_units':int(amounts.get('delivered',0)),
            'returns':int(amounts.get('returned',0)) if has_all_return_dates else None,
            'cancellations':int(amounts.get('cancelled',0)),
            'coverage':{'returns_complete':covers_returns,'returns_days':len(org_days),
                        'returns_provisional':has_all_return_dates and from_day <= today <= to_day,
                        'delivered_complete':False,'cancellations_complete':False},
            'notes':{'delivered_units':'Подтверждённые доставки с датой фактической доставки; возможен недосбор старых заказов.',
                     'returns':'Возвраты по logistic.return_date; число единиц, если выгрузка всех дней завершена.',
                     'cancellations':'Только отмены с явной датой события; Ozon часто не возвращает такую дату.'}}
