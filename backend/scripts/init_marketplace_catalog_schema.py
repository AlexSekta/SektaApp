"""Only creates new table; backup PostgreSQL before --apply."""
import argparse
from sqlalchemy import text
from backend.database import engine
from backend.models.marketplace_catalog_card import MarketplaceCatalogCard
from backend.models.master_product import MasterProduct  # resolve FK table for create()
from backend.auth.tenant import _ensure_app_role

def main():
    p = argparse.ArgumentParser()
    p.add_argument('--apply', action='store_true')
    args = p.parse_args()
    if not args.apply:
        print('DRY RUN: create marketplace_catalog_cards with tenant RLS. No current data changed.')
        return
    with engine.begin() as conn:
        MarketplaceCatalogCard.__table__.create(conn, checkfirst=True)
        _ensure_app_role(conn)
        conn.execute(text('ALTER TABLE marketplace_catalog_cards ENABLE ROW LEVEL SECURITY'))
        conn.execute(text('ALTER TABLE marketplace_catalog_cards FORCE ROW LEVEL SECURITY'))
        conn.execute(text('DROP POLICY IF EXISTS tenant_isolation ON marketplace_catalog_cards'))
        conn.execute(text('''CREATE POLICY tenant_isolation ON marketplace_catalog_cards
            USING (organization_id = NULLIF(current_setting('app.organization_id', true), '')::integer)
            WITH CHECK (organization_id = NULLIF(current_setting('app.organization_id', true), '')::integer)'''))
    print('SCHEMA READY: marketplace_catalog_cards; RLS enabled')

if __name__ == '__main__': main()
