"""Read-only, tenant-scoped status for existing sales-history workers."""
from datetime import date, timedelta
from fastapi import APIRouter, Depends, Request
from sqlalchemy import text
from sqlalchemy.orm import Session
from backend.dependencies import get_db
from backend.auth.security import require_current_user

router = APIRouter(prefix="/settings", tags=["Синхронизация"])

JOBS = (
    ("wb", "WB", "Wildberries", "wb_sales_history_jobs", "wb_sales_daily"),
    ("yandex", "YANDEX", "Яндекс Маркет", "yandex_sales_history_jobs", "yandex_sales_sync_days"),
    ("ozon_seller", "OZON", "Ozon — цена продавца", "ozon_sales_history_jobs", "ozon_sales_daily"),
    ("ozon_estimate", "OZON", "Ozon — оценка цены реализации", "ozon_order_history_jobs", "ozon_order_sync_days"),
)

@router.get("/sync-status")
def get_sync_status(request: Request, db: Session = Depends(get_db)):
    require_current_user(request)
    # Database tenant identity comes from get_db, never from a client parameter.
    oid = db.execute(text("SELECT NULLIF(current_setting('app.organization_id', true), '')::integer")).scalar()
    connections = db.execute(text("""SELECT marketplace, enabled FROM marketplace_connections
        WHERE organization_id=:oid"""), {"oid": oid}).all()
    enabled = {row[0] for row in connections if row[1]}
    result = []
    for key, mp, label, job_table, data_table in JOBS:
        # Names are fixed server-side constants, never interpolated from user input.
        job = db.execute(text(f"""SELECT next_day, status, last_error, updated_at
            FROM {job_table} WHERE organization_id=:oid"""), {"oid": oid}).mappings().first()
        summary = db.execute(text(f"""SELECT min(sale_date) first_day, max(sale_date) last_day,
            count(*) loaded_days FROM {data_table} WHERE organization_id=:oid"""), {"oid": oid}).mappings().first()
        result.append({
            "key": key, "marketplace": mp, "label": label,
            "connected": mp in enabled,
            "status": job["status"] if job else "not_started",
            "next_day": job["next_day"] if job else None,
            "last_error": job["last_error"] if job else None,
            "updated_at": job["updated_at"] if job else None,
            "first_day": summary["first_day"] if summary else None,
            "last_day": summary["last_day"] if summary else None,
            "loaded_days": summary["loaded_days"] if summary else 0,
        })
    return {"items": result}
