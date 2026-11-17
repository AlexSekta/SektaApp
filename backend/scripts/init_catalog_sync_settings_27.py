"""Explicit migration for catalog synchronization settings; defaults to dry-run."""
import argparse
from sqlalchemy import text
from backend.database import engine
from backend.models.catalog_sync_setting import CatalogSyncSetting
from backend.auth.tenant import _ensure_app_role


def main():
    p = argparse.ArgumentParser()
    p.add_argument('--apply', action='store_true')
    args = p.parse_args()
    if not args.apply:
        print('DRY RUN: create catalog_sync_settings with FORCE RLS. Scheduler not enabled. No writes.')
        return
    with engine.begin() as conn:
        CatalogSyncSetting.__table__.create(conn, checkfirst=True)
        _ensure_app_role(conn)
        conn.execute(text('ALTER TABLE catalog_sync_settings ENABLE ROW LEVEL SECURITY'))
        conn.execute(text('ALTER TABLE catalog_sync_settings FORCE ROW LEVEL SECURITY'))
        conn.execute(text('DROP POLICY IF EXISTS tenant_isolation ON catalog_sync_settings'))
        conn.execute(text("""CREATE POLICY tenant_isolation ON catalog_sync_settings
            USING (organization_id = NULLIF(current_setting('app.organization_id', true), '')::integer)
            WITH CHECK (organization_id = NULLIF(current_setting('app.organization_id', true), '')::integer)"""))
    print('SCHEMA READY: catalog_sync_settings; RLS/FORCE RLS enabled; scheduler remains inactive')

if __name__ == '__main__':
    main()
