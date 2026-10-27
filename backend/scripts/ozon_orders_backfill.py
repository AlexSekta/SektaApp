"""Manual historical backfill, no CSV imports. From project root:
python -m backend.scripts.ozon_orders_backfill --from-day 2026-10-10 --to-day 2026-10-13
"""
import argparse
from datetime import date, timedelta
from backend.database import SessionLocal
from backend.models.auth import Organization  # mapper registration
from backend.auth.tenant import (legacy_sync_organization_id, set_app_db_role,
    set_tenant_context, clear_tenant_context, reset_app_db_role)
from backend.services.ozon_order_sync import sync_day, ensure_ozon_order_tables


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--from-day', required=True, type=date.fromisoformat)
    parser.add_argument('--to-day', required=True, type=date.fromisoformat)
    args = parser.parse_args()
    if args.to_day < args.from_day or (args.to_day - args.from_day).days > 90:
        parser.error('Date range must be 1–91 days')
    ensure_ozon_order_tables()
    org = legacy_sync_organization_id()
    if org is None:
        parser.error('No organization configured')
    current = args.from_day
    while current <= args.to_day:
        db = SessionLocal()
        try:
            set_app_db_role(db)
            set_tenant_context(db, org)
            result = sync_day(db, org, current)
            print(f"OK {current}: {result['postings']} postings, {result['lines']} lines")
        except Exception as exc:
            db.rollback()
            print(f'ERROR {current}: {type(exc).__name__}: {exc}')
            raise
        finally:
            clear_tenant_context(db)
            reset_app_db_role(db)
            db.close()
        current += timedelta(days=1)


if __name__ == '__main__':
    main()
