"""Ozon financial accruals. Raw signed amounts, resumable day cursor, no estimates.

Manually launched via backend.scripts.ozon_finance_sync_56 until verified in production.
"""
import json
import logging
import time
from datetime import date, timedelta
from decimal import Decimal, InvalidOperation
from sqlalchemy import text

import backend.models.auth  # register ORM relationship targets
from backend.database import SessionLocal
from backend.auth.tenant import (set_app_db_role, set_tenant_context,
                                 clear_tenant_context, reset_app_db_role)
from backend.services.marketplace_clients import get_ozon_client

log = logging.getLogger('ozon_finance_56')
PATH = '/v1/finance/accrual/by-day'


def open_context(org):
    db = SessionLocal()
    try:
        set_app_db_role(db)
        set_tenant_context(db, org)
        return db
    except Exception:
        db.close()
        raise


def close_context(db):
    try:
        db.rollback()
        clear_tenant_context(db)
        reset_app_db_role(db)
    finally:
        db.close()


def parse_amount(row):
    money = row.get('total_amount')
    if not isinstance(money, dict):
        raise ValueError('total_amount is missing')
    try:
        amount = Decimal(str(money['amount']))
    except (KeyError, InvalidOperation, TypeError, ValueError) as exc:
        raise ValueError('invalid total_amount') from exc
    if not amount.is_finite():
        raise ValueError('nonfinite total_amount')
    return amount, str(money.get('currency') or '')[:8]


def sync_day(org, day, max_pages=100, delay=2, refresh=False):
    """One date; commits each page atomically with last_id. Idempotent by accrual_id."""
    db = open_context(org)
    try:
        db.execute(text('''INSERT INTO ozon_finance_days(organization_id, day)
            VALUES (:o,:d) ON CONFLICT DO NOTHING'''), {'o':org,'d':day})
        db.commit()
        state = db.execute(text('''SELECT status,last_id,page_count FROM ozon_finance_days
             WHERE organization_id=:o AND day=:d'''), {'o':org,'d':day}).mappings().one()
        if state['status'] == 'complete' and not refresh:
            return {'day':str(day), 'status':'complete', 'skipped':True}
        if refresh:
            # Restart from page 1. Keep existing rows until the refreshed scan completes;
            # do not lose financial history on an API failure.
            db.execute(text('''UPDATE ozon_finance_days SET last_id='',status='loading',
                page_count=0,last_error=NULL,updated_at=now()
                WHERE organization_id=:o AND day=:d'''), {'o':org,'d':day})
            db.commit()
        cursor = '' if refresh else (state['last_id'] or '')
        seen_ids = set() if refresh else None
        seen = {cursor} if cursor else set()
        client = get_ozon_client(db)
        page_count = 0
        while page_count < max_pages:
            if page_count:
                time.sleep(delay)
            response = client.post_raw(PATH, {'date':str(day), 'last_id':cursor})
            status = response.get('status_code')
            if status != 200:
                raise RuntimeError(f'Ozon Finance API HTTP {status}')
            body = response.get('body')
            if not isinstance(body, dict) or not isinstance(body.get('accruals'), list):
                raise ValueError('Unexpected accruals response structure')
            rows = body['accruals']
            new_cursor = body.get('last_id') or ''
            if rows and new_cursor and (new_cursor == cursor or new_cursor in seen):
                raise ValueError('Non-progressing or repeated accrual cursor')
            for row in rows:
                if not isinstance(row, dict) or not isinstance(row.get('accrual_id'), int):
                    raise ValueError('Missing accrual_id')
                if seen_ids is not None: seen_ids.add(row['accrual_id'])
                amount, currency = parse_amount(row)
                # Structured fields stored internally for later audited classification.
                db.execute(text('''INSERT INTO ozon_finance_accruals
                    (organization_id,day,accrual_id,accrued_at,category,amount,currency,
                     unit_number,posting_number,item_fees,non_item_fee,container_fees,posting)
                    VALUES (:o,:d,:id,:dt,:cat,:amt,:cur,:unit,:postnum,
                            CAST(:item AS jsonb),CAST(:non AS jsonb),CAST(:container AS jsonb),CAST(:posting AS jsonb))
                    ON CONFLICT (organization_id,accrual_id) DO UPDATE SET
                     day=EXCLUDED.day, accrued_at=EXCLUDED.accrued_at,
                     category=EXCLUDED.category, amount=EXCLUDED.amount, currency=EXCLUDED.currency,
                     unit_number=EXCLUDED.unit_number, posting_number=EXCLUDED.posting_number,
                     item_fees=EXCLUDED.item_fees, non_item_fee=EXCLUDED.non_item_fee,
                     container_fees=EXCLUDED.container_fees, posting=EXCLUDED.posting'''),{
                    'o':org,'d':day,'id':row['accrual_id'],
                    'dt':str(row.get('date') or '')[:64],
                    'cat':str(row.get('accrued_category') or 'UNKNOWN')[:50],
                    'amt':amount,'cur':currency,'unit':str(row.get('unit_number') or '')[:120],
                    'postnum':str((row.get('posting') or {}).get('posting_number') or '')[:120] if isinstance(row.get('posting'),dict) else None,
                    'item':json.dumps(row.get('item_fees'),ensure_ascii=False),
                    'non':json.dumps(row.get('non_item_fee'),ensure_ascii=False),
                    'container':json.dumps(row.get('container_fees'),ensure_ascii=False),
                    'posting':json.dumps(row.get('posting'),ensure_ascii=False),
                })
            complete = not new_cursor or not rows
            # API has a cursor even on some full final pages; only empty cursor/rows finish the day.
            db.execute(text('''UPDATE ozon_finance_days SET last_id=:cursor,
                page_count=page_count+1, status=:status, last_error=NULL, updated_at=now()
                WHERE organization_id=:o AND day=:d'''),{
                'o':org,'d':day,'cursor':new_cursor or cursor,
                'status':'complete' if complete else 'loading'})
            db.commit()
            page_count += 1
            cursor = new_cursor or cursor
            seen.add(cursor)
            log.info('OZON_FINANCE_PAGE org=%s day=%s pages=%s complete=%s',org,day,page_count,complete)
            if complete:
                break
        if refresh and complete:
            # Remove disappeared accruals only after fully reading the new snapshot.
            existing = db.execute(text('''SELECT accrual_id FROM ozon_finance_accruals
                WHERE organization_id=:o AND day=:d'''), {'o':org,'d':day}).scalars()
            obsolete = [accrual_id for accrual_id in existing if accrual_id not in seen_ids]
            for offset in range(0,len(obsolete),500):
                db.execute(text('''DELETE FROM ozon_finance_accruals
                    WHERE organization_id=:o AND day=:d AND accrual_id IN :ids''').bindparams(
                    __import__('sqlalchemy').bindparam('ids',expanding=True)
                ), {'o':org,'d':day,'ids':obsolete[offset:offset+500]})
            db.commit()
        sums = db.execute(text('''SELECT count(*) AS n,coalesce(sum(amount),0) AS total
             FROM ozon_finance_accruals WHERE organization_id=:o AND day=:d'''),
             {'o':org,'d':day}).mappings().one()
        db.execute(text('''UPDATE ozon_finance_days SET row_count=:n,total_amount=:t,updated_at=now()
                    WHERE organization_id=:o AND day=:d'''),
                   {'o':org,'d':day,'n':sums['n'],'t':sums['total']})
        db.commit()
        return {'day':str(day),'status':'complete' if complete else 'loading',
                'rows':sums['n'],'total':str(sums['total']),'pages_this_run':page_count}
    except Exception as exc:
        db.rollback()
        try:
            db.execute(text('''UPDATE ozon_finance_days SET status='retry',last_error=:e,
                updated_at=now() WHERE organization_id=:o AND day=:d'''),
                {'o':org,'d':day,'e':f'{type(exc).__name__}: {str(exc)[:120]}'})
            db.commit()
        except Exception:
            db.rollback()
        raise
    finally:
        close_context(db)


def sync_range(org, start, end, max_pages_per_day=100, delay=2):
    """Descending dates, stops on first error; no unbounded background activity."""
    current = end
    results = []
    while current >= start:
        result = sync_day(org, current, max_pages=max_pages_per_day, delay=delay)
        results.append(result)
        if result['status'] != 'complete':
            break
        current -= timedelta(days=1)
        if current >= start:
            time.sleep(delay)
    return results
