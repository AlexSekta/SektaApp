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
            'OZON': {'available': False, 'total': None, 'message': 'Финансовые выплаты Ozon пока не подключены'},
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
