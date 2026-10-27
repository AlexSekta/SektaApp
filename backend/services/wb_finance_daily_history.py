"""Incremental historical discovery of WB daily reports, without duplicate detail work.

Uses the same Finance API requester / worker as current daily and weekly reports.
Progress is tenant-scoped and persistent; completed source reports are never modified.
"""
import logging
from datetime import date, timedelta
from decimal import Decimal
from sqlalchemy import text
from backend.services import wb_finance_worker as weekly

log = logging.getLogger('wb_finance_daily_history')
START_DATE = date(2025, 1, 1)
WINDOW_DAYS = 30


def discover_next(org):
    db = weekly.context(org)
    try:
        # Initialize after the recent-day discovery window. The earliest date is
        # a chosen retention target, not a promise that WB keeps all that history.
        start_to = date.today() - timedelta(days=15)
        db.execute(text('''INSERT INTO wb_finance_daily_history_jobs
          (organization_id, next_to, status)
          VALUES (:org, :next_to, 'running')
          ON CONFLICT (organization_id) DO NOTHING'''), {'org': org, 'next_to': start_to})
        db.commit()
        job = db.execute(text('''SELECT next_to, status FROM wb_finance_daily_history_jobs
          WHERE organization_id=:org FOR UPDATE'''), {'org': org}).mappings().first()
        if not job or job['status'] == 'complete':
            db.rollback()
            return
        end = min(job['next_to'], date.today() - timedelta(days=15))
        if end < START_DATE:
            db.execute(text('''UPDATE wb_finance_daily_history_jobs SET status='complete', last_error=NULL, updated_at=now()
              WHERE organization_id=:org'''), {'org': org})
            db.commit()
            log.info('WB_DAILY_HISTORY_COMPLETE org=%s earliest_target=%s', org, START_DATE)
            return
        begin = max(START_DATE, end - timedelta(days=WINDOW_DAYS - 1))
        rows = weekly.finance_request(db, '/api/finance/v1/sales-reports/list',
            {'dateFrom': begin.isoformat(), 'dateTo': end.isoformat(), 'period': 'daily', 'limit': 1000, 'offset': 0})
        if rows is None:
            raise RuntimeError('Finance API rejected historical daily list')
        # Do not advance the cursor if a response is potentially truncated.
        if len(rows) >= 1000:
            raise RuntimeError('Daily history list may be truncated; needs pagination')
        for r in rows:
            if not isinstance(r, dict) or not r.get('reportId'):
                continue
            db.execute(text('''INSERT INTO wb_finance_daily_reports
              (organization_id,report_id,report_date,report_type,created_date,expected_retail,expected_for_pay,
               expected_bank_payment,expected_logistics,expected_penalty,expected_deduction,expected_storage,expected_acceptance)
              VALUES (:o,:id,:dt,:type,:created,:ret,:pay,:bank,:log,:pen,:ded,:st,:acc)
              ON CONFLICT (organization_id,report_id) DO NOTHING'''), {
                'o': org, 'id': int(r['reportId']), 'dt': r['dateFrom'],
                'type': r.get('reportType'), 'created': r.get('createDate') or None,
                'ret': Decimal(str(r.get('retailAmountSum') or 0)),
                'pay': Decimal(str(r.get('forPaySum') or 0)),
                'bank': Decimal(str(r.get('bankPaymentSum') or 0)),
                'log': Decimal(str(r.get('deliveryServiceSum') or 0)),
                'pen': Decimal(str(r.get('penaltySum') or 0)),
                'ded': Decimal(str(r.get('deductionSum') or 0)),
                'st': Decimal(str(r.get('paidStorageSum') or 0)),
                'acc': Decimal(str(r.get('paidAcceptanceSum') or 0)),
            })
        next_to = begin - timedelta(days=1)
        status = 'complete' if next_to < START_DATE else 'running'
        db.execute(text('''UPDATE wb_finance_daily_history_jobs
          SET next_to=:next_to, status=:status, last_error=NULL, updated_at=now()
          WHERE organization_id=:org'''), {'next_to': next_to, 'status': status, 'org': org})
        db.commit()
        log.info('WB_DAILY_HISTORY_DISCOVER_OK org=%s from=%s to=%s reports=%s next_to=%s status=%s',
                 org, begin, end, len(rows), next_to, status)
    except Exception as exc:
        db.rollback()
        try:
            db.execute(text('''UPDATE wb_finance_daily_history_jobs
              SET status='retry', last_error=:error, updated_at=now() WHERE organization_id=:org'''),
              {'org': org, 'error': type(exc).__name__})
            db.commit()
        except Exception:
            db.rollback()
        log.warning('WB_DAILY_HISTORY_DISCOVER_RETRY org=%s reason=%s', org, type(exc).__name__)
    finally:
        weekly.close(db)
