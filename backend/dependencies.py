from fastapi import Request
from backend.database import SessionLocal
from backend.auth.tenant import (
    set_app_db_role,
    reset_app_db_role,
    set_tenant_context,
    clear_tenant_context,
)

def get_db(request: Request):
    db = SessionLocal()
    organization_id = getattr(request.state, "organization_id", None)
    try:
        set_app_db_role(db)
        if organization_id is not None:
            set_tenant_context(db, organization_id)
        yield db
    finally:
        if organization_id is not None:
            clear_tenant_context(db)
        reset_app_db_role(db)
        db.close()
