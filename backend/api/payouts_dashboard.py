"""Read-only dashboard: payable amounts from WB daily financial reports."""
from datetime import date

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy import text
from sqlalchemy.orm import Session

from backend.auth.security import require_current_user
from backend.dependencies import get_db

router = APIRouter(prefix='/analytics', tags=['Аналитика — выплаты'])


@router.get('/payouts-dashboard')
def payouts_dashboard(request: Request, date_from: str, date_to: str, db: Session = Depends(get_db)):
    require_current_user(request)
    try:
        start = date.fromisoformat(date_from)
        end = date.fromisoformat(date_to)
    except ValueError as exc:
        raise HTTPException(422, 'Неверный формат даты') from exc
    if end < start or (end - start).days > 366:
        raise HTTPException(422, 'Диапазон должен быть не более 367 дней')
    org = db.execute(text("SELECT NULLIF(current_setting('app.organization_id', true), '')::integer")).scalar()
    if not org:
        raise HTTPException(401, 'Требуется организация')

    # Use WB's own bank payout figure for finalized reports. For reports still
    # being loaded use a provisional signed sum of financial entry operations.
    # This is a report-date aggregation, not a payment receipt date.
    rows = db.execute(text('''
        SELECT r.report_id, r.report_date, r.report_type, r.status,
               r.expected_bank_payment,
               COALESCE(SUM(
                  CASE WHEN LOWER(BTRIM(COALESCE(e.operation,''))) = 'возврат'
                       THEN -e.for_pay ELSE e.for_pay END
                  - e.logistics - e.storage - e.acceptance
                  - e.penalty - e.deduction + e.additional_payment
               ), 0) AS calculated_payout
        FROM wb_finance_daily_reports r
        LEFT JOIN wb_finance_daily_entries e
          ON e.organization_id=r.organization_id AND e.report_id=r.report_id
        WHERE r.organization_id=:o AND r.report_date BETWEEN :a AND :b
        GROUP BY r.organization_id, r.report_id
        ORDER BY r.report_date DESC, r.report_id DESC
    '''), {'o': org, 'a': start, 'b': end}).mappings().all()

    total = 0
    incomplete = 0
    report_count = 0
    for row in rows:
        report_count += 1
        if row['status'] == 'complete' and row['expected_bank_payment'] is not None:
            total += row['expected_bank_payment']
        else:
            total += row['calculated_payout']
            incomplete += 1

    # Ozon dashboard card is strictly the sum of daily accruals in the selected
    # date range, never the sum of potentially overlapping weekly rows.
    ozon_rows = db.execute(text('''
        SELECT day, status, total_amount FROM ozon_finance_days
        WHERE organization_id=:o AND day BETWEEN :a AND :b
    '''), {'o': org, 'a': start, 'b': end}).mappings().all()
    ozon_total = sum((r['total_amount'] for r in ozon_rows), 0)
    ozon_loaded = sum(r['status'] == 'complete' for r in ozon_rows)
    ozon_summary = {
        'available': bool(ozon_rows),
        'total': float(round(ozon_total, 2)) if ozon_rows else None,
        'report_count': len(ozon_rows),
        'incomplete_reports': (end-start).days+1 - ozon_loaded,
        'message': 'По датам ежедневных начислений Ozon',
    }

    return {
        'date_from': start.isoformat(), 'date_to': end.isoformat(),
        'marketplaces': {
            'WB': {
                'available': True,
                'total': float(round(total, 2)),
                'report_count': report_count,
                'incomplete_reports': incomplete,
                'message': 'По датам ежедневных финансовых отчётов WB',
            },
            'OZON': ozon_summary,
            'YANDEX': {'available': False, 'total': None, 'message': 'Финансовые выплаты Я.Маркета пока не подключены'},
        },
        'note': 'Это сумма к выплате по датам финансовых отчётов, а не подтверждённые поступления на расчётный счёт.',
    }

@router.get('/payouts-dashboard/weekly-periods')
def weekly_payout_periods(request: Request, date_from: str, date_to: str,
                          db: Session = Depends(get_db)):
    """Estimate withdrawal dates using native WB weekly report periods."""
    from datetime import timedelta
    require_current_user(request)
    try:
        start, end = date.fromisoformat(date_from), date.fromisoformat(date_to)
    except ValueError as exc:
        raise HTTPException(422, 'Неверный формат даты') from exc
    if end < start or (end-start).days > 366:
        raise HTTPException(422, 'Диапазон должен быть не более 367 дней')
    org = db.execute(text("SELECT NULLIF(current_setting('app.organization_id', true), '')::integer")).scalar()
    if not org:
        raise HTTPException(401, 'Требуется организация')
    rows = db.execute(text('''
        SELECT date_from, date_to, count(*) AS report_count,
               count(*) FILTER (WHERE status='complete' AND expected_bank_payment IS NOT NULL) AS complete_count,
               sum(expected_bank_payment) FILTER (WHERE status='complete') AS complete_amount,
               array_agg(report_id ORDER BY report_id) AS report_ids
        FROM wb_finance_reports
        WHERE organization_id=:o AND date_from<=:end AND date_to>=:start
        GROUP BY date_from,date_to
        ORDER BY date_to DESC,date_from DESC
    '''), {'o':org, 'start':start, 'end':end}).mappings().all()
    today=date.today()
    items=[]
    for row in rows:
        period_end=row['date_to']
        offset=(7-period_end.weekday()) % 7 or 7
        issued=period_end+timedelta(days=offset)
        available=issued+timedelta(days=14)
        fully_loaded=row['report_count']==row['complete_count']
        items.append({
            'date_from':row['date_from'].isoformat(), 'date_to':period_end.isoformat(),
            'estimated_issued_at':issued.isoformat(),
            'estimated_available_at':available.isoformat(),
            'date_reached':today>=available,
            'complete':fully_loaded,
            'report_count':row['report_count'],
            'complete_count':row['complete_count'],
            'amount':float(row['complete_amount']) if row['complete_amount'] is not None else None,
            'report_ids':list(row['report_ids']),
        })
    return {'items':items, 'note':'Даты расчётные: первый понедельник после периода + 14 дней. Фактический доступный баланс может отличаться из-за выводов и специальных условий.'}


@router.get('/payouts-dashboard/ozon-weekly-periods')
def ozon_weekly_payout_periods(request: Request, date_from: str, date_to: str,
                              db: Session = Depends(get_db)):
    """Weekly accrual snapshots, not Ozon's official payout register.

    Payment dates are a user-observed rule (period end +24 calendar days),
    adjusted for weekends and explicitly configured holidays. Never imply
    the date or payment status came from the Ozon API.
    """
    from datetime import timedelta
    require_current_user(request)
    try:
        start, end = date.fromisoformat(date_from), date.fromisoformat(date_to)
    except ValueError as exc:
        raise HTTPException(422, 'Неверный формат даты') from exc
    if end < start or (end-start).days > 366:
        raise HTTPException(422, 'Диапазон должен быть не более 367 дней')
    org = db.execute(text("SELECT NULLIF(current_setting('app.organization_id', true), '')::integer")).scalar()
    if not org:
        raise HTTPException(401, 'Требуется организация')
    today = date.today()
    # Explicitly observed closure for Russian 4 November 2026; holidays in
    # other years must be configured rather than assumed to have same schedule.
    observed_nonworking = {date(2026, 11, 4)}
    first_monday = start - timedelta(days=start.weekday())
    last_monday = end - timedelta(days=end.weekday())
    rows = db.execute(text("SELECT day, status, row_count, total_amount FROM ozon_finance_days WHERE organization_id=:o AND day BETWEEN :a AND :b"), {'o': org, 'a': first_monday, 'b': last_monday+timedelta(days=6)}).mappings().all()
    by_day = {r['day']: r for r in rows}
    # Group by both calendar week and calendar month: a cross-month week
    # becomes two separate Ozon-style reporting periods (e.g. 28–30 Sep,
    # 01–04 Oct), without counting any accrual twice.
    groups = {}
    cursor = first_monday
    final_day = last_monday + timedelta(days=6)
    while cursor <= final_day:
        monday = cursor - timedelta(days=cursor.weekday())
        key = (monday, cursor.year, cursor.month)
        entry = groups.setdefault(key, {'start': cursor, 'end': cursor})
        entry['end'] = cursor
        cursor += timedelta(days=1)
    items = []
    for group in sorted(groups.values(), key=lambda g: g['end'], reverse=True):
        period_start, period_end = group['start'], group['end']
        if period_end < start or period_start > end:
            continue
        last_expected = min(period_end, today)
        expected_days = max(0, (last_expected-period_start).days+1)
        period_rows = [by_day[period_start+timedelta(days=i)] for i in range(expected_days)
                       if period_start+timedelta(days=i) in by_day]
        complete_count = sum(r['status']=='complete' for r in period_rows)
        amount = sum((r['total_amount'] for r in period_rows), 0)
        estimated = period_end + timedelta(days=24)
        while estimated.weekday() >= 5 or estimated in observed_nonworking:
            estimated += timedelta(days=1)
        period_length = (period_end-period_start).days+1
        full = period_end < today and expected_days == period_length and complete_count == period_length
        items.append({
            'date_from': period_start.isoformat(), 'date_to': period_end.isoformat(),
            'amount': float(round(amount, 2)) if period_rows else None,
            'loaded_days': complete_count, 'expected_days': expected_days,
            'complete': full,
            'estimated_payment_at': estimated.isoformat(),
            'date_reached': today >= estimated,
            'calendar_adjustment_applied': estimated != period_end+timedelta(days=24),
            'status': 'complete' if full else 'partial',
        })
    return {
        'items': items,
        'note': 'Суммы построены из ежедневных начислений, период понедельник–воскресенье. '
                'Дата перечисления расчётная: конец недели +24 дня, с переносом выходных '
                'и подтверждённого 04.11.2026; это не статус банка и не официальный график Ozon.',
    }
