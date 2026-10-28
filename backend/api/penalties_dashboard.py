"""Penalty breakdown for dashboard: read-only, tenant scoped, daily WB finance source.

Ozon and Yandex are reported as unavailable until financial penalty data ingestion exists.
"""
from datetime import date
from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy import text
from sqlalchemy.orm import Session
from backend.dependencies import get_db
from backend.auth.security import require_current_user

router = APIRouter(prefix='/analytics', tags=['Аналитика — штрафы'])


def organization_id(db: Session) -> int:
    oid = db.execute(text("SELECT NULLIF(current_setting('app.organization_id', true), '')::integer")).scalar()
    if not oid:
        raise HTTPException(401, 'Требуется организация')
    return oid


@router.get('/penalties-breakdown')
def penalties_breakdown(request: Request, date_from: str, date_to: str, db: Session = Depends(get_db)):
    require_current_user(request)
    try:
        start, end = date.fromisoformat(date_from), date.fromisoformat(date_to)
    except ValueError as exc:
        raise HTTPException(422, 'Неверный формат даты') from exc
    if end < start or (end - start).days > 366:
        raise HTTPException(422, 'Допустимый диапазон — до 367 дней')
    org = organization_id(db)

    # Only daily financial reports: never sum the same expense from weekly + daily.
    # Group first by reason+SKU to avoid an arbitrary row limit that distorts totals.
    rows = db.execute(text('''
        SELECT
            COALESCE(NULLIF(BTRIM(e.reason), ''), 'Без описания') AS reason,
            COALESCE(NULLIF(BTRIM(e.vendor_code), ''), NULLIF(BTRIM(e.sku), ''),
                     NULLIF(BTRIM(e.nm_id), ''), '') AS sku,
            COUNT(*)::integer AS quantity,
            COALESCE(SUM(e.penalty), 0) AS amount
        FROM wb_finance_daily_entries e
        JOIN wb_finance_daily_reports r
          ON r.organization_id = e.organization_id AND r.report_id = e.report_id
        WHERE e.organization_id = :o
          AND r.report_date BETWEEN :start AND :end
          AND e.penalty <> 0
        GROUP BY 1, 2
        ORDER BY reason, sku
    '''), {'o': org, 'start': start, 'end': end}).mappings().all()

    status_counts = db.execute(text('''
        SELECT status, COUNT(*)::integer AS quantity
        FROM wb_finance_daily_reports
        WHERE organization_id=:o AND report_date BETWEEN :start AND :end
        GROUP BY status
    '''), {'o': org, 'start': start, 'end': end}).mappings().all()

    reasons = {}
    total = 0
    for row in rows:
        reason = row['reason']
        amount = float(row['amount'])
        qty = row['quantity']
        item = reasons.setdefault(reason, {'reason': reason, 'quantity': 0, 'amount': 0, 'items': []})
        item['quantity'] += qty
        item['amount'] += amount
        item['items'].append({'description': reason, 'sku': row['sku'], 'quantity': qty, 'amount': amount})
        total += amount
    return {
        'date_from': start.isoformat(), 'date_to': end.isoformat(),
        'marketplaces': {
            'WB': {
                'available': True, 'total': round(total, 2),
                'reasons': sorted(reasons.values(), key=lambda x: abs(x['amount']), reverse=True),
                'report_statuses': {row['status']: row['quantity'] for row in status_counts},
            },
            'OZON': {'available': False, 'total': None, 'reasons': [], 'message': 'Загрузка штрафов Ozon пока не подключена'},
            'YANDEX': {'available': False, 'total': None, 'reasons': [], 'message': 'Загрузка штрафов Я.Маркета пока не подключена'},
        },
        'note': 'Штрафы WB группируются по дате ежедневного финансового отчёта, не по дате заказа.',
    }
