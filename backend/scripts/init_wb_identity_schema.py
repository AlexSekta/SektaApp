"""Explicit, idempotent schema installation. Execute only after a DB backup.
python -m backend.scripts.init_wb_identity_schema --apply
Never modifies existing product, stock or analytics tables.
"""
import argparse
from sqlalchemy import text
from backend.database import engine
from backend.models.wb_identity import WBIdentityReview, WBIdentityLink
from backend.auth.tenant import _ensure_app_role

def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--apply', action='store_true')
    args=parser.parse_args()
    if not args.apply:
        print('DRY RUN: would create wb_identity_reviews, wb_identity_links with tenant RLS; no existing data changed')
        return
    with engine.begin() as conn:
        for model in (WBIdentityReview, WBIdentityLink):
            model.__table__.create(bind=conn, checkfirst=True)
        _ensure_app_role(conn)
        for name in ('wb_identity_reviews', 'wb_identity_links'):
            conn.execute(text(f'ALTER TABLE {name} ENABLE ROW LEVEL SECURITY'))
            conn.execute(text(f'ALTER TABLE {name} FORCE ROW LEVEL SECURITY'))
            conn.execute(text(f'DROP POLICY IF EXISTS tenant_isolation ON {name}'))
            conn.execute(text(f"""CREATE POLICY tenant_isolation ON {name}
                USING (organization_id = NULLIF(current_setting('app.organization_id', true), '')::integer)
                WITH CHECK (organization_id = NULLIF(current_setting('app.organization_id', true), '')::integer)"""))
    print('SCHEMA READY: wb_identity_reviews + wb_identity_links; RLS enabled')

if __name__ == '__main__': main()
