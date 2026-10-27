"""Idempotent Yandex Market order snapshots using the validated diagnostic API.
Persist order-line prices as API totals (do NOT multiply by quantity).
Cancellation filtering is deliberately NOT hardcoded pending business-rule validation.
"""
from datetime import date, datetime, timedelta
from decimal import Decimal
from threading import Lock
from zoneinfo import ZoneInfo
from sqlalchemy import text
from backend.database import Base, engine
from backend.logging_config import get_logger
from backend.models.yandex_sales_order import YandexSalesOrderLine, YandexSalesSyncDay
from backend.services.marketplace_clients import get_yandex_client, get_yandex_business_id
from backend.scripts.yandex_sales_probe import get_page, money, order_local_day

log = get_logger('yandex_sales_order_sync')
MOSCOW = ZoneInfo('Europe/Moscow')
_lock = Lock()


def verify_yandex_sales_schema():
    """Read-only startup guard. RLS/GRANT changes belong to an owner-run migration."""
    with engine.connect() as conn:
        for table in ('yandex_sales_order_lines', 'yandex_sales_sync_days'):
            row = conn.execute(text("""
                SELECT c.relrowsecurity, c.relforcerowsecurity,
                  EXISTS (SELECT 1 FROM pg_policies p WHERE p.schemaname = 'public'
                    AND p.tablename = :table AND p.policyname = 'tenant_isolation')
                FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace
                WHERE n.nspname = 'public' AND c.relname = :table AND c.relkind IN ('r', 'p')
            """), {'table': table}).first()
            if row is None or not all(row):
                raise RuntimeError(f'Yandex sales schema is not ready for {table}; apply sql/yandex_sales_rls_patch_29_1.sql as postgres')


def _read_complete_orders(client, business_id, day):
    payload = {'dates': {'creationDateFrom': day.isoformat(), 'creationDateTo': (day + timedelta(days=1)).isoformat()}, 'fake': False, 'sourcePlatforms': ['MARKET']}
    token = None
    tokens = set()
    orders = {}
    for _ in range(500):
        data = get_page(client, business_id, payload, token)
        if not isinstance(data, dict) or not isinstance(data.get('orders'), list):
            raise RuntimeError('Yandex returned incomplete/unrecognized orders payload')
        for order in data['orders']:
            orders[str(order['orderId'])] = order
        nxt = (data.get('paging') or {}).get('nextPageToken')
        if not nxt:
            return list(orders.values())
        if nxt == token or nxt in tokens:
            raise RuntimeError('Yandex returned repeated pagination token')
        tokens.add(nxt)
        token = nxt
    raise RuntimeError('Yandex pagination limit reached')


def sync_yandex_sales_day(db, organization_id: int, day: date):
    if not _lock.acquire(blocking=False):
        raise RuntimeError('Yandex sales import already running')
    try:
        client = get_yandex_client(db)
        business_id = get_yandex_business_id(db, client)
        orders = _read_complete_orders(client, business_id, day)
        new_lines = []
        units = 0
        valid_orders = 0
        for order in orders:
            if order_local_day(order) != day:
                continue
            valid_orders += 1
            created = datetime.fromisoformat(order['creationDate'].replace('Z', '+00:00')).astimezone(MOSCOW).replace(tzinfo=None)
            for index, item in enumerate(order.get('items') or []):
                qty = int(item.get('count') or 0)
                if qty <= 0:
                    raise ValueError(f'Invalid quantity for order {order["orderId"]}')
                prices = item.get('prices') or {}
                if not prices.get('payment'):
                    raise ValueError(f'Missing payment in order {order["orderId"]}')
                values = {}
                currencies = set()
                for field in ('payment', 'cashback', 'subsidy'):
                    amount, currency = money(prices, field)
                    values[field] = amount
                    if currency:
                        currencies.add(str(currency))
                if len(currencies) != 1 or next(iter(currencies)) not in ('RUR', 'RUB'):
                    raise ValueError(f'Unsupported currency {currencies} in order {order["orderId"]}')
                new_lines.append(YandexSalesOrderLine(
                    organization_id=organization_id, business_id=business_id,
                    order_id=str(order['orderId']), line_index=index, sale_date=day,
                    created_at=created, offer_id=str(item.get('offerId') or ''),
                    program_type=str(order.get('programType') or ''),
                    order_status=str(order.get('status') or ''),
                    order_substatus=str(order.get('substatus') or ''),
                    quantity=qty, payment=values['payment'], cashback=values['cashback'],
                    subsidy=values['subsidy'], currency_code=next(iter(currencies)),
                    last_synced_at=datetime.utcnow()))
                units += qty
        db.query(YandexSalesOrderLine).filter(YandexSalesOrderLine.organization_id == organization_id, YandexSalesOrderLine.sale_date == day).delete(synchronize_session=False)
        db.add_all(new_lines)
        checkpoint = db.query(YandexSalesSyncDay).filter_by(organization_id=organization_id, sale_date=day).one_or_none()
        if checkpoint is None:
            checkpoint = YandexSalesSyncDay(organization_id=organization_id, sale_date=day, orders_count=0, lines_count=0, units_count=0)
            db.add(checkpoint)
        checkpoint.orders_count = valid_orders
        checkpoint.lines_count = len(new_lines)
        checkpoint.units_count = units
        checkpoint.provisional = day >= datetime.now(MOSCOW).date()
        checkpoint.last_synced_at = datetime.utcnow()
        db.commit()
        log.info('YANDEX_SALES_ORDER_SYNC_OK day=%s orders=%s lines=%s units=%s provisional=%s',day,valid_orders,len(new_lines),units,checkpoint.provisional)
        return {'orders':valid_orders,'lines':len(new_lines),'units':units,'provisional':checkpoint.provisional}
    except Exception:
        db.rollback()
        raise
    finally:
        _lock.release()
