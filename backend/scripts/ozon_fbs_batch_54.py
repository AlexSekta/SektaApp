"""Explicit, frozen one-time Ozon FBS label batch. Never run automatically.

Usage: python -m backend.scripts.ozon_fbs_batch_54 preview|snapshot|status|run [--batch ID] [--limit N]

Only creates labels after explicit `snapshot` followed by `run --batch ...`.
Creation is never repeated following an ambiguous API response.
"""
import argparse
import os
import time
import uuid
from datetime import datetime, timezone
from sqlalchemy import text
from backend.auth.tenant import tenant_session
from backend.services.marketplace_clients import get_ozon_client
from backend.services import ozon_fbs_sticker_monitor_43 as monitor

ORG = 2
TABLE = 'ozon_fbs_label_batch_54'


def ensure_schema():
    # Schema creation needs owner privileges; this is run only from explicit CLI.
    from backend.database import engine
    with engine.begin() as conn:
        conn.execute(text('''CREATE TABLE IF NOT EXISTS ozon_fbs_label_batch_54 (
            organization_id integer NOT NULL,
            batch_id uuid NOT NULL,
            posting_number varchar(100) NOT NULL,
            captured_at timestamptz NOT NULL DEFAULT now(),
            state varchar(40) NOT NULL DEFAULT 'pending',
            error varchar(200),
            updated_at timestamptz NOT NULL DEFAULT now(),
            PRIMARY KEY (organization_id, batch_id, posting_number)
        )'''))
        conn.execute(text('GRANT SELECT,INSERT,UPDATE,DELETE ON ozon_fbs_label_batch_54 TO marketplace_app'))
        conn.execute(text('ALTER TABLE ozon_fbs_label_batch_54 ENABLE ROW LEVEL SECURITY'))
        conn.execute(text('ALTER TABLE ozon_fbs_label_batch_54 FORCE ROW LEVEL SECURITY'))
        conn.execute(text('DROP POLICY IF EXISTS tenant_isolation ON ozon_fbs_label_batch_54'))
        conn.execute(text('''CREATE POLICY tenant_isolation ON ozon_fbs_label_batch_54
            USING (organization_id = NULLIF(current_setting('app.organization_id', true),'')::integer)
            WITH CHECK (organization_id = NULLIF(current_setting('app.organization_id', true),'')::integer)'''))


def candidates(db):
    return db.execute(text('''SELECT count(*) AS total,
      count(*) FILTER (WHERE a.label_task_id IS NOT NULL) AS known_tasks,
      count(*) FILTER (WHERE a.label_task_id IS NULL AND a.label_requested_at IS NULL) AS need_create,
      count(*) FILTER (WHERE a.label_task_id IS NULL AND a.label_requested_at IS NOT NULL) AS uncertain_create
      FROM ozon_fbs_sticker_archive a
      WHERE a.organization_id=:org AND a.status='awaiting_deliver' AND a.sticker_pdf IS NULL'''), {'org':ORG}).mappings().one()


def snapshot(db):
    batch = str(uuid.uuid4())
    inserted = db.execute(text('''INSERT INTO ozon_fbs_label_batch_54
        (organization_id,batch_id,posting_number,state)
        SELECT :org,cast(:batch as uuid),a.posting_number,
           CASE WHEN a.label_task_id IS NULL AND a.label_requested_at IS NOT NULL
                THEN 'review' ELSE 'pending' END
        FROM ozon_fbs_sticker_archive a
        WHERE a.organization_id=:org AND a.status='awaiting_deliver'
           AND a.sticker_pdf IS NULL
        RETURNING posting_number'''), {'org':ORG,'batch':batch}).all()
    db.commit()
    return batch,len(inserted)


def status(db,batch):
    return db.execute(text('''SELECT state,count(*) as count FROM ozon_fbs_label_batch_54
        WHERE organization_id=:org AND batch_id=cast(:batch as uuid)
        GROUP BY state ORDER BY state'''), {'org':ORG,'batch':batch}).all()


def mark(db,batch,number,state,error=None):
    db.execute(text('''UPDATE ozon_fbs_label_batch_54 SET state=:state,error=:error,updated_at=now()
        WHERE organization_id=:org AND batch_id=cast(:batch as uuid) AND posting_number=:no'''),
        {'state':state,'error':(str(error)[:200] if error else None),'org':ORG,'batch':batch,'no':number})
    db.commit()


def work_one(db,client,batch,number):
    archive = db.execute(text('''SELECT posting_number,status,sticker_pdf IS NOT NULL AS saved,
          label_task_id,label_requested_at
        FROM ozon_fbs_sticker_archive
        WHERE organization_id=:org AND posting_number=:no'''), {'org':ORG,'no':number}).mappings().first()
    if not archive:
        mark(db,batch,number,'skipped','archive missing')
        return 'skipped'
    if archive['saved']:
        mark(db,batch,number,'saved')
        return 'saved'
    task=archive['label_task_id']
    if task is None:
        if archive['status'] != 'awaiting_deliver':
            mark(db,batch,number,'skipped','status changed before creation')
            return 'skipped'
        if archive['label_requested_at'] is not None:
            mark(db,batch,number,'review','old create request without task: must inspect manually')
            return 'review'
        # The archive may lag behind changes made by warehouse staff.  Refresh the
        # live posting status BEFORE any attempt to create a label task.
        try:
            detail = monitor.paced(lambda: client.post_raw(
                '/v3/posting/fbs/get',
                {'posting_number': number,
                 'with': {'barcodes': False, 'analytics_data': False,
                          'financial_data': False}},
            ))
            if detail.get('status_code') != 200:
                raise RuntimeError('get HTTP ' + str(detail.get('status_code')))
            body = detail.get('body') or {}
            posting = body.get('result')
            if not isinstance(posting, dict) or posting.get('posting_number') != number:
                raise ValueError('unexpected posting details: cannot verify status')
            live_status = posting.get('status')
            if not isinstance(live_status, str) or not live_status:
                raise ValueError('missing live status')
        except Exception as exc:
            db.rollback()
            mark(db, batch, number, 'review',
                 'live status check failed (' + type(exc).__name__ + '); no create attempted')
            return 'review'
        if live_status != 'awaiting_deliver':
            mark(db, batch, number, 'skipped', 'live status ' + live_status)
            return 'skipped'
        # This minimizes, but cannot eliminate, the race between live status
        # verification and the Ozon create request.
        # Persist one-way claim before network call, independent of concurrent workers.
        claimed=db.execute(text('''UPDATE ozon_fbs_sticker_archive
          SET label_requested_at=now(),label_error='batch54_create_requested_unconfirmed'
          WHERE organization_id=:org AND posting_number=:no AND sticker_pdf IS NULL
            AND status='awaiting_deliver' AND label_task_id IS NULL AND label_requested_at IS NULL
          RETURNING posting_number'''), {'org':ORG,'no':number}).first()
        if not claimed:
            db.rollback()
            mark(db,batch,number,'review','claim not acquired')
            return 'review'
        mark(db,batch,number,'creating') # commits claim before network request
        try:
            reply=monitor.paced(lambda:client.post_raw('/v3/posting/fbs/package-label/create', {'posting_numbers':[number]}))
            if reply.get('status_code')!=200:
                raise RuntimeError('create HTTP '+str(reply.get('status_code')))
            task,task_type=monitor.parse_task(reply.get('body'))
        except Exception as e:
            db.rollback()
            mark(db,batch,number,'review',type(e).__name__+': uncertain create result; DO NOT retry')
            return 'review'
        db.execute(text('''UPDATE ozon_fbs_sticker_archive
            SET label_task_id=:task,label_task_type=:typ,label_error=NULL,
              label_next_attempt_at=now()+interval '20 seconds'
            WHERE organization_id=:org AND posting_number=:no AND label_task_id IS NULL'''),
            {'org':ORG,'no':number,'task':task,'typ':task_type})
        db.commit()
        mark(db,batch,number,'awaiting_pdf')
        return 'created'
    try:
        monitor.process_one(db,ORG,client,{'posting_number':number,'label_task_id':task,'eligible_create':False})
        saved=db.execute(text('''SELECT sticker_pdf IS NOT NULL FROM ozon_fbs_sticker_archive
                   WHERE organization_id=:org AND posting_number=:no'''),{'org':ORG,'no':number}).scalar()
        mark(db,batch,number,'saved' if saved else 'awaiting_pdf')
        return 'saved' if saved else 'awaiting_pdf'
    except Exception as e:
        db.rollback()
        mark(db,batch,number,'awaiting_pdf',type(e).__name__)
        return 'retry_later'


def run_batch(db,batch,limit,gap):
    exists=db.execute(text('''SELECT count(*) FROM ozon_fbs_label_batch_54
      WHERE organization_id=:org AND batch_id=cast(:batch as uuid)'''), {'org':ORG,'batch':batch}).scalar()
    if not exists:
        raise RuntimeError('Batch not found; run snapshot first')
    client=get_ozon_client(db)
    # Snapshot membership is immutable. Only these orders are processed.
    rows=db.execute(text('''SELECT posting_number,state FROM ozon_fbs_label_batch_54
      WHERE organization_id=:org AND batch_id=cast(:batch as uuid)
        AND state IN ('pending','awaiting_pdf')
      ORDER BY (state='awaiting_pdf') DESC,captured_at,posting_number
      LIMIT :lim'''), {'org':ORG,'batch':batch,'lim':limit}).mappings().all()
    for i,row in enumerate(rows):
        no=row['posting_number']
        result=work_one(db,client,batch,no)
        print('BATCH54_ITEM',no,result,flush=True)
        if i<len(rows)-1: time.sleep(gap)
    print('BATCH54_STATUS',list(status(db,batch)))


def run_all(db, batch, gap=12.0, max_items=725, max_hours=4.0,
            max_open_tasks=5, retry_seconds=60, max_new_reviews=3,
            max_task_attempts=6):
    """Bounded foreground processing of an existing frozen batch; Ctrl+C safe."""
    from backend.database import engine
    # Independent connection holds a PostgreSQL session-level concurrency lock.
    with engine.connect() as lock_conn:
        locked = lock_conn.execute(text(
            'SELECT pg_try_advisory_lock(543054, :org)'), {'org': ORG}).scalar()
        if not locked:
            raise RuntimeError('Batch54 run-all already running for organization')
        try:
            _run_all_locked(db, batch, gap, max_items, max_hours,
                            max_open_tasks, retry_seconds,
                            max_new_reviews, max_task_attempts)
        finally:
            lock_conn.execute(text(
                'SELECT pg_advisory_unlock(543054, :org)'), {'org': ORG})


def _run_all_locked(db, batch, gap, max_items, max_hours,
                    max_open_tasks, retry_seconds,
                    max_new_reviews, max_task_attempts):
    exists = db.execute(text('''SELECT count(*) FROM ozon_fbs_label_batch_54
       WHERE organization_id=:org AND batch_id=cast(:batch as uuid)'''),
       {'org': ORG, 'batch': batch}).scalar()
    if not exists:
        raise RuntimeError('Batch not found; use existing snapshot ID')
    client = get_ozon_client(db)
    deadline = time.monotonic() + max_hours * 3600
    processed = 0
    newly_review = 0
    task_attempts = {}
    stop_reason = 'completed'
    print('BATCH543_START batch=' + batch + ' max_items=' + str(max_items)
          + ' max_hours=' + str(max_hours) + ' gap=' + str(gap)
          + ' open_tasks_cap=' + str(max_open_tasks), flush=True)
    try:
        while processed < max_items and time.monotonic() < deadline:
            open_tasks = db.execute(text('''SELECT count(*)
                FROM ozon_fbs_label_batch_54 WHERE organization_id=:org
                  AND batch_id=cast(:batch as uuid) AND state='awaiting_pdf' '''),
                {'org':ORG,'batch':batch}).scalar()
            pending = db.execute(text('''SELECT count(*)
                FROM ozon_fbs_label_batch_54 WHERE organization_id=:org
                  AND batch_id=cast(:batch as uuid) AND state='pending' '''),
                {'org':ORG,'batch':batch}).scalar()
            if not open_tasks and not pending:
                stop_reason = 'queue_empty'
                break
            allow_new = open_tasks < max_open_tasks
            row = db.execute(text('''SELECT posting_number,state
                 FROM ozon_fbs_label_batch_54
                 WHERE organization_id=:org AND batch_id=cast(:batch as uuid)
                   AND (
                     (state='awaiting_pdf' AND updated_at <= now()
                         - make_interval(secs => :retry))
                     OR (state='pending' AND :allow_new)
                   )
                 ORDER BY CASE WHEN state='awaiting_pdf' THEN 0 ELSE 1 END,
                          captured_at,posting_number LIMIT 1'''),
                 {'org':ORG,'batch':batch,'retry':int(retry_seconds),
                  'allow_new':allow_new}).mappings().first()
            if row is None:
                time.sleep(min(15.0, max(1.0, gap)))
                continue
            no = row['posting_number']
            result = work_one(db, client, batch, no)
            processed += 1
            print('BATCH543_ITEM', processed, no, result, flush=True)
            if result == 'review':
                newly_review += 1
                if newly_review >= max_new_reviews:
                    stop_reason = 'review_limit'
                    break
            if row['state'] == 'awaiting_pdf' and result in ('retry_later','awaiting_pdf'):
                task_attempts[no] = task_attempts.get(no, 0) + 1
                if task_attempts[no] >= max_task_attempts:
                    stop_reason = 'repeated_pdf_failure'
                    print('BATCH543_REPEATED_FAILURE posting=' + no, flush=True)
                    break
            else:
                task_attempts.pop(no, None)
            if processed % 10 == 0:
                print('BATCH543_STATUS', list(status(db, batch)), flush=True)
            if processed < max_items:
                time.sleep(gap)
        else:
            stop_reason = 'item_limit' if processed >= max_items else 'time_limit'
    except KeyboardInterrupt:
        stop_reason = 'interrupted'
    finally:
        print('BATCH543_STOP reason=' + stop_reason + ' processed=' + str(processed)
              + ' newly_review=' + str(newly_review), flush=True)
        print('BATCH543_STATUS', list(status(db,batch)), flush=True)

def main():
    parser=argparse.ArgumentParser(description='Frozen Ozon FBS PDF snapshot; read README before running')
    parser.add_argument('command',choices=['preview','snapshot','status','run','run-all'])
    parser.add_argument('--batch',help='UUID returned by snapshot; required for status/run')
    parser.add_argument('--limit',type=int,default=10,help='Up to 10 orders per manual run')
    parser.add_argument('--gap',type=float,default=10.0,help='Seconds between requests (minimum 10)')
    parser.add_argument('--max-items',type=int,default=725,
                        help='run-all: items processed in this launch (1..2000)')
    parser.add_argument('--max-hours',type=float,default=4.0,
                        help='run-all: running time in hours (0..12)')
    parser.add_argument('--max-open-tasks',type=int,default=5,
                        help='run-all: outstanding PDF tasks (1..10)')
    parser.add_argument('--retry-seconds',type=int,default=60,
                        help='run-all: minimum task retry delay (>=30)')
    args=parser.parse_args()
    if args.command in ('snapshot','run','run-all','status'): ensure_schema()
    with tenant_session(ORG) as db:
        if args.command=='preview':
            print('BATCH54_PREVIEW',dict(candidates(db)))
        elif args.command=='snapshot':
            batch,count=snapshot(db)
            print('BATCH54_SNAPSHOT',batch,'orders',count)
            print('Run manually: python -m backend.scripts.ozon_fbs_batch_54 run --batch',batch)
        elif args.command in ('status','run','run-all'):
            if not args.batch: parser.error('--batch required')
            uuid.UUID(args.batch)
            if args.command=='status': print('BATCH54_STATUS',list(status(db,args.batch)))
            elif args.command == 'run-all':
                if not 1<=args.max_items<=2000: parser.error('--max-items must be 1..2000')
                if not 0<args.max_hours<=12: parser.error('--max-hours must be 0..12')
                if not 1<=args.max_open_tasks<=10: parser.error('--max-open-tasks must be 1..10')
                if args.retry_seconds<30: parser.error('--retry-seconds must be >=30')
                if args.gap<10: parser.error('--gap must be >=10')
                run_all(db,args.batch,gap=args.gap,max_items=args.max_items,
                        max_hours=args.max_hours,max_open_tasks=args.max_open_tasks,
                        retry_seconds=args.retry_seconds)
            else:
                if not 1<=args.limit<=10: parser.error('--limit must be 1..10')
                if args.gap<10: parser.error('--gap must be >= 10 seconds')
                run_batch(db,args.batch,args.limit,args.gap)

if __name__=='__main__': main()
