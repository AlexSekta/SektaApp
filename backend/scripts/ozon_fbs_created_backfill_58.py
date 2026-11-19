"""Manual, read-only Ozon FBS date backfill. Never changes remote postings or labels.

Commands:
  python -m backend.scripts.ozon_fbs_created_backfill_58 preview
  python -m backend.scripts.ozon_fbs_created_backfill_58 run --limit 3 --gap 3
  python -m backend.scripts.ozon_fbs_created_backfill_58 status

Only updates archive.ozon_created_at from verified /v3/posting/fbs/get result.in_process_at.
"""
import argparse
import time
from datetime import datetime, timezone
from sqlalchemy import text
from backend.auth.tenant import tenant_session
from backend.database import engine
from backend.services.marketplace_clients import get_ozon_client

ORG = 2


def parse_date(value):
    if not isinstance(value, str) or not value.strip():
        return None
    try:
        dt = datetime.fromisoformat(value.strip().replace('Z', '+00:00'))
    except ValueError:
        return None
    return dt.astimezone(timezone.utc) if dt.tzinfo is not None else None


def extract_date(body, expected):
    if not isinstance(body, dict):
        raise ValueError('invalid response body')
    result = body.get('result') if isinstance(body.get('result'), dict) else body
    if str(result.get('posting_number') or '') != expected:
        raise ValueError('posting mismatch')
    dt = parse_date(result.get('in_process_at'))
    if dt is None:
        raise ValueError('missing/invalid in_process_at')
    return dt


def ensure_schema():
    # Run only for explicit `run`; no modifications from preview/status.
    with engine.begin() as conn:
        conn.execute(text('''CREATE TABLE IF NOT EXISTS ozon_fbs_created_backfill_58 (
            organization_id INTEGER NOT NULL,
            posting_number VARCHAR(100) NOT NULL,
            attempts INTEGER NOT NULL DEFAULT 0,
            state VARCHAR(24) NOT NULL DEFAULT 'retry',
            last_error VARCHAR(160),
            next_attempt_at TIMESTAMPTZ,
            updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            PRIMARY KEY(organization_id, posting_number)
        )'''))
        conn.execute(text('GRANT SELECT,INSERT,UPDATE,DELETE ON ozon_fbs_created_backfill_58 TO marketplace_app'))
        conn.execute(text('ALTER TABLE ozon_fbs_created_backfill_58 ENABLE ROW LEVEL SECURITY'))
        conn.execute(text('ALTER TABLE ozon_fbs_created_backfill_58 FORCE ROW LEVEL SECURITY'))
        conn.execute(text('DROP POLICY IF EXISTS tenant_isolation ON ozon_fbs_created_backfill_58'))
        conn.execute(text('''CREATE POLICY tenant_isolation ON ozon_fbs_created_backfill_58
          USING (organization_id = NULLIF(current_setting('app.organization_id',true),'')::integer)
          WITH CHECK (organization_id = NULLIF(current_setting('app.organization_id',true),'')::integer)'''))


def pending_count(db):
    return db.execute(text('''SELECT count(*) FROM ozon_fbs_sticker_archive
        WHERE organization_id=:org AND ozon_created_at IS NULL'''), {'org': ORG}).scalar()


def total_count(db):
    return db.execute(text('''SELECT count(*) FROM ozon_fbs_sticker_archive
        WHERE organization_id=:org'''), {'org': ORG}).scalar()


def candidates(db, limit):
    return db.execute(text('''SELECT a.posting_number FROM ozon_fbs_sticker_archive a
        LEFT JOIN ozon_fbs_created_backfill_58 b
          ON b.organization_id=a.organization_id AND b.posting_number=a.posting_number
        WHERE a.organization_id=:org AND a.ozon_created_at IS NULL
          AND (b.next_attempt_at IS NULL OR b.next_attempt_at<=now())
          AND (b.attempts IS NULL OR b.attempts<5)
        ORDER BY a.first_seen_at DESC, a.posting_number
        LIMIT :lim'''), {'org': ORG, 'lim': limit}).scalars().all()


def record_issue(db, number, reason, delay_minutes):
    db.execute(text('''INSERT INTO ozon_fbs_created_backfill_58
           (organization_id,posting_number,attempts,state,last_error,next_attempt_at)
           VALUES (:org,:no,1,'retry',:error,now()+make_interval(mins => :delay))
           ON CONFLICT (organization_id,posting_number) DO UPDATE SET
             attempts=ozon_fbs_created_backfill_58.attempts+1,
             last_error=EXCLUDED.last_error,
             next_attempt_at=EXCLUDED.next_attempt_at,
             updated_at=now()'''),
        {'org': ORG, 'no': number, 'error': reason[:160], 'delay': delay_minutes})
    db.commit()


def save_date(db, number, dt):
    result = db.execute(text('''UPDATE ozon_fbs_sticker_archive SET ozon_created_at=:created
        WHERE organization_id=:org AND posting_number=:no AND ozon_created_at IS NULL'''),
        {'created': dt, 'org': ORG, 'no': number})
    db.execute(text('''DELETE FROM ozon_fbs_created_backfill_58
        WHERE organization_id=:org AND posting_number=:no'''), {'org': ORG, 'no': number})
    db.commit()
    return result.rowcount


def run(db, limit, gap):
    client = get_ozon_client(db)
    numbers = candidates(db, limit)
    print('BACKFILL58_START selected=', len(numbers), 'gap=', gap, flush=True)
    for index, number in enumerate(numbers, 1):
        try:
            reply = client.post_raw('/v3/posting/fbs/get', {
                'posting_number': number,
                'with': {'barcodes': False, 'analytics_data': False, 'financial_data': False},
            })
            code = reply.get('status_code')
            if code != 200:
                delay = 30 if code == 429 else 10 if code in (500, 502, 503, 504) else 1440
                record_issue(db, number, 'HTTP ' + str(code), delay)
                print('BACKFILL58_ITEM', index, number, 'retry', 'http=' + str(code), flush=True)
                if code == 429:
                    print('BACKFILL58_STOP rate_limited', flush=True)
                    break
            else:
                dt = extract_date(reply.get('body'), number)
                updated = save_date(db, number, dt)
                print('BACKFILL58_ITEM', index, number, 'saved' if updated else 'already_saved',
                      dt.isoformat(), flush=True)
        except Exception as exc:
            db.rollback()
            record_issue(db, number, type(exc).__name__, 30)
            print('BACKFILL58_ITEM', index, number, 'retry', type(exc).__name__, flush=True)
            if not isinstance(exc, ValueError):
                print('BACKFILL58_STOP api_or_connection_problem', flush=True)
                break
        if index < len(numbers):
            time.sleep(gap)
    print('BACKFILL58_REMAINING', pending_count(db), flush=True)


def main():
    p = argparse.ArgumentParser(description='Backfill missing Ozon FBS in_process_at without labels or status changes')
    p.add_argument('command', choices=['preview', 'run', 'status'])
    p.add_argument('--limit', type=int, default=10)
    p.add_argument('--gap', type=float, default=3.0)
    args = p.parse_args()
    if args.command == 'run':
        if not 1 <= args.limit <= 100:
            p.error('--limit must be 1..100')
        if args.gap < 3:
            p.error('--gap must be >=3 seconds')
        ensure_schema()
    with tenant_session(ORG) as db:
        print('BACKFILL58', 'total=', total_count(db), 'missing=', pending_count(db))
        if args.command == 'run':
            run(db, args.limit, args.gap)
        elif args.command == 'status':
            has_table = db.execute(text("SELECT to_regclass('ozon_fbs_created_backfill_58')")).scalar()
            if has_table:
                rows = db.execute(text('''SELECT attempts,COUNT(*) AS total
                    FROM ozon_fbs_created_backfill_58 WHERE organization_id=:org
                    GROUP BY attempts ORDER BY attempts'''), {'org': ORG}).all()
                print('BACKFILL58_RETRIES', list(rows))
        db.rollback()


if __name__ == '__main__':
    main()
