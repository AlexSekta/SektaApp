"""Read-only, organization-scoped WB finance overview (weekly + daily)."""
from datetime import date

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from sqlalchemy import text
from sqlalchemy.orm import Session

from backend.auth.security import require_current_user
from backend.dependencies import get_db

router = APIRouter(prefix='/analytics/wb-finance', tags=['Аналитика — отчёты WB'])


STATUS_LABELS = {
    'queued': 'В очереди',
    'loading': 'Загружается',
    'retry': 'Повтор запроса',
    'complete': 'Сверено',
    'mismatch': 'Расхождение',
}

DAILY_METRICS = {
    'retail': ('retail', 'Реализация'),
    'commission': ('commission', 'Комиссия WB без НДС'),
    'vat': ('vat', 'НДС на комиссию'),
    'acquiring': ('acquiring', 'Эквайринг'),
    'for_pay': ('for_pay', 'К перечислению за товар'),
    'logistics': ('logistics', 'Логистика'),
    'storage': ('storage', 'Хранение'),
    'acceptance': ('acceptance', 'Платная приёмка'),
    'penalty': ('penalty', 'Штрафы'),
    'deduction': ('deduction', 'Удержания'),
    'additional_payment': ('additional_payment', 'Доплаты'),
    'bank_payment': (
        '(for_pay - logistics - storage - acceptance - penalty - deduction + additional_payment)',
        'Итого к оплате',
    ),
}


def org_id(db: Session) -> int:
    oid = db.execute(text("SELECT NULLIF(current_setting('app.organization_id',true),'')::integer")).scalar()
    if not oid:
        raise HTTPException(401, 'Требуется организация')
    return oid


@router.get('/reports')
def reports(request: Request, db: Session = Depends(get_db)):
    require_current_user(request)
    o = org_id(db)
    rows = db.execute(text('''
        SELECT
            r.report_id,
            r.date_from,
            r.date_to,
            r.expected_penalty,
            r.expected_deduction,
            r.status,
            r.loaded_rows,
            r.last_error,
            r.updated_at,
            coalesce(sum(e.penalty), 0) penalty,
            coalesce(sum(e.deduction), 0) deduction
        FROM wb_finance_reports r
        LEFT JOIN wb_finance_entries e
          ON e.organization_id = r.organization_id
         AND e.report_id = r.report_id
        WHERE r.organization_id = :o
        GROUP BY r.organization_id, r.report_id
        ORDER BY r.date_to DESC, r.report_id DESC
    '''), {'o': o}).mappings()
    return {'items': [dict(x) for x in rows]}


@router.get('/reports/{report_id}')
def detail(report_id: int, request: Request, db: Session = Depends(get_db)):
    require_current_user(request)
    o = org_id(db)
    report = db.execute(text('''
        SELECT status, expected_penalty, expected_deduction
        FROM wb_finance_reports
        WHERE organization_id = :o AND report_id = :r
    '''), {'o': o, 'r': report_id}).mappings().first()
    if not report:
        raise HTTPException(404, 'Отчёт не найден')

    groups = db.execute(text('''
        SELECT
            CASE
                WHEN penalty <> 0 THEN 'Штраф'
                WHEN deduction <> 0 THEN 'Удержание'
                ELSE 'Доплата'
            END kind,
            reason,
            CASE
                WHEN nullif(nm_id,'') IS NOT NULL OR nullif(vendor_code,'') IS NOT NULL OR nullif(sku,'') IS NOT NULL
                    THEN 'product_candidate'
                ELSE 'no_product_id'
            END attribution,
            count(*) rows,
            sum(CASE
                    WHEN penalty <> 0 THEN penalty
                    WHEN deduction <> 0 THEN deduction
                    ELSE additional_payment
                END) amount
        FROM wb_finance_entries
        WHERE organization_id = :o
          AND report_id = :r
          AND (penalty <> 0 OR deduction <> 0 OR additional_payment <> 0)
        GROUP BY kind, reason, attribution
        ORDER BY abs(sum(CASE
                    WHEN penalty <> 0 THEN penalty
                    WHEN deduction <> 0 THEN deduction
                    ELSE additional_payment
                END)) DESC
    '''), {'o': o, 'r': report_id}).mappings()
    return {
        'report': dict(report),
        'groups': [dict(x) for x in groups],
        'note': 'Привязка к товару предварительная; окончательное распределение требует проверки причины и SKU.',
    }


@router.get('/reports/{report_id}/metric-details')
def weekly_metric_details(report_id: int, request: Request, metric: str = Query(...), limit: int = Query(500, ge=1, le=1000), db: Session = Depends(get_db)):
    require_current_user(request)
    o = org_id(db)
    if metric not in ('penalty', 'deduction', 'additional_payment'):
        raise HTTPException(422, 'Недоступный показатель недельного отчёта')
    exists = db.execute(text('SELECT 1 FROM wb_finance_reports WHERE organization_id=:o AND report_id=:r'), {'o': o, 'r': report_id}).scalar()
    if not exists:
        raise HTTPException(404, 'Отчёт не найден')
    rows = db.execute(text(f'''
        SELECT coalesce(nullif(vendor_code,''), nullif(sku,''), nullif(nm_id,''), '') identifier,
            coalesce(nullif(reason,''), 'Не указано') reason,
            count(*) rows, round(coalesce(sum({metric}),0),2) amount
        FROM wb_finance_entries
        WHERE organization_id=:o AND report_id=:r AND {metric}<>0
        GROUP BY identifier, reason
        ORDER BY abs(sum({metric})) DESC, identifier
        LIMIT :limit
    '''), {'o': o, 'r': report_id, 'limit': limit}).mappings()
    return {'metric': metric, 'items': [dict(row) for row in rows], 'limited_to': limit}


@router.get('/reports/{report_id}/products')
def products(report_id: int, request: Request, db: Session = Depends(get_db)):
    require_current_user(request)
    o = org_id(db)
    exists = db.execute(text('''
        SELECT 1
        FROM wb_finance_reports
        WHERE organization_id = :o AND report_id = :r
    '''), {'o': o, 'r': report_id}).first()
    if not exists:
        raise HTTPException(404, 'Отчёт не найден')

    rows = db.execute(text('''
        SELECT
            coalesce(nullif(vendor_code,''), nullif(nm_id,''), nullif(sku,''), 'Без идентификатора') identifier,
            count(*) FILTER (WHERE penalty <> 0 OR deduction <> 0) operations,
            coalesce(sum(penalty), 0) penalty,
            coalesce(sum(deduction), 0) deduction
        FROM wb_finance_entries
        WHERE organization_id = :o
          AND report_id = :r
          AND (penalty <> 0 OR deduction <> 0)
        GROUP BY identifier
        ORDER BY abs(sum(penalty) + sum(deduction)) DESC
        LIMIT 500
    '''), {'o': o, 'r': report_id}).mappings()
    return {'items': [dict(x) for x in rows], 'limited_to': 500}


@router.get('/daily')
def daily_reports(request: Request, date_from: str, date_to: str, db: Session = Depends(get_db)):
    require_current_user(request)
    try:
        start = date.fromisoformat(date_from)
        end = date.fromisoformat(date_to)
    except ValueError as exc:
        raise HTTPException(422, 'Неверный формат даты') from exc

    if end < start or (end - start).days > 366:
        raise HTTPException(422, 'Диапазон должен быть не более 367 дней')

    o = org_id(db)
    rows = db.execute(text('''
        SELECT
            r.report_id,
            r.report_date,
            r.report_type,
            r.status,
            r.loaded_rows,
            r.last_error,
            r.updated_at,
            r.expected_retail,
            r.expected_for_pay,
            r.expected_bank_payment,
            r.expected_logistics,
            r.expected_penalty,
            r.expected_deduction,
            coalesce(sum(e.retail), 0) retail,
            coalesce(sum(e.for_pay), 0) for_pay,
            coalesce(sum(e.commission), 0) commission,
            coalesce(sum(e.vat), 0) vat,
            coalesce(sum(e.acquiring), 0) acquiring,
            coalesce(sum(e.logistics), 0) logistics,
            coalesce(sum(e.storage), 0) storage,
            coalesce(sum(e.acceptance), 0) acceptance,
            coalesce(sum(e.penalty), 0) penalty,
            coalesce(sum(e.deduction), 0) deduction,
            coalesce(sum(e.additional_payment), 0) additional_payment
        FROM wb_finance_daily_reports r
        LEFT JOIN wb_finance_daily_entries e
          ON e.organization_id = r.organization_id
         AND e.report_id = r.report_id
        WHERE r.organization_id = :o
          AND r.report_date BETWEEN :a AND :b
        GROUP BY r.organization_id, r.report_id
        ORDER BY r.report_date DESC, r.report_type
    '''), {'o': o, 'a': start, 'b': end}).mappings()
    return {'items': [dict(row) for row in rows]}


@router.get('/daily/{report_id}/reasons')
def daily_reasons(report_id: int, request: Request, db: Session = Depends(get_db)):
    require_current_user(request)
    o = org_id(db)
    exists = db.execute(text('''
        SELECT 1
        FROM wb_finance_daily_reports
        WHERE organization_id = :o AND report_id = :r
    '''), {'o': o, 'r': report_id}).scalar()
    if not exists:
        raise HTTPException(404, 'Отчёт не найден')

    rows = db.execute(text('''
        SELECT
            reason,
            operation,
            CASE
                WHEN coalesce(nullif(vendor_code,''), nullif(nm_id,''), nullif(sku,'')) IS NULL THEN 'general'
                ELSE 'sku_candidate'
            END attribution,
            count(*) rows,
            coalesce(sum(penalty), 0) penalty,
            coalesce(sum(deduction), 0) deduction,
            coalesce(sum(logistics), 0) logistics,
            coalesce(sum(storage), 0) storage,
            coalesce(sum(acceptance), 0) acceptance
        FROM wb_finance_daily_entries
        WHERE organization_id = :o
          AND report_id = :r
          AND (penalty <> 0 OR deduction <> 0 OR logistics <> 0 OR storage <> 0 OR acceptance <> 0)
        GROUP BY reason, operation, attribution
        ORDER BY abs(sum(penalty) + sum(deduction) + sum(logistics) + sum(storage) + sum(acceptance)) DESC
        LIMIT 250
    '''), {'o': o, 'r': report_id}).mappings()
    return {'items': [dict(row) for row in rows], 'limited_to': 250}


@router.get('/daily/{report_id}/metric-details')
def daily_metric_details(
    report_id: int,
    request: Request,
    metric: str = Query(..., description='Код показателя'),
    limit: int = Query(250, ge=1, le=1000),
    db: Session = Depends(get_db),
):
    require_current_user(request)
    o = org_id(db)
    exists = db.execute(text('''
        SELECT report_type, report_date, status
        FROM wb_finance_daily_reports
        WHERE organization_id = :o AND report_id = :r
    '''), {'o': o, 'r': report_id}).mappings().first()
    if not exists:
        raise HTTPException(404, 'Отчёт не найден')

    metric_info = DAILY_METRICS.get(metric)
    if not metric_info:
        raise HTTPException(422, 'Неизвестный показатель')

    expr, label = metric_info
    sql = f'''
        SELECT
            coalesce(nullif(vendor_code,''), nullif(sku,''), nullif(nm_id,''), '') identifier,
            reason,
            operation,
            CASE
                WHEN coalesce(nullif(vendor_code,''), nullif(sku,''), nullif(nm_id,'')) IS NULL THEN 'general'
                ELSE 'sku_candidate'
            END attribution,
            count(*) rows,
            round(coalesce(sum({expr}), 0), 2) amount
        FROM wb_finance_daily_entries
        WHERE organization_id = :o
          AND report_id = :r
          AND {expr} <> 0
        GROUP BY identifier, reason, operation, attribution
        ORDER BY abs(sum({expr})) DESC, count(*) DESC, identifier
        LIMIT :limit
    '''
    rows = db.execute(text(sql), {'o': o, 'r': report_id, 'limit': limit}).mappings()

    return {
        'metric': metric,
        'label': label,
        'status_label': STATUS_LABELS.get(exists['status'], exists['status']),
        'report': {
            'report_id': report_id,
            'report_type': exists['report_type'],
            'report_date': exists['report_date'],
            'status': exists['status'],
        },
        'items': [dict(row) for row in rows],
        'limited_to': limit,
    }
