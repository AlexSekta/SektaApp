"""Create barcode audit table. Dry-run by default; requires DB backup before --apply."""
import argparse
from sqlalchemy import text
from backend.database import engine
from backend.models.master_product import MasterProduct
from backend.models.product_barcode_change import ProductBarcodeChange
from backend.auth.tenant import _ensure_app_role


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--apply', action='store_true')
    args = parser.parse_args()
    if not args.apply:
        print('DRY RUN: create product_barcode_changes with tenant RLS; no changes')
        return
    with engine.begin() as connection:
        ProductBarcodeChange.__table__.create(connection, checkfirst=True)
        _ensure_app_role(connection)
        connection.execute(text('ALTER TABLE product_barcode_changes ENABLE ROW LEVEL SECURITY'))
        connection.execute(text('ALTER TABLE product_barcode_changes FORCE ROW LEVEL SECURITY'))
        connection.execute(text('DROP POLICY IF EXISTS tenant_isolation ON product_barcode_changes'))
        connection.execute(text('''CREATE POLICY tenant_isolation ON product_barcode_changes
          USING (organization_id = NULLIF(current_setting('app.organization_id', true), '')::integer)
          WITH CHECK (organization_id = NULLIF(current_setting('app.organization_id', true), '')::integer)'''))
        connection.execute(text('GRANT SELECT, INSERT ON product_barcode_changes TO marketplace_app'))
        connection.execute(text('GRANT USAGE, SELECT ON SEQUENCE product_barcode_changes_id_seq TO marketplace_app'))
    print('SCHEMA READY: product_barcode_changes; RLS/FORCE RLS enabled')

if __name__ == '__main__':
    main()
