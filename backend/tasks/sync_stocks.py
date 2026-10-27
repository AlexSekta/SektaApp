from backend.database import SessionLocal
from backend.auth.tenant import clear_tenant_context, legacy_sync_organization_id, set_tenant_context, set_app_db_role, reset_app_db_role
from backend.logging_config import get_logger
from backend.services.stock_service import sync_all_stocks

logger = get_logger("stock_sync")

def main():
    logger.info("SYNC_START | source=scheduled")
    organization_id = legacy_sync_organization_id()
    if organization_id is None:
        logger.info("SYNC_SKIPPED_NO_ORGANIZATION")
        return
    db = SessionLocal()
    try:
        set_app_db_role(db)
        set_tenant_context(db, organization_id)
        result = sync_all_stocks(db)
        logger.info("WB_SYNC_OK | saved=%s", result.get("wb", 0))
        logger.info("OZON_FBS_SYNC_OK | saved=%s", result.get("ozon_fbs", 0))
        logger.info("OZON_FBO_SYNC_OK | saved=%s", result.get("ozon_fbo", 0))
        logger.info("SYNC_FINISH | total=%s", result.get("total", 0))
    except Exception:
        db.rollback(); logger.exception("SYNC_FAILED")
    finally:
        clear_tenant_context(db); reset_app_db_role(db); db.close()

if __name__ == "__main__":
    main()
