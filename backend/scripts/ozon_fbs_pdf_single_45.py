"""Single Ozon FBS posting PDF verification/archival.

Commands:
  python -m backend.scripts.ozon_fbs_pdf_single_45 status
  python -m backend.scripts.ozon_fbs_pdf_single_45 create
  python -m backend.scripts.ozon_fbs_pdf_single_45 fetch

No shipment/packing endpoints; only read posting, create/get label task.
"""
import argparse
import hashlib
from pathlib import Path
from sqlalchemy import text
from backend.database import SessionLocal
from backend.auth.tenant import (
    legacy_sync_organization_id, set_app_db_role, set_tenant_context,
    clear_tenant_context, reset_app_db_role,
)
from backend.services.marketplace_clients import get_ozon_client
from backend.services.ozon_fbs_sticker_monitor_43 import (
    detail_posting, save_identifiers, parse_task, parse_task_status,
    download_pdf,
)

POSTING = '0136766041-0010-1'
EXPECTED_SCANIT = 'ii50243803131'


def read_archive(db, org):
    return db.execute(text('''SELECT posting_number, order_number, status, scanit,
                label_task_id, label_task_type, sticker_saved_at, sticker_sha256,
                sticker_pdf IS NOT NULL AS has_pdf
        FROM ozon_fbs_sticker_archive
        WHERE organization_id=:org AND posting_number=:posting'''),
        {'org':org, 'posting':POSTING}).mappings().first()


def call_ok(client, path, payload):
    result = client.post_raw(path, payload)
    status = result.get('status_code')
    if status != 200:
        body = result.get('body')
        error = body.get('error') if isinstance(body, dict) else None
        raise RuntimeError(f'Ozon HTTP {status}, error={str(error)[:60] if error else "unknown"}; no order changes')
    return result.get('body')


def main():
    parser = argparse.ArgumentParser(description='Single Ozon FBS PDF test; never ships or packs an order')
    parser.add_argument('command', choices=('status','create','fetch'))
    parser.add_argument('--output', default='ozon_label_0136766041-0010-1.pdf')
    args = parser.parse_args()
    org = legacy_sync_organization_id()
    if org is None:
        raise RuntimeError('No organization configured')
    db = SessionLocal()
    try:
        set_app_db_role(db)
        set_tenant_context(db, org)
        row = read_archive(db, org)
        if args.command == 'status':
            if not row:
                print('NOT_FOUND_IN_ARCHIVE')
            else:
                print('ARCHIVE', {k: str(row[k]) for k in ('posting_number','order_number','status','scanit','label_task_id','sticker_saved_at','sticker_sha256','has_pdf')})
            return
        client = get_ozon_client(db)
        detail = detail_posting(client, POSTING)
        print('POSTING', POSTING, 'status=',detail['status'],'scanit=',detail['scanit'])
        if detail['scanit'] != EXPECTED_SCANIT:
            raise RuntimeError('scanit mismatch; refused')
        # Ensure validated identity exists independently of PDF availability.
        if not row:
            save_identifiers(db, org, detail)
            row = read_archive(db, org)
        if row['has_pdf']:
            print('PDF_ALREADY_SAVED sha256=', row['sticker_sha256'])
            return
        if args.command == 'create':
            if row['label_task_id']:
                print('EXISTING_TASK',row['label_task_id'],'-- use fetch; no duplicate create')
                return
            # Only label generation: does not mark packing/shipping.
            body = call_ok(client, '/v3/posting/fbs/package-label/create', {'posting_numbers':[POSTING]})
            try:
                task, task_type = parse_task(body)
            except (ValueError, KeyError, TypeError):
                print('UNEXPECTED_TASK_RESPONSE_KEYS',list(body.keys()) if isinstance(body,dict) else type(body).__name__)
                raise
            db.execute(text('''UPDATE ozon_fbs_sticker_archive SET label_task_id=:task,
                label_task_type=:kind, label_requested_at=now(), label_error=NULL,
                label_next_attempt_at=now()
                WHERE organization_id=:org AND posting_number=:posting AND label_task_id IS NULL'''),
                {'task':task,'kind':task_type,'org':org,'posting':POSTING})
            db.commit()
            print('TASK_CREATED',task,'type=',task_type)
            print('NEXT: run fetch to check readiness and save PDF')
            return
        if not row['label_task_id']:
            print('NO_TASK: run create first')
            return
        body = call_ok(client,'/v2/posting/fbs/package-label/get',{'task_id':int(row['label_task_id'])})
        try:
            state, url = parse_task_status(body)
        except ValueError:
            print('UNEXPECTED_GET_RESPONSE_KEYS',list(body.keys()) if isinstance(body,dict) else type(body).__name__)
            raise
        if state != 'completed':
            print('LABEL_NOT_READY task=',row['label_task_id'],'state=',state)
            return
        pdf = download_pdf(url)
        sha = hashlib.sha256(pdf).hexdigest()
        path = Path(args.output)
        if path.exists():
            raise FileExistsError('Output PDF exists; refusing to overwrite')
        path.write_bytes(pdf)
        db.execute(text('''UPDATE ozon_fbs_sticker_archive
          SET sticker_pdf=:pdf, sticker_sha256=:sha, sticker_saved_at=now(),
              label_error=NULL, label_next_attempt_at=NULL
          WHERE organization_id=:org AND posting_number=:posting AND sticker_pdf IS NULL'''),
          {'pdf':pdf,'sha':sha,'org':org,'posting':POSTING})
        db.commit()
        print('PDF_SAVED posting=',POSTING,'scanit=',EXPECTED_SCANIT,'bytes=',len(pdf),'sha256=',sha)
        print('PRINTABLE_FILE',path.resolve())
    finally:
        db.rollback()
        clear_tenant_context(db)
        reset_app_db_role(db)
        db.close()


if __name__=='__main__':
    main()
