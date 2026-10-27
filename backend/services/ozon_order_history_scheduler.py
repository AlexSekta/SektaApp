"""Low-priority historical Ozon FBO/FBS customer-price estimate backfill.

Uses the existing atomic sync_day method; no alternative API, no new price formula.
Owner migration is required before starting the worker.
"""
import os
import threading
from datetime import date, datetime, timedelta
from sqlalchemy import Column, Date, DateTime, Integer, String, Text, UniqueConstraint, text
from backend.database import Base, engine
from backend.auth.tenant import tenant_session
from backend.logging_config import get_logger
from backend.models.marketplace_connection import MarketplaceConnection
from backend.models.ozon_order import OzonOrderSyncDay
from backend.services.ozon_order_sync import MOSCOW, sync_day
from backend.services.ozon_sync_guard import sync_guard

log = get_logger('ozon_order_history_scheduler')

class OzonOrderHistoryJob(Base):
    __tablename__ = 'ozon_order_history_jobs'
    id = Column(Integer, primary_key=True)
    organization_id = Column(Integer, nullable=False, index=True)
    next_day = Column(Date, nullable=True)
    status = Column(String(24), nullable=False, default='pending')
    last_error = Column(Text, nullable=True)
    updated_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    __table_args__ = (UniqueConstraint('organization_id', name='uq_ozon_order_history_org'),)

_stop = threading.Event()
_worker = None
_LOCK_KEY = 21010231
_MIN_DATE = date(2025, 1, 1)
_START_DELAY = 480
_INTERVAL = max(900, int(os.getenv('OZON_ORDER_HISTORY_INTERVAL_SECONDS', '1200')))


def verify_ozon_order_history_schema():
    with engine.connect() as conn:
        row = conn.execute(text("""
            SELECT c.relrowsecurity, c.relforcerowsecurity,
                EXISTS (SELECT 1 FROM pg_policies p WHERE p.schemaname='public'
                  AND p.tablename='ozon_order_history_jobs' AND p.policyname='tenant_isolation')
            FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace
            WHERE n.nspname='public' AND c.relname='ozon_order_history_jobs'
        """)).first()
        if row is None or not all(row):
            raise RuntimeError('Apply sql/ozon_order_history_patch_31.sql as postgres before startup')


def _org_ids():
    with engine.connect() as conn:
        return [int(r[0]) for r in conn.execute(text("""
            SELECT DISTINCT organization_id FROM marketplace_connections
            WHERE marketplace='OZON' AND enabled AND credentials_encrypted IS NOT NULL
            ORDER BY organization_id
        """))]


def _one_org(org_id):
    today = datetime.now(MOSCOW).date()
    newest = today - timedelta(days=2)  # live collector manages today/yesterday
    with tenant_session(org_id) as db:
        connection = db.query(MarketplaceConnection).filter_by(
            organization_id=org_id, marketplace='OZON', enabled=True).first()
        if connection is None or not connection.credentials_encrypted:
            return 'skip'
        job = db.query(OzonOrderHistoryJob).filter_by(organization_id=org_id).one_or_none()
        if job is None:
            job = OzonOrderHistoryJob(organization_id=org_id, next_day=newest)
            db.add(job)
            db.commit()
        if job.status in ('complete', 'unavailable'):
            return 'skip'
        day = min(job.next_day or newest, newest)
        while day >= _MIN_DATE:
            exists = db.query(OzonOrderSyncDay.id).filter_by(
                organization_id=org_id, sale_date=day).first()
            if not exists:
                break
            day -= timedelta(days=1)
        if day < _MIN_DATE:
            job.status = 'complete'
            job.next_day = day
            job.last_error = None
            job.updated_at = datetime.utcnow()
            db.commit()
            log.info('OZON_ORDER_HISTORY_COMPLETE org=%s', org_id)
            return 'complete'
        # Shared with live Ozon order/event collectors; skip rather than queue work.
        if not sync_guard.acquire(blocking=False):
            log.info('OZON_ORDER_HISTORY_SKIPPED concurrent collector org=%s', org_id)
            return 'busy'
        try:
            job.next_day = day
            job.status = 'running'
            job.updated_at = datetime.utcnow()
            db.commit()
            result = sync_day(db, org_id, day)
            job = db.query(OzonOrderHistoryJob).filter_by(organization_id=org_id).one()
            job.next_day = day - timedelta(days=1)
            job.status = 'running' if job.next_day >= _MIN_DATE else 'complete'
            job.last_error = None
            job.updated_at = datetime.utcnow()
            db.commit()
            log.info('OZON_ORDER_HISTORY_OK org=%s day=%s postings=%s lines=%s',
                     org_id, day, result['postings'], result['lines'])
            return 'ok'
        except Exception as exc:
            db.rollback()
            job = db.query(OzonOrderHistoryJob).filter_by(organization_id=org_id).one_or_none()
            if job:
                job.status = 'retry'
                job.next_day = day
                job.last_error = f'{type(exc).__name__}: {exc}'[:800]
                job.updated_at = datetime.utcnow()
                db.commit()
            log.warning('OZON_ORDER_HISTORY_RETRY org=%s day=%s error=%s',
                        org_id, day, type(exc).__name__)
            return 'retry'
        finally:
            sync_guard.release()


def _loop():
    # Connection-scoped advisory lock prevents duplicate workers across processes.
    with engine.connect() as conn:
        if not conn.execute(text('SELECT pg_try_advisory_lock(:k)'), {'k': _LOCK_KEY}).scalar():
            log.info('OZON_ORDER_HISTORY_ALREADY_RUNNING')
            return
        try:
            if _stop.wait(_START_DELAY):
                return
            while not _stop.is_set():
                try:
                    ids = _org_ids()
                    for org in ids:
                        if _stop.is_set():
                            break
                        _one_org(org)
                        if _stop.wait(90):
                            break
                except Exception:
                    log.exception('OZON_ORDER_HISTORY_LOOP_ERROR')
                if _stop.wait(_INTERVAL):
                    break
        finally:
            conn.execute(text('SELECT pg_advisory_unlock(:k)'), {'k': _LOCK_KEY})


def start_ozon_order_history_scheduler():
    global _worker
    if os.getenv('OZON_ORDER_HISTORY_AUTO', '1') == '0':
        log.info('OZON_ORDER_HISTORY_DISABLED')
        return
    if _worker is not None and _worker.is_alive():
        return
    _stop.clear()
    _worker = threading.Thread(target=_loop, daemon=True, name='ozon-order-history')
    _worker.start()
    log.info('OZON_ORDER_HISTORY_STARTED startup_delay_seconds=%s interval_seconds=%s',
             _START_DELAY, _INTERVAL)


def stop_ozon_order_history_scheduler():
    _stop.set()
    if _worker is not None and _worker.is_alive():
        _worker.join(timeout=3)
