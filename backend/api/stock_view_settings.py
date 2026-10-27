"""Настройки отображения остатков организации. Не управляет синхронизацией."""
from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel
from sqlalchemy import text
from sqlalchemy.orm import Session
from backend.dependencies import get_db
from backend.auth.security import require_current_user

router = APIRouter(prefix='/settings/stock-view', tags=['Настройки — Отображение остатков'])

class StockViewConfig(BaseModel):
    fbs: bool
    fbo: bool
    wb: bool
    ozon: bool
    yandex: bool

def get_org(db: Session):
    oid = db.execute(text("SELECT NULLIF(current_setting('app.organization_id', true), '')::integer")).scalar()
    if oid is None:
        raise HTTPException(401, 'Не определена организация')
    return oid

@router.get('')
def get_settings(request: Request, db: Session = Depends(get_db)):
    require_current_user(request)
    row = db.execute(text('SELECT fbs,fbo,wb,ozon,yandex FROM organization_stock_view WHERE organization_id=:oid'), {'oid':get_org(db)}).mappings().first()
    return dict(row) if row else {'fbs':True,'fbo':True,'wb':True,'ozon':True,'yandex':True}

@router.put('')
def save_settings(data: StockViewConfig, request: Request, db: Session = Depends(get_db)):
    user = require_current_user(request)
    if user.role != 'OWNER':
        raise HTTPException(403, 'Только владелец организации может изменять настройки отображения')
    if not data.fbs and not data.fbo:
        raise HTTPException(422, 'Выберите хотя бы одну модель работы: FBS или FBO')
    if not any((data.wb,data.ozon,data.yandex)):
        raise HTTPException(422, 'Выберите хотя бы один маркетплейс')
    values = data.model_dump()
    values['oid'] = get_org(db)
    db.execute(text('''INSERT INTO organization_stock_view (organization_id,fbs,fbo,wb,ozon,yandex)
       VALUES (:oid,:fbs,:fbo,:wb,:ozon,:yandex)
       ON CONFLICT (organization_id) DO UPDATE SET
       fbs=EXCLUDED.fbs,fbo=EXCLUDED.fbo,wb=EXCLUDED.wb,ozon=EXCLUDED.ozon,yandex=EXCLUDED.yandex'''), values)
    db.commit()
    return data.model_dump()
