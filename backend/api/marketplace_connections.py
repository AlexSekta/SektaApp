from datetime import datetime
from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.orm import Session
from backend.dependencies import get_db
from backend.auth.security import require_current_user
from backend.models.marketplace_connection import MarketplaceConnection
from backend.services.marketplace_credentials import encrypt_credentials, decrypt_credentials, mask_secret

router = APIRouter(prefix="/settings/marketplaces", tags=["Настройки — Маркетплейсы"])
MARKETPLACES = ("WB", "OZON", "YANDEX")

def _empty():
    return {"enabled": False, "configured": False, "masked": {}, "last_connected_at": None, "last_error": None}

def _serialize(row):
    if not row: return _empty()
    creds = decrypt_credentials(row.credentials_encrypted) if row.credentials_encrypted else {}
    if row.marketplace == "WB":
        masked = {"token": mask_secret(creds.get("token"))}
    elif row.marketplace == "OZON":
        masked = {"client_id": mask_secret(creds.get("client_id")), "api_key": mask_secret(creds.get("api_key"))}
    else:
        masked = {"api_key": mask_secret(creds.get("api_key")), "business_id": creds.get("business_id")}
    return {"enabled": bool(row.enabled), "configured": bool(row.credentials_encrypted), "masked": masked,
            "last_connected_at": row.last_connected_at.isoformat() if row.last_connected_at else None,
            "last_error": row.last_error}

def _rows(db): return {r.marketplace:r for r in db.query(MarketplaceConnection).all()}

@router.get("")
def get_marketplace_settings(request: Request, db: Session = Depends(get_db)):
    user = require_current_user(request)
    if user.role != "OWNER":
        raise HTTPException(403, "Только владелец организации может просматривать API-подключения")
    rows=_rows(db)
    return {"status":"ok","marketplaces":{m:_serialize(rows.get(m)) for m in MARKETPLACES}}

@router.put("")
def update_marketplace_settings(data: dict, request: Request, db: Session = Depends(get_db)):
    user = require_current_user(request)
    if user.role != "OWNER":
        raise HTTPException(403, "Только владелец организации может изменять API-подключения")
    incoming=data.get("marketplaces")
    if not isinstance(incoming,dict): raise HTTPException(400,"Поле marketplaces обязательно")
    rows=_rows(db); org_id=int(request.state.organization_id)
    for marketplace in MARKETPLACES:
        item=incoming.get(marketplace) or {}
        if not isinstance(item,dict): raise HTTPException(400,f"Некорректные настройки {marketplace}")
        row=rows.get(marketplace)
        if row is None:
            row=MarketplaceConnection(organization_id=org_id,marketplace=marketplace,enabled=False)
            db.add(row); db.flush(); rows[marketplace]=row
        row.enabled=bool(item.get("enabled",False)); row.last_error=None; row.updated_at=datetime.utcnow()
        if marketplace=="WB":
            token=str(item.get("token") or "").strip()
            if token: row.credentials_encrypted=encrypt_credentials({"token":token})
        elif marketplace=="OZON":
            client_id=str(item.get("client_id") or "").strip(); api_key=str(item.get("api_key") or "").strip()
            if client_id or api_key:
                if not client_id or not api_key: raise HTTPException(400,"Для Ozon нужно указать Client ID и API-ключ")
                row.credentials_encrypted=encrypt_credentials({"client_id":client_id,"api_key":api_key})
        else:
            api_key=str(item.get("api_key") or "").strip(); business_id=str(item.get("business_id") or "").strip()
            if api_key:
                creds={"api_key":api_key};
                if business_id: creds["business_id"]=business_id
                row.credentials_encrypted=encrypt_credentials(creds)
            elif business_id and row.credentials_encrypted:
                creds=decrypt_credentials(row.credentials_encrypted); creds["business_id"]=business_id; row.credentials_encrypted=encrypt_credentials(creds)
    db.commit(); rows=_rows(db)
    return {"status":"ok","marketplaces":{m:_serialize(rows.get(m)) for m in MARKETPLACES}}
