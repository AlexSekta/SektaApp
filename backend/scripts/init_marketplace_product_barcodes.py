"""Create the platform-specific barcode table, with tenant isolation. Dry run by default."""
import argparse
from sqlalchemy import text
from backend.database import engine
from backend.models.master_product import MasterProduct  # noqa: F401 — FK registration
from backend.models.marketplace_product_barcode import MarketplaceProductBarcode
from backend.auth.tenant import _ensure_app_role


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--apply', action='store_true')
    args = parser.parse_args()
    if not args.apply:
        print('DRY RUN: create marketplace_product_barcodes; enable FORCE RLS. No writes.')
        return
    with engine.begin() as conn:
        MarketplaceProductBarcode.__table__.create(conn, checkfirst=True)
        _ensure_app_role(conn)
        conn.execute(text('ALTER TABLE marketplace_product_barcodes ENABLE ROW LEVEL SECURITY'))
        conn.execute(text('ALTER TABLE marketplace_product_barcodes FORCE ROW LEVEL SECURITY'))
        conn.execute(text('DROP POLICY IF EXISTS tenant_isolation ON marketplace_product_barcodes'))
        conn.execute(text('''CREATE POLICY tenant_isolation ON marketplace_product_barcodes
            USING (organization_id = NULLIF(current_setting('app.organization_id', true), '')::integer)
            WITH CHECK (organization_id = NULLIF(current_setting('app.organization_id', true), '')::integer)'''))
    print('SCHEMA READY: marketplace_product_barcodes; RLS/FORCE RLS enabled')


if __name__ == '__main__':
    main()
