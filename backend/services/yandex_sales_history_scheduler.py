"""Persistent, conservative historical Yandex sales loader using existing order API.

The existing live-day scheduler remains responsible for today/yesterday.  This
worker only fills missing, completed days and does not change sales calculations.
"""
from backend.services.advisory_lock_connection_58_18 import lock_connection
import os
import threading
from datetime import date, datetime, timedelta
from time import monotonic

from sqlalchemy import Column, Date, DateTime, Integer, String, Text, UniqueConstraint, text

from backend.database import Base, engine
from backend.auth.tenant import tenant_session
from backend.logging_config import get_logger
from backend.models.marketplace_connection import MarketplaceConnection
from backend.models.yandex_sales_order import YandexSalesSyncDay
from backend.services.yandex_sales_order_sync import MOSCOW, sync_yandex_sales_day

log = get_logger('yandex_sales_history_scheduler')


class YandexSalesHistoryJob(Base):
    __tablename__ = 'yandex_sales_history_jobs'
    id = Column(Integer, primary_key=True)
    organization_id = Column(Integer, nullable=False, index=True)
    next_day = Column(Date, nullable=True)
    status = Column(String(24), nullable=False, default='pending')
    last_error = Column(Text, nullable=True)
    updated_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    __table_args__ = (UniqueConstraint('organization_id', name='uq_yandex_sales_history_org'),)


_stop = threading.Event()
_worker = None
_MIN_DATE = date(2025, 1, 1)
_GAP_SECONDS = max(20, int(os.getenv('YANDEX_SALES_HISTORY_GAP_SECONDS', '65')))
_ADVISORY_LOCK = 21010229


def verify_yandex_sales_history_schema():
    """Do not modify RLS at application startup. Migration is owner-only."""
    with engine.connect() as conn:
        row = conn.execute(text("""
            SELECT c.relrowsecurity, c.relforcerowsecurity,
              EXISTS (SELECT 1 FROM pg_policies p WHERE p.schemaname = 'public'
                AND p.tablename = 'yandex_sales_history_jobs' AND p.policyname = 'tenant_isolation')
            FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace
            WHERE n.nspname = 'public' AND c.relname = 'yandex_sales_history_jobs'
        """)).first()
        if row is None or not all(row):
            raise RuntimeError('Yandex history schema is not ready; apply sql/yandex_sales_rls_patch_29_1.sql as postgres')


def _organization_ids():
    with engine.connect() as conn:
        result = conn.execute(text("SELECT DISTINCT organization_id FROM marketplace_connections WHERE marketplace='YANDEX' AND enabled AND credentials_encrypted IS NOT NULL ORDER BY organization_id"))
        return [int(row[0]) for row in result]


def _process_org(org_id):
    newest = datetime.now(MOSCOW).date() - timedelta(days=2)
    if newest < _MIN_DATE:
        return False
    with tenant_session(org_id) as db:
        connection = db.query(MarketplaceConnection).filter_by(organization_id=org_id, marketplace='YANDEX', enabled=True).first()
        if not connection or not connection.credentials_encrypted:
            return False
        job = db.query(YandexSalesHistoryJob).filter_by(organization_id=org_id).one_or_none()
        if job is None:
            job = YandexSalesHistoryJob(organization_id=org_id, next_day=newest)
            db.add(job)
            db.commit()
        day = min(job.next_day or newest, newest)
        if day < _MIN_DATE:
            if job.status != 'complete':
                job.status = 'complete'
                job.last_error = None
                job.updated_at = datetime.utcnow()
                db.commit()
            return False
        while day >= _MIN_DATE and db.query(YandexSalesSyncDay.id).filter_by(organization_id=org_id, sale_date=day).first():
            day -= timedelta(days=1)
        if day < _MIN_DATE:
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
        try:
            outcome = sync_yandex_sales_day(db, org_id, day)
            job.next_day = day - timedelta(days=1)
            job.status = 'running'
            job.last_error = None
            job.updated_at = datetime.utcnow()
            db.commit()
            log.info('YANDEX_SALES_HISTORY_OK org=%s day=%s orders=%s lines=%s', org_id, day, outcome['orders'], outcome['lines'])
            return True
        except Exception as exc:
            db.rollback()
            job = db.query(YandexSalesHistoryJob).filter_by(organization_id=org_id).one_or_none()
            if job is not None:
                job.status = 'retry'
                job.last_error = str(exc)[:800]
                job.updated_at = datetime.utcnow()
                db.commit()
            log.warning('YANDEX_SALES_HISTORY_RETRY org=%s day=%s reason=%s', org_id, day, type(exc).__name__)
            return 'retry'


def _loop():
    with lock_connection() as conn:
        if not conn.execute(text('SELECT pg_try_advisory_lock(:lock)'), {'lock': _ADVISORY_LOCK}).scalar():
            log.info('YANDEX_SALES_HISTORY_ALREADY_RUNNING')
            return
        conn.commit()  # End transaction, retain session advisory lock.
        try:
            if _stop.wait(240):
                return
            last_request = 0.0
            while not _stop.is_set():
                try:
                    orgs = _organization_ids()
                    did_any = False
                    for org in orgs:
                        if _stop.is_set():
                            return
                        delay = _GAP_SECONDS - (monotonic() - last_request)
                        if last_request and delay > 0 and _stop.wait(delay):
                            return
                        last_request = monotonic()
                        result = _process_org(org)
                        did_any = did_any or bool(result)
                        if result == 'retry' and _stop.wait(900):
                            return
                    if not did_any and _stop.wait(300):
                        return
                except Exception:
                    log.exception('YANDEX_SALES_HISTORY_LOOP_ERROR')
                    if _stop.wait(300):
                        return
        finally:
            conn.execute(text('SELECT pg_advisory_unlock(:lock)'), {'lock': _ADVISORY_LOCK})
            conn.commit()


def start_yandex_sales_history_scheduler():
    global _worker
    if os.getenv('YANDEX_SALES_HISTORY_AUTO', '1') == '0':
        log.info('YANDEX_SALES_HISTORY_DISABLED')
        return
    if _worker and _worker.is_alive():
        return
    _stop.clear()
    _worker = threading.Thread(target=_loop, name='yandex-sales-history', daemon=True)
    _worker.start()
    log.info('YANDEX_SALES_HISTORY_STARTED request_gap_seconds=%s', _GAP_SECONDS)


def stop_yandex_sales_history_scheduler():
    _stop.set()
    if _worker and _worker.is_alive():
        _worker.join(timeout=3)
