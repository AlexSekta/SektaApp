"""Patch 21: explicit administrative migration. Dry run is the default."""
import argparse
from sqlalchemy import text
from backend.database import engine
from backend.models.master_product import MasterProduct  # noqa: F401
from backend.models.marketplace_product_snapshot import MarketplaceProductSnapshot, MarketplaceProductSnapshotChange
from backend.auth.tenant import _ensure_app_role


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--apply', action='store_true')
    args = parser.parse_args()
    if not args.apply:
        print('DRY RUN: add nullable master_products.internal_name and create marketplace_product_snapshots + marketplace_product_snapshot_changes with tenant FORCE RLS. No writes.')
        return
    with engine.begin() as conn:
        conn.execute(text('ALTER TABLE master_products ADD COLUMN IF NOT EXISTS internal_name TEXT'))
        MarketplaceProductSnapshot.__table__.create(conn, checkfirst=True)
        MarketplaceProductSnapshotChange.__table__.create(conn, checkfirst=True)
        _ensure_app_role(conn)
        for table in ('marketplace_product_snapshots', 'marketplace_product_snapshot_changes'):
            conn.execute(text(f'ALTER TABLE {table} ENABLE ROW LEVEL SECURITY'))
            conn.execute(text(f'ALTER TABLE {table} FORCE ROW LEVEL SECURITY'))
            conn.execute(text(f'DROP POLICY IF EXISTS tenant_isolation ON {table}'))
            conn.execute(text(f'''CREATE POLICY tenant_isolation ON {table}
                USING (organization_id = NULLIF(current_setting('app.organization_id', true), '')::integer)
                WITH CHECK (organization_id = NULLIF(current_setting('app.organization_id', true), '')::integer)'''))
    print('SCHEMA READY: internal_name, marketplace_product_snapshots, marketplace_product_snapshot_changes; RLS/FORCE RLS enabled')


if __name__ == '__main__':
    main()
