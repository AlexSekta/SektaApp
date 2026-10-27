"""Historical Yandex sales import (run while uvicorn is stopped)."""
import argparse
from datetime import date, timedelta
from backend.database import SessionLocal
from backend.models.auth import Organization  # noqa: F401
from backend.auth.tenant import legacy_sync_organization_id, set_app_db_role, set_tenant_context, clear_tenant_context, reset_app_db_role
from backend.services.yandex_sales_order_sync import ensure_yandex_sales_tables, sync_yandex_sales_day

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--from-day', required=True, type=date.fromisoformat)
    parser.add_argument('--to-day', required=True, type=date.fromisoformat)
    args = parser.parse_args()
    if args.to_day < args.from_day or (args.to_day-args.from_day).days > 90:
        parser.error('Allowed range: 1–91 days')
    ensure_yandex_sales_tables()
    org = legacy_sync_organization_id()
    if org is None:
        parser.error('No organization configured')
    current = args.from_day
    while current <= args.to_day:
        db = SessionLocal()
        try:
            set_app_db_role(db)
            set_tenant_context(db, org)
            result = sync_yandex_sales_day(db, org, current)
            print(f'OK {current}: {result["orders"]} orders, {result["lines"]} lines, {result["units"]} units',flush=True)
        finally:
            clear_tenant_context(db)
            reset_app_db_role(db)
            db.close()
        current += timedelta(days=1)

if __name__ == '__main__':
    main()
