from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.orm import Session

from backend.auth.security import require_current_user
from backend.dependencies import get_db
from backend.models.auth import Organization

router = APIRouter(prefix="/settings/organization", tags=["Настройки — Организация"])


@router.put("")
def update_organization_name(
    data: dict,
    request: Request,
    db: Session = Depends(get_db),
):
    user = require_current_user(request)

    if user.role != "OWNER":
        raise HTTPException(403, "Только владелец организации может изменить её название")

    name = str(data.get("name") or "").strip()
    if not name:
        raise HTTPException(400, "Название организации не может быть пустым")
    if len(name) > 200:
        raise HTTPException(400, "Название организации не должно превышать 200 символов")

    organization = (
        db.query(Organization)
        .filter(Organization.id == user.organization_id)
        .first()
    )
    if organization is None:
        raise HTTPException(404, "Организация не найдена")

    organization.name = name
    db.commit()
    db.refresh(organization)

    return {
        "status": "ok",
        "organization": {
            "id": organization.id,
            "name": organization.name,
        },
    }
