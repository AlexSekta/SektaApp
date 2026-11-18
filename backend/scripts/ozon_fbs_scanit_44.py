"""Single posting Ozon FBS scanit read; optional idempotent archive save.

Run: python -m backend.scripts.ozon_fbs_scanit_44 0136766041-0010-1
Run: python -m backend.scripts.ozon_fbs_scanit_44 0136766041-0010-1 --save
"""
import argparse
import re
from backend.database import SessionLocal
from backend.auth.tenant import (legacy_sync_organization_id, set_app_db_role,
                                 set_tenant_context, clear_tenant_context, reset_app_db_role)
from backend.services.marketplace_clients import get_ozon_client
from backend.services.ozon_fbs_sticker_monitor_43 import detail_posting, save_identifiers


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('posting_number')
    parser.add_argument('--save', action='store_true', help='Save verified identifiers in PostgreSQL')
    args = parser.parse_args()
    if not re.fullmatch(r'[A-Za-z0-9-]{4,100}', args.posting_number):
        parser.error('Invalid posting number')
    org = legacy_sync_organization_id()
    if org is None:
        raise RuntimeError('No organization configured')
    db = SessionLocal()
    try:
        set_app_db_role(db)
        set_tenant_context(db, org)
        data = detail_posting(get_ozon_client(db), args.posting_number)
        print('OZON_FBS_DETAIL_44', data)
        if args.save:
            if not data['scanit']:
                raise RuntimeError('No scanit returned; DB not changed')
            save_identifiers(db, org, data)
            print('OZON_FBS_SCANIT_SAVED_44 posting=', args.posting_number)
        else:
            print('READ_ONLY: use --save to persist the verified identifier')
    finally:
        db.rollback()
        clear_tenant_context(db)
        reset_app_db_role(db)
        db.close()

if __name__ == '__main__':
    main()
