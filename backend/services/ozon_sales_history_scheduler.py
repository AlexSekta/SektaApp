"""Low-priority Ozon analytics history. Same /v1/analytics/data source.

Run the owner SQL migration before starting the worker. One 90-day window per
organization per cycle, deliberately offset from the hourly live scheduler.
"""
import os
import threading
from datetime import date, datetime, timedelta
from sqlalchemy import Column, Date, DateTime, Integer, String, Text, UniqueConstraint, text
from backend.database import Base, engine
from backend.auth.tenant import tenant_session
from backend.logging_config import get_logger
from backend.models.marketplace_connection import MarketplaceConnection
from backend.services.ozon_sales_sync import sync_ozon_sales

log = get_logger('ozon_sales_history_scheduler')

class OzonSalesHistoryJob(Base):
    __tablename__ = 'ozon_sales_history_jobs'
    id = Column(Integer, primary_key=True)
    organization_id = Column(Integer, nullable=False, index=True)
    next_day = Column(Date, nullable=True)
    status = Column(String(24), nullable=False, default='pending')
    last_error = Column(Text, nullable=True)
    updated_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    __table_args__ = (UniqueConstraint('organization_id', name='uq_ozon_sales_history_org'),)

_stop = threading.Event()
_worker = None
_MIN_DATE = date(2025, 1, 1)
_LOCK_KEY = 21010230


def verify_ozon_sales_history_schema():
    with engine.connect() as conn:
        row = conn.execute(text("""
            SELECT c.relrowsecurity, c.relforcerowsecurity,
              EXISTS (SELECT 1 FROM pg_policies p WHERE p.schemaname='public'
                AND p.tablename='ozon_sales_history_jobs' AND p.policyname='tenant_isolation')
            FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace
            WHERE n.nspname='public' AND c.relname='ozon_sales_history_jobs'
        """)).first()
        if row is None or not all(row):
            raise RuntimeError('Ozon history table is not ready; apply sql/ozon_sales_history_patch_30.sql as postgres')


def _org_ids():
    with engine.connect() as conn:
        return [int(r[0]) for r in conn.execute(text("""
            SELECT DISTINCT organization_id FROM marketplace_connections
            WHERE marketplace='OZON' AND enabled AND credentials_encrypted IS NOT NULL
            ORDER BY organization_id
        """))]


def _one_org(org_id):
    # Live scheduler owns the last 90 days. History begins immediately before it.
    newest = date.today() - timedelta(days=90)
    if newest < _MIN_DATE:
        return False
    with tenant_session(org_id) as db:
        conn = db.query(MarketplaceConnection).filter_by(organization_id=org_id, marketplace='OZON', enabled=True).first()
        if conn is None or not conn.credentials_encrypted:
            return False
        job = db.query(OzonSalesHistoryJob).filter_by(organization_id=org_id).one_or_none()
        if job is None:
            job = OzonSalesHistoryJob(organization_id=org_id, next_day=newest)
            db.add(job)
            db.commit()
        if job.status in ('complete', 'unavailable'):
            return False
        upper = min(job.next_day or newest, newest)
        if upper < _MIN_DATE:
            job.status = 'complete'
            job.updated_at = datetime.utcnow()
            db.commit()
            return False
        lower = max(_MIN_DATE, upper - timedelta(days=89))
        try:
            result = sync_ozon_sales(db, org_id, date_from_override=lower, date_to_override=upper)
            # Empty responses are not proof of zero sales or absence of API access.
            # Stop rather than silently mark an entire historical window covered.
            if not result['rows_received']:
                job.status = 'unavailable'
                job.last_error = f'API returned no daily rows for {lower}..{upper}; range not marked covered'
            else:
                job.next_day = lower - timedelta(days=1)
                job.status = 'running' if job.next_day >= _MIN_DATE else 'complete'
                job.last_error = None
            job.updated_at = datetime.utcnow()
            db.commit()
            log.info('OZON_SALES_HISTORY_OK org=%s from=%s to=%s rows=%s status=%s', org_id, lower, upper, result['rows_saved'], job.status)
            return True
        except Exception as exc:
            db.rollback()
            job = db.query(OzonSalesHistoryJob).filter_by(organization_id=org_id).one_or_none()
            if job:
                job.status = 'retry'
                job.last_error = str(exc)[:800]
                job.updated_at = datetime.utcnow()
                db.commit()
            log.warning('OZON_SALES_HISTORY_RETRY org=%s from=%s to=%s reason=%s', org_id, lower, upper, type(exc).__name__)
            return 'retry'


def _loop():
    with engine.connect() as dbconn:
        if not dbconn.execute(text('SELECT pg_try_advisory_lock(:key)'), {'key': _LOCK_KEY}).scalar():
            log.info('OZON_SALES_HISTORY_ALREADY_RUNNING')
            return
        try:
            # Standard Ozon analytics sync runs about 65 seconds after startup.
            # Offset history far enough to avoid overlapping its API request.
            if _stop.wait(600):
                return
            while not _stop.is_set():
                try:
                    for org_id in _org_ids():
                        if _stop.is_set():
                            return
                        result = _one_org(org_id)
                        if result == 'retry':
                            # A cooldown matters more than fast backfill for Ozon.
                            if _stop.wait(3600):
                                return
                        elif _stop.wait(75):
                            return
                except Exception:
                    log.exception('OZON_SALES_HISTORY_LOOP_ERROR')
                # At most one historical request per org per hour.
                if _stop.wait(3600):
                    return
        finally:
            dbconn.execute(text('SELECT pg_advisory_unlock(:key)'), {'key': _LOCK_KEY})


def start_ozon_sales_history_scheduler():
    global _worker
    if os.getenv('OZON_SALES_HISTORY_AUTO', '1') == '0':
        log.info('OZON_SALES_HISTORY_DISABLED')
        return
    if _worker is not None and _worker.is_alive():
        return
    _stop.clear()
    _worker = threading.Thread(target=_loop, daemon=True, name='ozon-sales-history')
    _worker.start()
    log.info('OZON_SALES_HISTORY_STARTED startup_delay_seconds=600')


def stop_ozon_sales_history_scheduler():
    _stop.set()
    if _worker and _worker.is_alive():
        _worker.join(timeout=3)
