"""Incremental WB Sales Funnel daily backfill. Run from project root.

Example:
  python -m backend.scripts.wb_sales_backfill --org 2 --from 2026-09-01 --to 2026-10-21

Existing loaded days are skipped. A successful day commits before the next API call.
"""
import argparse
import sys
import time
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal

from fastapi import HTTPException
from sqlalchemy.exc import SQLAlchemyError

from backend.auth.tenant import tenant_session
from backend.models.wb_sales_daily import WBSalesDaily
from backend.api.wb_sales_daily import fetch_one_day


def arguments():
    parser = argparse.ArgumentParser(description='Историческая загрузка продаж WB по дням')
    parser.add_argument('--org', type=int, required=True, help='ID организации')
    parser.add_argument('--from', dest='start', type=date.fromisoformat, default=date(2026, 9, 1))
    parser.add_argument('--to', dest='end', type=date.fromisoformat, default=date(2026, 10, 21))
    parser.add_argument('--interval', type=int, default=30, help='Пауза между запросами WB, секунды (минимум 30)')
    parser.add_argument('--force', action='store_true', help='Повторно загрузить уже сохранённые дни')
    args = parser.parse_args()
    if args.org <= 0 or args.start > args.end or args.end >= date.today() or args.interval < 30:
        parser.error('Требуются положительный ID, корректный завершённый период и интервал >= 30 секунд')
    if (args.end - args.start).days > 364:
        parser.error('Период слишком длинный')
    return args


def main():
    args = arguments()
    days = [args.start + timedelta(days=i) for i in range((args.end - args.start).days + 1)]
    print(f'WB: организация {args.org}, период {args.start} — {args.end}, дней {len(days)}', flush=True)
    print('Важно: дату каждого дня сохраняем отдельно; Ctrl+C безопасен между днями.', flush=True)
    loaded = 0
    skipped = 0
    last_request_time = None
    for index, day in enumerate(days, 1):
        try:
            with tenant_session(args.org) as db:
                current = db.query(WBSalesDaily).filter_by(organization_id=args.org, sale_date=day).one_or_none()
                if current is not None and not args.force:
                    skipped += 1
                    print(f'[{index}/{len(days)}] {day}: уже загружено — пропуск', flush=True)
                    continue

                if last_request_time is not None:
                    wait = args.interval - (time.monotonic() - last_request_time)
                    if wait > 0:
                        print(f'Пауза перед WB API: {wait:.0f} с', flush=True)
                        time.sleep(wait)
                last_request_time = time.monotonic()
                totals, products = fetch_one_day(db, day)
                if current is None:
                    current = WBSalesDaily(organization_id=args.org, sale_date=day)
                    db.add(current)
                current.order_count = totals['orderCount']
                current.order_sum = totals['orderSum']
                current.cancel_count = totals['cancelCount']
                current.cancel_sum = totals['cancelSum']
                current.products_count = products
                current.synced_at = datetime.now(timezone.utc).replace(tzinfo=None)
                db.commit()
                loaded += 1
                print(f'[{index}/{len(days)}] {day}: сохранено, карточек {products}, '
                      f'заказано {current.order_count}, сумма {current.order_sum} руб., '
                      f'отмен {current.cancel_count}', flush=True)
        except KeyboardInterrupt:
            print('\nОстановлено пользователем. Повторный запуск продолжит с незагруженных дней.', flush=True)
            return 130
        except HTTPException as exc:
            print(f'ОШИБКА WB за {day}: HTTP {exc.status_code}: {exc.detail}', file=sys.stderr, flush=True)
            print('Уже сохранённые дни остаются в БД. Повторите команду после устранения причины.', file=sys.stderr)
            return 1
        except (SQLAlchemyError, ValueError, RuntimeError) as exc:
            print(f'ОШИБКА за {day}: {type(exc).__name__}: {exc}', file=sys.stderr, flush=True)
            return 1
    print(f'Готово: новых/обновлённых дней {loaded}; пропущено {skipped}; всего {len(days)}.', flush=True)
    return 0


if __name__ == '__main__':
    sys.exit(main())
