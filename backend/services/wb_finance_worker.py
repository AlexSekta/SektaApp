"""Tenant-scoped WB finance collector. Only finalized reports; never changes sales tables."""
import logging
import threading
import time
from datetime import date, timedelta
from decimal import Decimal
from sqlalchemy import text
from backend.database import SessionLocal
from backend.auth.tenant import set_app_db_role, set_tenant_context, clear_tenant_context, reset_app_db_role
from backend.services.marketplace_clients import get_wb_client
from backend.scripts.wb_finance_probe import post_finance

log = logging.getLogger('wb_finance_worker')
stop = threading.Event()
thread = None
GAP = 65
last_call = 0.0


def context(org):
    db = SessionLocal()
    set_app_db_role(db)
    set_tenant_context(db, org)
    return db


def close(db):
    try:
        clear_tenant_context(db)
        reset_app_db_role(db)
    finally:
        db.close()


def finance_request(db, path, payload):
    global last_call
    delay = GAP - (time.monotonic() - last_call)
    if delay > 0 and stop.wait(delay):
        return None
    token = get_wb_client(db).headers.get('Authorization')
    last_call = time.monotonic()
    # Existing diagnostic validates HTTP and response format, never prints tokens.
    return post_finance(token, path, payload)


def work_report(org, rid):
    db = context(org)
    try:
        job = db.execute(text('SELECT cursor_rrd,expected_penalty,expected_deduction FROM wb_finance_reports WHERE report_id=:rid AND organization_id=:org'),{'rid':rid,'org':org}).mappings().first()
        if not job: return
        cursor = int(job['cursor_rrd'])
        data = finance_request(db, f'/api/finance/v1/sales-reports/detailed/{rid}', {'limit':1000,'rrdId':cursor,'fields':[]})
        if data is None: raise RuntimeError('Finance API не ответил; проверьте права и лимиты')
        if len(data)>1000: raise RuntimeError('Некорректный размер страницы')
        ids = [int(row['rrdId']) for row in data]
        if data and max(ids)<=cursor: raise RuntimeError('Курсор API не продвинулся')
        for row in data:
            def dec(k): return Decimal(str(row.get(k) or 0))
            db.execute(text('''INSERT INTO wb_finance_entries(organization_id,report_id,rrd_id,nm_id,vendor_code,sku,srid,penalty,deduction,additional_payment,reason)
            VALUES (:o,:r,:id,:nm,:v,:sku,:srid,:p,:d,:a,:reason)
            ON CONFLICT (organization_id,report_id,rrd_id) DO UPDATE SET nm_id=EXCLUDED.nm_id,vendor_code=EXCLUDED.vendor_code,sku=EXCLUDED.sku,srid=EXCLUDED.srid,
            penalty=EXCLUDED.penalty,deduction=EXCLUDED.deduction,additional_payment=EXCLUDED.additional_payment,reason=EXCLUDED.reason'''),
            {'o':org,'r':rid,'id':int(row['rrdId']),'nm':str(row.get('nmId') or '') or None,'v':str(row.get('vendorCode') or '') or None,
            'sku':str(row.get('sku') or '') or None,'srid':str(row.get('srid') or '') or None,
            'p':dec('penalty'),'d':dec('deduction'),'a':dec('additionalPayment'),
            'reason':str(row.get('bonusTypeName') or row.get('sellerOperName') or row.get('docTypeName') or 'Не указано')[:500]})
        count = db.execute(text('SELECT count(*) FROM wb_finance_entries WHERE organization_id=:o AND report_id=:r'),{'o':org,'r':rid}).scalar()
        if not data or len(data)<1000:
            sums=db.execute(text('SELECT coalesce(sum(penalty),0),coalesce(sum(deduction),0) FROM wb_finance_entries WHERE organization_id=:o AND report_id=:r'),{'o':org,'r':rid}).first()
            ok=(job['expected_penalty'] is not None and job['expected_deduction'] is not None and sums[0]==job['expected_penalty'] and sums[1]==job['expected_deduction'])
            status='complete' if ok else 'mismatch'
            error=None if ok else f'Сверка не пройдена: штраф={sums[0]}, удержание={sums[1]}'
        else:
            status='loading';error=None
        db.execute(text('''UPDATE wb_finance_reports SET cursor_rrd=:c,loaded_rows=:n,status=:s,last_error=:e,updated_at=now() WHERE organization_id=:o AND report_id=:r'''),
            {'c':max(ids) if ids else cursor,'n':count,'s':status,'e':error,'o':org,'r':rid})
        db.commit()
        log.info('WB_FINANCE_PAGE_OK org=%s report=%s rows=%s total=%s status=%s',org,rid,len(data),count,status)
    except Exception as exc:
        db.rollback()
        db.execute(text("UPDATE wb_finance_reports SET status='retry',last_error=:e,updated_at=now() WHERE organization_id=:o AND report_id=:r"),{'e':type(exc).__name__,'o':org,'r':rid})
        db.commit()
        log.warning('WB_FINANCE_PAGE_RETRY org=%s report=%s type=%s',org,rid,type(exc).__name__)
    finally: close(db)


def discover(org):
    db=context(org)
    try:
        today=date.today()
        # Last 4 completed weeks; long-term archive builds automatically by adding a separate backfill later.
        end=today-timedelta(days=today.weekday()+1)  # last completed Sunday
        start=end-timedelta(days=27)
        rows=finance_request(db,'/api/finance/v1/sales-reports/list',{'dateFrom':start.isoformat(),'dateTo':end.isoformat(),'period':'weekly','limit':100,'offset':0})
        if rows is None: return
        for row in rows:
            if not row.get('reportId'):continue
            db.execute(text('''INSERT INTO wb_finance_reports(organization_id,report_id,date_from,date_to,expected_penalty,expected_deduction)
            VALUES (:o,:r,:f,:t,:p,:d) ON CONFLICT (organization_id,report_id) DO NOTHING'''),
            {'o':org,'r':int(row['reportId']),'f':row['dateFrom'],'t':row['dateTo'],'p':Decimal(str(row.get('penaltySum') or 0)),'d':Decimal(str(row.get('deductionSum') or 0))})
        db.commit()
    except Exception as exc:
        db.rollback();log.warning('WB_FINANCE_DISCOVER_FAIL org=%s type=%s',org,type(exc).__name__)
    finally:close(db)


def loop():
    if stop.wait(90):return
    last_discover=0
    last_daily_discover=0
    last_history_discover=0
    while not stop.is_set():
        db=SessionLocal()
        try:
            # This worker runs under app role to avoid bypassing RLS on customer data.
            # Service-side discovery of connected organizations, consistent with existing schedulers.
            orgs=[r[0] for r in db.execute(text("SELECT DISTINCT organization_id FROM marketplace_connections WHERE marketplace='WB' AND enabled AND credentials_encrypted IS NOT NULL ORDER BY organization_id")).all()]
            db.rollback()
        except Exception as exc:
            log.warning('WB_FINANCE_ORGS_ERROR type=%s',type(exc).__name__);orgs=[]
        finally:db.close()
        if time.monotonic()-last_discover>86400:
            for org in orgs:
                if stop.is_set():break
                discover(org)
            last_discover=time.monotonic()
        # Daily discovery shares the exact same Finance API request budget.
        from backend.services import wb_finance_daily
        if time.monotonic()-last_daily_discover>21600:
            for org in orgs:
                if stop.is_set():break
                wb_finance_daily.discover(org)
            last_daily_discover=time.monotonic()
        log.info('WB_FINANCE_CYCLE organizations=%s', len(orgs))
        # Detail pages have priority over backfill discovery. Both use the SAME
        # Finance requester and 65-second gap; no second scheduler or API client.
        pending = False
        for org in orgs:
            if stop.is_set():
                break
            try:
                daily_rid = wb_finance_daily.next_report(org)
                if daily_rid is not None:
                    log.info('WB_FINANCE_DAILY_PICK org=%s report=%s', org, daily_rid)
                    wb_finance_daily.work_one(org, daily_rid)
                    pending = True
                    continue
                d = context(org)
                try:
                    weekly_rid = d.execute(text("SELECT report_id FROM wb_finance_reports WHERE organization_id=:o AND status IN ('queued','loading','retry') ORDER BY date_to DESC LIMIT 1"), {'o':org}).scalar()
                finally:
                    close(d)
                if weekly_rid is not None:
                    work_report(org, weekly_rid)
                    pending = True
            except Exception as exc:
                # A failed tenant must never terminate the shared background thread.
                log.exception('WB_FINANCE_ORG_CYCLE_ERROR org=%s error=%s', org, type(exc).__name__)

        # A busy detail queue must not starve historical discovery forever.
        # All Finance calls still use finance_request() and the same 65-sec gap.
        if time.monotonic() - last_history_discover >= 900:
            from backend.services import wb_finance_daily_history
            for org in orgs:
                if stop.is_set():
                    break
                try:
                    wb_finance_daily_history.discover_next(org)
                except Exception as exc:
                    log.exception('WB_DAILY_HISTORY_CYCLE_ERROR org=%s error=%s', org, type(exc).__name__)
            last_history_discover = time.monotonic()
        stop.wait(60)


def start_wb_finance_worker():
    global thread
    if thread and thread.is_alive():return
    stop.clear()
    thread=threading.Thread(target=loop,name='wb-finance-worker',daemon=True)
    thread.start()
    log.info('WB_FINANCE_WORKER_STARTED')


def stop_wb_finance_worker():
    stop.set()
    if thread:thread.join(timeout=3)
