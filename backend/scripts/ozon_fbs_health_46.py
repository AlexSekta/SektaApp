"""Read-only Ozon FBS monitor health, org-scoped, no tokens or PDF bytes."""
from sqlalchemy import text
from backend.database import SessionLocal
from backend.auth.tenant import (legacy_sync_organization_id, set_app_db_role,
    set_tenant_context, clear_tenant_context, reset_app_db_role)


def main():
    org = legacy_sync_organization_id()
    if org is None:
        raise RuntimeError('No organization configured')
    db=SessionLocal()
    try:
        set_app_db_role(db)
        set_tenant_context(db, org)
        summary=db.execute(text('''
          SELECT COUNT(*) AS postings,
                 COUNT(*) FILTER (WHERE NULLIF(scanit,'') IS NOT NULL) AS scanit_saved,
                 COUNT(*) FILTER (WHERE NULLIF(scanit,'') IS NULL) AS missing_scanit,
                 COUNT(*) FILTER (WHERE sticker_pdf IS NOT NULL) AS pdf_saved,
                 COUNT(*) FILTER (WHERE sticker_pdf IS NULL AND label_task_id IS NOT NULL) AS pdf_tasks_pending,
                 COUNT(*) FILTER (WHERE sticker_pdf IS NULL AND label_error IS NOT NULL) AS pdf_errors,
                 MAX(sticker_saved_at) AS last_pdf_saved_at,
                 MAX(last_seen_at) AS latest_posting_seen_at
            FROM ozon_fbs_sticker_archive WHERE organization_id=:org'''), {'org':org}).mappings().one()
        print('OZON_FBS_HEALTH_46', dict(summary))
        statuses=db.execute(text('''SELECT status, COUNT(*) AS total,
             COUNT(*) FILTER (WHERE NULLIF(scanit,'') IS NULL) AS missing_scanit,
             COUNT(*) FILTER (WHERE sticker_pdf IS NOT NULL) AS pdf_saved
             FROM ozon_fbs_sticker_archive WHERE organization_id=:org
             GROUP BY status ORDER BY total DESC'''), {'org':org}).mappings().all()
        for row in statuses:
            print('OZON_FBS_STATUS_46', dict(row))
    finally:
        db.rollback()
        clear_tenant_context(db)
        reset_app_db_role(db)
        db.close()

if __name__=='__main__':
    main()
