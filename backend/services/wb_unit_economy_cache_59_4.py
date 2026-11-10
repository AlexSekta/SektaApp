"""Persistent WB unit-economy snapshot: reads never trigger WB API calls."""
import os
import threading
from datetime import datetime, timezone
from collections import Counter

import requests
from sqlalchemy import text
from backend.auth.tenant import set_app_db_role, reset_app_db_role, set_tenant_context, clear_tenant_context
from backend.database import SessionLocal, engine
from backend.logging_config import get_logger
from backend.services.marketplace_clients import get_wb_client
from backend.services.marketplace_credentials import MarketplaceNotConfiguredError

logger = get_logger('wb_unit_economy')
_stop = threading.Event()
_thread = None


def ensure_schema():
    with engine.begin() as conn:
        conn.execute(text('''CREATE TABLE IF NOT EXISTS wb_unit_economy_snapshots (
            organization_id integer PRIMARY KEY REFERENCES organizations(id) ON DELETE CASCADE,
            cards jsonb NOT NULL DEFAULT '[]'::jsonb,
            rates jsonb NOT NULL DEFAULT '[]'::jsonb,
            synced_at timestamptz NOT NULL DEFAULT now()
        )'''))
        conn.execute(text('ALTER TABLE wb_unit_economy_snapshots ENABLE ROW LEVEL SECURITY'))
        conn.execute(text('ALTER TABLE wb_unit_economy_snapshots FORCE ROW LEVEL SECURITY'))
        conn.execute(text('''DO $$ BEGIN
            IF NOT EXISTS (SELECT 1 FROM pg_policies WHERE schemaname='public'
                AND tablename='wb_unit_economy_snapshots' AND policyname='wb_unit_economy_org_policy') THEN
                CREATE POLICY wb_unit_economy_org_policy ON wb_unit_economy_snapshots
                    USING (organization_id = NULLIF(current_setting('app.organization_id',true),'')::integer)
                    WITH CHECK (organization_id = NULLIF(current_setting('app.organization_id',true),'')::integer);
            END IF;
        END $$'''))
        conn.execute(text('GRANT SELECT,INSERT,UPDATE,DELETE ON wb_unit_economy_snapshots TO marketplace_app'))
        conn.execute(text('''CREATE TABLE IF NOT EXISTS wb_unit_economy_options (
            organization_id integer PRIMARY KEY REFERENCES organizations(id) ON DELETE CASCADE,
            total_commission_rate numeric(8,4) NOT NULL,
            details jsonb NOT NULL DEFAULT '{}'::jsonb,
            synced_at timestamptz NOT NULL DEFAULT now()
        )'''))
        conn.execute(text('ALTER TABLE wb_unit_economy_options ENABLE ROW LEVEL SECURITY'))
        conn.execute(text('ALTER TABLE wb_unit_economy_options FORCE ROW LEVEL SECURITY'))
        conn.execute(text('''DO $$ BEGIN
            IF NOT EXISTS (SELECT 1 FROM pg_policies WHERE schemaname='public'
                AND tablename='wb_unit_economy_options' AND policyname='wb_unit_economy_options_org_policy') THEN
                CREATE POLICY wb_unit_economy_options_org_policy ON wb_unit_economy_options
                    USING (organization_id = NULLIF(current_setting('app.organization_id',true),'')::integer)
                    WITH CHECK (organization_id = NULLIF(current_setting('app.organization_id',true),'')::integer);
            END IF;
        END $$'''))
        conn.execute(text('GRANT SELECT,INSERT,UPDATE,DELETE ON wb_unit_economy_options TO marketplace_app'))

        conn.execute(text("""CREATE TABLE IF NOT EXISTS unit_economy_settings (
            organization_id integer NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
            marketplace varchar(16) NOT NULL,
            tariff_package_rate numeric(8,4),
            only_enabled boolean NOT NULL DEFAULT true,
            updated_at timestamptz NOT NULL DEFAULT now(),
            PRIMARY KEY (organization_id, marketplace))"""))
        conn.execute(text("""CREATE TABLE IF NOT EXISTS unit_economy_product_status (
            organization_id integer NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
            product_id integer NOT NULL REFERENCES master_products(id) ON DELETE CASCADE,
            marketplace varchar(16) NOT NULL,
            status varchar(16) NOT NULL DEFAULT 'active',
            updated_at timestamptz NOT NULL DEFAULT now(),
            PRIMARY KEY (organization_id, product_id, marketplace),
            CONSTRAINT unit_economy_status_values CHECK (status IN ('active','archive')))"""))
        for table in ('unit_economy_settings','unit_economy_product_status'):
            conn.execute(text(f'ALTER TABLE {table} ENABLE ROW LEVEL SECURITY'))
            conn.execute(text(f'ALTER TABLE {table} FORCE ROW LEVEL SECURITY'))
            conn.execute(text(f"""DO $$ BEGIN
                IF NOT EXISTS (SELECT 1 FROM pg_policies WHERE schemaname='public'
                    AND tablename='{table}' AND policyname='{table}_org_policy') THEN
                    CREATE POLICY {table}_org_policy ON {table}
                        USING (organization_id = NULLIF(current_setting('app.organization_id',true),'')::integer)
                        WITH CHECK (organization_id = NULLIF(current_setting('app.organization_id',true),'')::integer);
                END IF;
            END $$"""))
            conn.execute(text(f'GRANT SELECT,INSERT,UPDATE,DELETE ON {table} TO marketplace_app'))


def get_snapshot(db):
    return db.execute(text('SELECT cards,rates,synced_at FROM wb_unit_economy_snapshots LIMIT 1')).mappings().first()


def get_option_snapshot(db):
    return db.execute(text('SELECT total_commission_rate,details,synced_at FROM wb_unit_economy_options LIMIT 1')).mappings().first()


def sync_options(org_id):
    """Separate sync: options failures do not roll back existing card/rate snapshot."""
    from decimal import Decimal, InvalidOperation
    import json
    db = SessionLocal()
    try:
        set_app_db_role(db)
        set_tenant_context(db, org_id)
        try:
            client = get_wb_client(db)
        except MarketplaceNotConfiguredError:
            db.rollback()
            return 'not_configured'
        response = requests.get('https://common-api.wildberries.ru/api/common/v1/tariff-constructor/options',
                                headers=client.headers,params={'locale':'ru'},timeout=30)
        if response.status_code == 429:
            logger.warning('WB_UNIT_ECONOMY_OPTIONS_RATE_LIMIT org=%s; retaining snapshot',org_id)
            db.rollback()
            return 'rate_limited'
        response.raise_for_status()
        payload=response.json()
        if not isinstance(payload,dict) or 'totalCommissionRate' not in payload:
            raise ValueError('WB tariff constructor: missing totalCommissionRate')
        try:
            rate=Decimal(str(payload['totalCommissionRate']))
        except (TypeError, ValueError, InvalidOperation) as exc:
            raise ValueError('WB tariff constructor: invalid rate') from exc
        if not rate.is_finite() or rate<0 or rate>100:
            raise ValueError('WB tariff constructor: rate out of range')
        db.execute(text('''INSERT INTO wb_unit_economy_options(organization_id,total_commission_rate,details,synced_at)
            VALUES (:org,:rate,CAST(:details AS jsonb),now())
            ON CONFLICT(organization_id) DO UPDATE SET total_commission_rate=excluded.total_commission_rate,
            details=excluded.details,synced_at=excluded.synced_at'''),
            {'org':org_id,'rate':rate,'details':json.dumps(payload,ensure_ascii=False)})
        db.commit()
        logger.info('WB_UNIT_ECONOMY_OPTIONS_SYNC_OK org=%s rate=%s',org_id,rate)
        return 'ok'
    except Exception:
        db.rollback()
        logger.exception('WB_UNIT_ECONOMY_OPTIONS_SYNC_FAILED org=%s; previous data retained',org_id)
        return 'error'
    finally:
        clear_tenant_context(db)
        reset_app_db_role(db)
        db.close()


def sync_organization(org_id):
    db = SessionLocal()
    try:
        set_app_db_role(db)
        set_tenant_context(db, org_id)
        try:
            client = get_wb_client(db)
        except MarketplaceNotConfiguredError:
            db.rollback()
            return 'not_configured'
        cards = client.get_products().get('cards') or []
        if not isinstance(cards, list):
            raise ValueError('WB cards: invalid format')
        response = requests.get('https://common-api.wildberries.ru/api/v1/tariffs/commission',
                                headers=client.headers, timeout=30)
        if response.status_code == 429:
            logger.warning('WB_UNIT_ECONOMY_RATE_LIMIT org=%s; retained last snapshot',org_id)
            db.rollback()
            return 'rate_limited'
        response.raise_for_status()
        payload = response.json()
        rates = payload.get('report') if isinstance(payload,dict) else None
        if not isinstance(rates,list) or not rates:
            raise ValueError('WB tariffs empty or invalid: previous snapshot retained')
        import json
        db.execute(text('''INSERT INTO wb_unit_economy_snapshots(organization_id,cards,rates,synced_at)
          VALUES (:org,CAST(:cards AS jsonb),CAST(:rates AS jsonb),now())
          ON CONFLICT(organization_id) DO UPDATE SET cards=excluded.cards,
          rates=excluded.rates,synced_at=excluded.synced_at'''),
          {'org':org_id,'cards':json.dumps(cards,ensure_ascii=False),
           'rates':json.dumps(rates,ensure_ascii=False)})
        db.commit()
        logger.info('WB_UNIT_ECONOMY_SYNC_OK org=%s cards=%s rates=%s',org_id,len(cards),len(rates))
        return 'ok'
    except Exception:
        db.rollback()
        logger.exception('WB_UNIT_ECONOMY_SYNC_FAILED org=%s; previous snapshot retained',org_id)
        return 'error'
    finally:
        clear_tenant_context(db)
        reset_app_db_role(db)
        db.close()


def _run_cycle():
    # Enumerate enabled WB integrations; tenant context applied separately to each session.
    with engine.connect() as conn:
        org_ids = conn.execute(text("SELECT organization_id FROM marketplace_connections WHERE marketplace='WB' AND enabled=true ORDER BY organization_id")).scalars().all()
    for org_id in org_ids:
        if _stop.is_set():
            break
        sync_organization(int(org_id))
        # Service-token-only constructor sync disabled; user-entered rate is persisted in DB.


def _loop():
    # Delay first network activity after boot to avoid competing with other schedulers.
    if _stop.wait(120):
        return
    while not _stop.is_set():
        try:
            _run_cycle()
        except Exception:
            logger.exception('WB_UNIT_ECONOMY_CYCLE_FAILED')
        _stop.wait(6*60*60)


def start_scheduler():
    global _thread
    if _thread is not None and _thread.is_alive():
        return
    _stop.clear()
    _thread = threading.Thread(target=_loop,daemon=True,name='wb-unit-economy-sync')
    _thread.start()
    logger.info('WB_UNIT_ECONOMY_SCHEDULER_STARTED interval_hours=6 startup_delay_seconds=120')


def stop_scheduler():
    _stop.set()
