"""Backfill known delivered events from posting history and returns by event date.
Run with uvicorn stopped. Does NOT invent missing cancellation timestamps.
"""
import argparse
from datetime import date, timedelta
from backend.database import SessionLocal
from backend.models.auth import Organization  # mapper registration
from backend.auth.tenant import legacy_sync_organization_id,set_app_db_role,set_tenant_context,clear_tenant_context,reset_app_db_role
from backend.services.ozon_event_sync import ensure_event_tables,sync_returns_day,sync_posting_events_window


def main():
    ap=argparse.ArgumentParser()
    ap.add_argument('--from-day',type=date.fromisoformat,required=True)
    ap.add_argument('--to-day',type=date.fromisoformat,required=True)
    ap.add_argument('--orders-from-day',type=date.fromisoformat,default=None,
                    help='Oldest posting date to scan for deliveries; defaults to from-day')
    args=ap.parse_args()
    if args.to_day<args.from_day or (args.to_day-args.from_day).days>90:
        ap.error('Select 1–91 days')
    ensure_event_tables()
    org=legacy_sync_organization_id()
    if org is None: ap.error('Organization missing')
    db=SessionLocal()
    try:
        set_app_db_role(db);set_tenant_context(db,org)
        order_from=args.orders_from_day or args.from_day
        if order_from>args.to_day: ap.error('--orders-from-day > to-day')
        # Split listing windows into 7-day slices for API pagination and memory safety.
        day=order_from
        while day<=args.to_day:
            end=min(day+timedelta(days=6),args.to_day)
            result=sync_posting_events_window(db,org,day,end)
            print(f'POSTINGS {day}..{end}: {result}',flush=True)
            day=end+timedelta(days=1)
        day=args.from_day
        while day<=args.to_day:
            try:
                result=sync_returns_day(db,org,day)
                print(f'RETURNS {day}: {result}',flush=True)
            except Exception as e:
                db.rollback()
                print(f'RETURNS ERROR {day}: {type(e).__name__}: {e}',flush=True)
                raise
            day+=timedelta(days=1)
    finally:
        clear_tenant_context(db);reset_app_db_role(db);db.close()

if __name__=='__main__':main()
