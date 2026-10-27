"""WB sales funnel daily snapshots. 'Ordered' is not paid/realized revenue."""
from datetime import date, datetime, timedelta
from decimal import Decimal, InvalidOperation
import requests
from fastapi import APIRouter, Depends, HTTPException, Query, Request
from sqlalchemy.orm import Session
from backend.dependencies import get_db
from backend.models.wb_sales_daily import WBSalesDaily
from backend.services.marketplace_clients import get_wb_client
from backend.services.marketplace_credentials import MarketplaceNotConfiguredError

router = APIRouter(prefix='/analytics', tags=['Аналитика'])
URL = 'https://seller-analytics-api.wildberries.ru/api/analytics/v3/sales-funnel/products'


def fetch_one_day(db, day):
    try:
        wb = get_wb_client(db)
    except (MarketplaceNotConfiguredError, RuntimeError):
        raise HTTPException(400, 'Подключение WB не настроено') from None
    totals = dict(orderCount=0, orderSum=Decimal(0), cancelCount=0, cancelSum=Decimal(0))
    offset = 0
    count = 0
    for _ in range(50):
        payload = {'selectedPeriod': {'start': day.isoformat(), 'end': day.isoformat()},
                   'nmIds': [], 'brandNames': [], 'subjectIds': [], 'tagIds': [],
                   'skipDeletedNm': False, 'limit': 1000, 'offset': offset}
        try:
            response = requests.post(URL, headers=wb.headers, json=payload, timeout=90)
        except requests.RequestException:
            raise HTTPException(502, 'Не удалось получить данные WB') from None
        if response.status_code in (401, 403):
            raise HTTPException(403, 'Токен WB не имеет доступа к аналитике')
        if response.status_code == 429:
            raise HTTPException(429, 'Превышен лимит запросов WB. Повторите позже')
        if response.status_code != 200:
            raise HTTPException(502, f'WB вернул HTTP {response.status_code}')
        try:
            data = response.json().get('data')
        except (ValueError, AttributeError):
            data = None
        if not isinstance(data, dict) or not isinstance(data.get('products'), list):
            raise HTTPException(502, 'WB вернул неожиданный формат данных')
        products = data['products']
        for p in products:
            selected = (p.get('statistic') or {}).get('selected') if isinstance(p, dict) else None
            if not isinstance(selected, dict):
                raise HTTPException(502, 'Нет статистики по одной из карточек WB')
            for key in totals:
                value = selected.get(key)
                if not isinstance(value, (int, float)) or isinstance(value, bool):
                    raise HTTPException(502, f'WB не вернул {key} по карточке')
                try:
                    totals[key] += Decimal(str(value)) if 'Sum' in key else int(value)
                except (ValueError, InvalidOperation):
                    raise HTTPException(502, f'Неверный показатель {key}') from None
        count += len(products)
        if len(products) < 1000:
            return totals, count
        # Do not exceed WB rate limits with unthrottled pagination.
        raise HTTPException(409, 'Более 1000 карточек: требуется постраничная синхронизация с ограничением частоты')
    raise HTTPException(409, 'Превышен лимит страниц WB')


@router.post('/wb-sales/sync-day')
def sync_day(day: date = Query(...), request: Request = None, db: Session = Depends(get_db)):
    if day > date.today() or day < date.today() - timedelta(days=364):
        raise HTTPException(400, 'Дата вне доступного периода WB')
    org = getattr(request.state, 'organization_id', None)
    if not org:
        raise HTTPException(401, 'Необходима авторизация')
    totals, products = fetch_one_day(db, day)
    record = db.query(WBSalesDaily).filter_by(organization_id=org, sale_date=day).one_or_none()
    if record is None:
        record = WBSalesDaily(organization_id=org, sale_date=day)
        db.add(record)
    record.order_count = totals['orderCount']
    record.order_sum = totals['orderSum']
    record.cancel_count = totals['cancelCount']
    record.cancel_sum = totals['cancelSum']
    record.products_count = products
    record.synced_at = datetime.utcnow()
    db.commit()
    return {'status': 'ok', 'day': day.isoformat(), 'products': products,
            'ordered_units': record.order_count, 'revenue': float(record.order_sum),
            'cancel_count': record.cancel_count, 'cancel_sum': float(record.cancel_sum)}


@router.get('/wb-sales')
def wb_sales(date_from: date = Query(...), date_to: date = Query(...),
             request: Request = None, db: Session = Depends(get_db)):
    if date_to < date_from or (date_to - date_from).days > 365:
        raise HTTPException(400, 'Некорректный период')
    org = getattr(request.state, 'organization_id', None)
    if not org:
        raise HTTPException(401, 'Необходима авторизация')
    found = {r.sale_date: r for r in db.query(WBSalesDaily).filter(
        WBSalesDaily.organization_id == org, WBSalesDaily.sale_date >= date_from,
        WBSalesDaily.sale_date <= date_to).all()}
    rows = []
    totals = {'revenue': 0.0, 'ordered_units': 0, 'cancel_count': 0, 'cancel_sum': 0.0}
    for n in range((date_to - date_from).days + 1):
        day = date_from + timedelta(days=n)
        r = found.get(day)
        values = {'date': day.isoformat(), 'revenue': float(r.order_sum) if r else 0,
                  'ordered_units': r.order_count if r else 0, 'cancel_count': r.cancel_count if r else 0,
                  'cancel_sum': float(r.cancel_sum) if r else 0, 'loaded': r is not None}
        rows.append(values)
        if r:
            for key in totals:
                totals[key] += values[key]
    return {'status': 'ok', 'source': 'DB', 'metric': 'ordered', 'rows': rows, 'totals': totals,
            'coverage': {'loaded_days': len(found), 'period_days': len(rows), 'complete': len(found) == len(rows)}}
