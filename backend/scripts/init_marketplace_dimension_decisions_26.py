"""Add append-only marketplace dimensions decisions. Default dry-run."""
import argparse
from sqlalchemy import text
from backend.database import engine
from backend.auth.tenant import _ensure_app_role
from backend.models.marketplace_dimension_decision import MarketplaceDimensionDecision


def main():
    p = argparse.ArgumentParser()
    p.add_argument('--apply', action='store_true')
    args = p.parse_args()
    if not args.apply:
        print('DRY RUN: create marketplace_dimension_decisions with tenant FORCE RLS. No writes.')
        return
    with engine.begin() as conn:
        MarketplaceDimensionDecision.__table__.create(conn, checkfirst=True)
        _ensure_app_role(conn)
        table = 'marketplace_dimension_decisions'
        conn.execute(text(f'ALTER TABLE {table} ENABLE ROW LEVEL SECURITY'))
        conn.execute(text(f'ALTER TABLE {table} FORCE ROW LEVEL SECURITY'))
        conn.execute(text(f'DROP POLICY IF EXISTS tenant_isolation ON {table}'))
        conn.execute(text(f'''CREATE POLICY tenant_isolation ON {table}
            USING (organization_id = NULLIF(current_setting('app.organization_id', true), '')::integer)
            WITH CHECK (organization_id = NULLIF(current_setting('app.organization_id', true), '')::integer)'''))
    print('SCHEMA READY: marketplace_dimension_decisions; RLS/FORCE RLS enabled')


if __name__ == '__main__':
    main()
