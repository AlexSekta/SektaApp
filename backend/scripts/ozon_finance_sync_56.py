"""Manual, resumable financial Ozon loader. Use only after running sql/ozon_finance_56.sql."""
import argparse
import json
from datetime import date
from backend.services.ozon_finance_56 import sync_range


def main():
    p = argparse.ArgumentParser()
    p.add_argument('--organization-id', required=True, type=int)
    p.add_argument('--from-date', required=True)
    p.add_argument('--to-date', required=True)
    p.add_argument('--max-pages-per-day', default=100, type=int)
    p.add_argument('--delay', default=2.0, type=float)
    a = p.parse_args()
    start, end = date.fromisoformat(a.from_date),date.fromisoformat(a.to_date)
    if a.organization_id < 1 or end < start or (end-start).days > 31:
        p.error('Range must be 1..32 days, organization positive')
    if not (1 <= a.max_pages_per_day <= 500) or a.delay < 2:
        p.error('Pages 1..500 and delay >=2 seconds')
    print(json.dumps(sync_range(a.organization_id,start,end,a.max_pages_per_day,a.delay),ensure_ascii=False,indent=2,default=str))

if __name__ == '__main__':
    main()
