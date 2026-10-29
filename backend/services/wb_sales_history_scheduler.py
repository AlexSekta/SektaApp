"""Persistent per-organization WB history worker, only known Sales Funnel API.

The worker never mutates other marketplaces or marketplace stock records.
"""
from backend.services.advisory_lock_connection_58_18 import lock_connection
import os
import threading
from datetime import date, datetime, timedelta
from time import monotonic

from sqlalchemy import Column, Date, DateTime, Integer, String, Text, UniqueConstraint, text
from backend.database import Base, engine
from backend.auth.tenant import tenant_session
from backend.models.marketplace_connection import MarketplaceConnection
from backend.models.wb_sales_daily import WBSalesDaily
from backend.api.wb_sales_daily import fetch_one_day
from backend.services.wb_sales_funnel_throttle import fetch_throttled
from backend.logging_config import get_logger

logger = get_logger('wb_sales_history_scheduler')


class WBSalesHistoryJob(Base):
    __tablename__ = 'wb_sales_history_jobs'
    id = Column(Integer, primary_key=True)
    organization_id = Column(Integer, nullable=False, index=True)
    next_day = Column(Date, nullable=True)
    status = Column(String(24), nullable=False, default='pending')
    last_error = Column(Text, nullable=True)
    updated_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    __table_args__ = (UniqueConstraint('organization_id', name='uq_wb_history_job_org'),)


_stop = threading.Event()
_worker = None
_RATE_SECONDS = 65  # more conservative than the existing standalone backfill
_MIN_DATE = date(2025, 1, 1)
_ADVISORY_LOCK = 21010226


def ensure_wb_sales_history_schema():
    Base.metadata.create_all(bind=engine, tables=[WBSalesHistoryJob.__table__])
    with engine.begin() as conn:
        conn.execute(text('GRANT SELECT, INSERT, UPDATE, DELETE ON wb_sales_history_jobs TO marketplace_app'))
        conn.execute(text('GRANT USAGE, SELECT ON SEQUENCE wb_sales_history_jobs_id_seq TO marketplace_app'))
        conn.execute(text('ALTER TABLE wb_sales_history_jobs ENABLE ROW LEVEL SECURITY'))
        conn.execute(text('ALTER TABLE wb_sales_history_jobs FORCE ROW LEVEL SECURITY'))
        conn.execute(text('DROP POLICY IF EXISTS tenant_isolation ON wb_sales_history_jobs'))
        conn.execute(text("CREATE POLICY tenant_isolation ON wb_sales_history_jobs USING (organization_id = NULLIF(current_setting('app.organization_id', true), '')::integer) WITH CHECK (organization_id = NULLIF(current_setting('app.organization_id', true), '')::integer)"))


def _organization_ids():
    # Discovery uses the database owner, but all business writes are in tenant_session + RLS.
    with engine.connect() as conn:
        return [int(r[0]) for r in conn.execute(text("SELECT DISTINCT organization_id FROM marketplace_connections WHERE marketplace='WB' AND enabled AND credentials_encrypted IS NOT NULL ORDER BY organization_id"))]


def _process_org(org_id):
    oldest = max(_MIN_DATE, date.today() - timedelta(days=364))
    newest = date.today() - timedelta(days=1)
    if oldest > newest:
        return False
    with tenant_session(org_id) as db:
        connection = db.query(MarketplaceConnection).filter_by(organization_id=org_id, marketplace='WB', enabled=True).first()
        if not connection or not connection.credentials_encrypted:
            return False
        job = db.query(WBSalesHistoryJob).filter_by(organization_id=org_id).one_or_none()
        if job is None:
            job = WBSalesHistoryJob(organization_id=org_id, next_day=newest)
            db.add(job)
            db.commit()
        day = min(job.next_day or newest, newest)
        if day < oldest:
            if job.status != 'complete':
                job.status = 'complete'
                job.last_error = None
                job.updated_at = datetime.utcnow()
                db.commit()
            return False
        # Skip contiguous already-saved days in a single DB transaction.
        while day >= oldest and db.query(WBSalesDaily.id).filter_by(organization_id=org_id, sale_date=day).first():
            day -= timedelta(days=1)
        if day < oldest:
            job.next_day = day
            job.status = 'complete'
            job.last_error = None
            job.updated_at = datetime.utcnow()
            db.commit()
            return False
        job.next_day = day
        job.status = 'running'
        job.updated_at = datetime.utcnow()
        db.commit()
        # An exception MUST NOT advance the cursor; previously loaded days remain intact.
        try:
            totals, count = fetch_throttled(fetch_one_day, db, day)
            db.add(WBSalesDaily(
                organization_id=org_id, sale_date=day,
                order_count=totals['orderCount'], order_sum=totals['orderSum'],
                cancel_count=totals['cancelCount'], cancel_sum=totals['cancelSum'],
                products_count=count, synced_at=datetime.utcnow(),
            ))
            job.next_day = day - timedelta(days=1)
            job.status = 'running'
            job.last_error = None
            job.updated_at = datetime.utcnow()
            db.commit()
            logger.info('WB_HISTORY_OK org=%s day=%s products=%s', org_id, day, count)
            return True
        except Exception as exc:
            db.rollback()
            job = db.query(WBSalesHistoryJob).filter_by(organization_id=org_id).one_or_none()
            if job:
                job.status = 'retry'
                job.last_error = str(getattr(exc, 'detail', str(exc)))[:800]
                job.updated_at = datetime.utcnow()
                db.commit()
            logger.warning('WB_HISTORY_RETRY org=%s day=%s reason=%s', org_id, day, type(exc).__name__)
            return 'retry'


def _loop():
    # DB advisory lock prevents concurrent backfills across uvicorn worker processes.
    with lock_connection() as lock_conn:
        if not lock_conn.execute(text('SELECT pg_try_advisory_lock(:key)'), {'key': _ADVISORY_LOCK}).scalar():
            logger.info('WB_HISTORY_ALREADY_RUNNING')
            return
        lock_conn.commit()  # End transaction, retain session advisory lock.
        try:
            _stop.wait(80)  # leave room for startup and user requests
            last_request = 0.0
            while not _stop.is_set():
                try:
                    ids = _organization_ids()
                    if not ids:
                        _stop.wait(300)
                        continue
                    attempted = False
                    for org_id in ids:
                        if _stop.is_set():
                            break
                        # ensure at least 65 seconds between all potential API calls
                        delay = _RATE_SECONDS - (monotonic() - last_request)
                        if last_request and delay > 0 and _stop.wait(delay):
                            return
                        last_request = monotonic()
                        did_request = _process_org(org_id)
                        attempted = attempted or bool(did_request)
                        if did_request == 'retry':
                            # Rate limit or upstream error: cool down before trying again.
                            if _stop.wait(900):
                                return
                    if not attempted:
                        _stop.wait(300)
                except Exception:
                    logger.exception('WB_HISTORY_LOOP_ERROR')
                    _stop.wait(300)
        finally:
            lock_conn.execute(text('SELECT pg_advisory_unlock(:key)'), {'key': _ADVISORY_LOCK})
            lock_conn.commit()


def start_wb_sales_history_scheduler():
    global _worker
    if os.getenv('WB_SALES_HISTORY_AUTO', '1') == '0':
        logger.info('WB_HISTORY_DISABLED')
        return
    if _worker and _worker.is_alive():
        return
    _stop.clear()
    _worker = threading.Thread(target=_loop, name='wb-sales-history', daemon=True)
    _worker.start()


def stop_wb_sales_history_scheduler():
    _stop.set()
    if _worker and _worker.is_alive():
        _worker.join(timeout=3)
