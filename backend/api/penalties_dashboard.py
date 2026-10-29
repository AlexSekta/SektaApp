"""Read-only dashboard penalties from WB daily reports and Ozon accrual fees."""
from datetime import date
from collections import defaultdict
from decimal import Decimal
from backend.api.ozon_finance_56 import _fees_in, _money_field, _product_nodes
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
    # Ozon: use fee type IDs confirmed as fines, not all negative accruals.
    # A single accrual can have multiple fee rows/SKUs; count fee occurrences.
    # Raw total_amount is NOT added to these fee totals (no double-counting).
    catalog_rows = db.execute(text("""SELECT type_id, name, description
        FROM ozon_finance_type_catalog WHERE organization_id=:o"""), {'o':org}).mappings().all()
    fine_types = {}
    for item in catalog_rows:
        type_id = str(item['type_id'])
        api_name = str(item['name'] or '')
        api_description = str(item['description'] or '')
        # Explicitly verified fines + further DefectFine* types from the Ozon catalog.
        if type_id in ('92', '94') or api_name.startswith('DefectFine'):
            fine_types[type_id] = api_description or api_name or f'Тип штрафа {type_id}'

    ozon_rows = db.execute(text("""SELECT a.item_fees, a.non_item_fee,
               a.container_fees, a.posting
        FROM ozon_finance_accruals a
        JOIN ozon_finance_days d ON d.organization_id=a.organization_id AND d.day=a.day
        WHERE a.organization_id=:o AND a.day BETWEEN :start AND :end
        ORDER BY a.day DESC, a.accrual_id"""), {'o':org,'start':start,'end':end}).mappings()

    ozon_rows = list(ozon_rows)
    ozon_skus = set()
    for entry in ozon_rows:
        value = entry['item_fees']
        if isinstance(value, dict):
            for group in value.get('fees') or []:
                if isinstance(group, dict) and group.get('sku') is not None:
                    ozon_skus.add(str(group['sku']))
        for prod in _product_nodes(entry['posting']):
            if prod.get('sku') is not None:
                ozon_skus.add(str(prod['sku']))
    sku_to_article = defaultdict(set)
    sku_list = sorted(ozon_skus)
    for offset in range(0, len(sku_list), 400):
        mapped = db.execute(text("""SELECT sku,offer_id FROM ozon_order_lines
            WHERE organization_id=:o AND sku::text=ANY(:skus)"""),
            {'o':org,'skus':sku_list[offset:offset+400]}).mappings()
        for matched in mapped:
            if matched['offer_id']:
                sku_to_article[str(matched['sku'])].add(str(matched['offer_id']))

    ozon_reasons = defaultdict(lambda: {'quantity':0, 'amount':Decimal('0'), 'items':defaultdict(lambda: {'quantity':0,'amount':Decimal('0')})})
    for entry in ozon_rows:
        def register(fee, sku=None):
            tid = str(fee.get('type_id', ''))
            if tid not in fine_types: return
            value = _money_field(fee.get('accrued'))
            if value is None or value == 0: return
            # Fines are negative accruals. Positive reversals reduce the net fine.
            cost = -value
            reason = fine_types[tid]
            bucket = ozon_reasons[reason]
            bucket['quantity'] += 1
            bucket['amount'] += cost
            article_candidates = sku_to_article.get(str(sku), set()) if sku is not None else set()
            article = next(iter(article_candidates)) if len(article_candidates) == 1 else ''
            bucket['items'][article]['quantity'] += 1
            bucket['items'][article]['amount'] += cost

        item_fees = entry['item_fees']
        if isinstance(item_fees, dict):
            for group in item_fees.get('fees') or []:
                if isinstance(group, dict):
                    for fee in _fees_in(group.get('fees') or []):
                        register(fee, group.get('sku'))
        for fee in _fees_in([entry['non_item_fee'], entry['container_fees']]):
            register(fee)
        for product in _product_nodes(entry['posting']):
            delivery = product.get('delivery')
            if isinstance(delivery, dict):
                for fee in _fees_in(delivery.get('services') or []):
                    register(fee, product.get('sku'))

    ozon_result = []
    for reason, bucket in ozon_reasons.items():
        ozon_result.append({
            'reason':reason, 'quantity':bucket['quantity'],
            'amount':round(float(bucket['amount']),2),
            'items':[{'description':reason, 'sku':article,
                      'quantity':part['quantity'], 'amount':round(float(part['amount']),2)}
                     for article,part in sorted(bucket['items'].items())]
        })
    ozon_result.sort(key=lambda r:abs(r['amount']), reverse=True)
    ozon_total = round(sum(r['amount'] for r in ozon_result), 2)
    ozon_states = db.execute(text("""SELECT status, count(*)::integer AS quantity
        FROM ozon_finance_days
        WHERE organization_id=:o AND day BETWEEN :start AND :end
        GROUP BY status"""), {'o':org,'start':start,'end':end}).mappings().all()

    return {
        'date_from': start.isoformat(), 'date_to': end.isoformat(),
        'marketplaces': {
            'WB': {
                'available': True, 'total': round(total, 2),
                'reasons': sorted(reasons.values(), key=lambda x: abs(x['amount']), reverse=True),
                'report_statuses': {row['status']: row['quantity'] for row in status_counts},
            },
            'OZON': {'available': True, 'total': ozon_total, 'reasons': ozon_result,
                     'report_statuses': {r['status']:r['quantity'] for r in ozon_states},
                     'message': 'Учитываются только подтверждённые штрафные типы Ozon'},
            'YANDEX': {'available': False, 'total': None, 'reasons': [], 'message': 'Загрузка штрафов Я.Маркета пока не подключена'},
        },
        'note': 'Штрафы WB — из ежедневных финансовых отчётов. Ozon — из подтверждённых штрафных типов в ежедневных начислениях. Незагруженные дни не включены.',
    }
