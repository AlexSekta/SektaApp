"""Read-only summary for patch 43. Run: python -m backend.scripts.ozon_fbs_sticker_status_43"""
from sqlalchemy import text
from backend.database import SessionLocal
from backend.auth.tenant import set_app_db_role,set_tenant_context,clear_tenant_context,reset_app_db_role,legacy_sync_organization_id

def main():
    org=legacy_sync_organization_id()
    if org is None:
        raise RuntimeError('No organization configured')
    db=SessionLocal()
    try:
        set_app_db_role(db)
        set_tenant_context(db,org)
        summary=db.execute(text('''SELECT COUNT(*) AS postings,
          COUNT(*) FILTER (WHERE NULLIF(scanit,'') IS NOT NULL) AS scanit_saved,
          COUNT(*) FILTER (WHERE NULLIF(upper_barcode,'') IS NOT NULL) AS upper_barcodes_saved,
          COUNT(*) FILTER (WHERE sticker_pdf IS NOT NULL) AS stickers_saved,
          COUNT(*) FILTER (WHERE label_task_id IS NOT NULL AND sticker_pdf IS NULL) AS pending_tasks,
          COUNT(*) FILTER (WHERE status='awaiting_deliver' AND sticker_pdf IS NULL) AS ready_without_sticker,
          COUNT(*) FILTER (WHERE label_error IS NOT NULL AND sticker_pdf IS NULL) AS retries
          FROM ozon_fbs_sticker_archive WHERE organization_id=:org'''),{'org':org}).mappings().first()
        print('OZON_FBS_MONITOR_SUMMARY', dict(summary))
        rows=db.execute(text('''SELECT posting_number,order_number,status,scanit,upper_barcode,lower_barcode,
          sticker_saved_at,sticker_sha256,label_error
          FROM ozon_fbs_sticker_archive WHERE organization_id=:org
          ORDER BY last_seen_at DESC LIMIT 10'''),{'org':org}).mappings().all()
        for row in rows:
            print('OZON_FBS_MONITOR_ROW',dict(row))
    finally:
        db.rollback()
        clear_tenant_context(db)
        reset_app_db_role(db)
        db.close()

if __name__=='__main__':
    main()
