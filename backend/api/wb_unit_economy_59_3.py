"""WB categories and commissions: DB-only read endpoint."""
from collections import Counter
from decimal import Decimal, InvalidOperation
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from sqlalchemy import text
from pydantic import BaseModel, Field
from typing import Literal
from backend.dependencies import get_db
from backend.models.master_product import MasterProduct
from backend.services.wb_unit_economy_cache_59_4 import get_snapshot, get_option_snapshot

router = APIRouter(prefix='/unit-economy', tags=['Юнит-экономика'])


def _percentage(value):
    try:
        number = Decimal(str(value))
        return float(number) if number.is_finite() and 0 <= number <= 100 else None
    except (TypeError, ValueError, InvalidOperation):
        return None


@router.get('/wb/catalog-tariffs')
def wb_catalog_tariffs(db: Session=Depends(get_db)):
    snapshot = get_snapshot(db)
    option_snapshot = get_option_snapshot(db)
    settings = db.execute(text("SELECT tariff_package_rate FROM unit_economy_settings WHERE marketplace='WB'")).mappings().first()
    option_rate = _percentage(settings['tariff_package_rate']) if settings and settings['tariff_package_rate'] is not None else None
    cards = snapshot['cards'] if snapshot else []
    rates = snapshot['rates'] if snapshot else []
    counts = Counter(str(c.get('vendorCode') or '').strip() for c in cards)
    unique_cards = {str(c.get('vendorCode') or '').strip():c for c in cards if str(c.get('vendorCode') or '').strip()}
    by_subject={}
    duplicate=set()
    for r in rates:
        key=str(r.get('subjectID') or r.get('subjectId') or '').strip()
        if not key: continue
        if key in by_subject: duplicate.add(key)
        by_subject[key]=r
    result=[]
    for p in db.query(MasterProduct).all():
        article=(p.seller_article or '').strip()
        card=unique_cards.get(article) if article and counts[article]==1 else None
        sid=str(card.get('subjectID') or card.get('subjectId') or '').strip() if card else ''
        rate=by_subject.get(sid) if sid and sid not in duplicate else None
        subject=(card.get('subjectName') or '').strip() if card else None
        if not subject and rate: subject=(rate.get('subjectName') or '').strip() or None
        result.append({'product_id':p.id,'matched':bool(card),'subject_id':sid or None,
                       'subject_name':subject,'nm_id':card.get('nmID') if card else None,
                       'commission_fbo':_percentage(rate.get('paidStorageKgvp')) if rate else None,
                       'commission_fbs':_percentage(rate.get('kgvpMarketplace')) if rate else None})
    return {'tariff_package_rate':option_rate,
            'tariff_package_synced_at':option_snapshot['synced_at'].isoformat() if option_snapshot else None,
            'items':result,'cards_count':len(cards),'tariffs_count':len(rates),
            'synced_at':snapshot['synced_at'].isoformat() if snapshot else None,
            'stale':snapshot is None,
            'status':'ready' if snapshot else 'waiting_first_sync'}

class UnitSettingsUpdate(BaseModel):
    marketplace: Literal['WB', 'OZON', 'YANDEX']
    tariff_package_rate: float | None = Field(default=None, ge=0, le=100)
    only_enabled: bool | None = None


@router.get('/settings')
def unit_settings(db: Session = Depends(get_db)):
    settings = db.execute(text('SELECT marketplace, tariff_package_rate, only_enabled FROM unit_economy_settings')).mappings().all()
    statuses = db.execute(text('SELECT product_id, marketplace, status FROM unit_economy_product_status')).mappings().all()
    return {'settings': [dict(r) for r in settings], 'statuses': [dict(r) for r in statuses]}


@router.put('/settings')
def save_unit_settings(payload: UnitSettingsUpdate, db: Session = Depends(get_db)):
    if payload.marketplace != 'WB' and payload.tariff_package_rate is not None:
        raise HTTPException(400, 'Тарифный пакет поддерживается только для WB')
    db.execute(text("""INSERT INTO unit_economy_settings (organization_id,marketplace,tariff_package_rate,only_enabled)
        VALUES (NULLIF(current_setting('app.organization_id',true),'')::integer,:mp,:rate,COALESCE(:only,true))
        ON CONFLICT(organization_id,marketplace) DO UPDATE SET
        tariff_package_rate=COALESCE(:rate,unit_economy_settings.tariff_package_rate),
        only_enabled=COALESCE(:only,unit_economy_settings.only_enabled),updated_at=now()"""),
        {'mp':payload.marketplace,'rate':payload.tariff_package_rate,'only':payload.only_enabled})
    db.commit()
    return {'ok': True}


class ProductStatusUpdate(BaseModel):
    marketplace: Literal['WB', 'OZON', 'YANDEX']
    status: Literal['active', 'archive']


@router.put('/products/{product_id}/status')
def save_product_status(product_id: int, payload: ProductStatusUpdate, db: Session = Depends(get_db)):
    exists = db.query(MasterProduct.id).filter(MasterProduct.id == product_id).first()
    if not exists:
        raise HTTPException(404, 'Товар не найден')
    db.execute(text("""INSERT INTO unit_economy_product_status(organization_id,product_id,marketplace,status)
        VALUES (NULLIF(current_setting('app.organization_id',true),'')::integer,:pid,:mp,:status)
        ON CONFLICT(organization_id,product_id,marketplace) DO UPDATE SET
        status=excluded.status,updated_at=now()"""),{'pid':product_id,'mp':payload.marketplace,'status':payload.status})
    db.commit()
    return {'ok': True, 'status':payload.status}


@router.get('/wb/acquiring-average')
def wb_acquiring_average(db: Session = Depends(get_db)):
    """Revenue-weighted acquiring percentage from completed daily WB sales, last four calendar months."""
    from datetime import date
    today = date.today()
    year, month = today.year, today.month - 4
    while month <= 0:
        month += 12
        year -= 1
    start = date(year, month, min(today.day, __import__('calendar').monthrange(year,month)[1]))
    row = db.execute(text("""
        SELECT count(*) AS n, coalesce(sum(e.acquiring),0) AS fee,
               coalesce(sum(e.retail),0) AS turnover
        FROM wb_finance_daily_entries e
        JOIN wb_finance_daily_reports r
          ON r.organization_id=e.organization_id AND r.report_id=e.report_id
        WHERE e.organization_id=NULLIF(current_setting('app.organization_id',true),'')::integer
          AND r.status='complete' AND r.report_date>=:start AND r.report_date<:today
          AND lower(btrim(e.operation))='продажа' AND e.retail>0
    """),{'start':start,'today':today}).mappings().one()
    turnover = float(row['turnover'])
    return {'rate':round(float(row['fee']) / turnover * 100, 4) if turnover>0 else None,
            'date_from':start.isoformat(),'date_to':(today-__import__('datetime').timedelta(days=1)).isoformat(),
            'rows':int(row['n']), 'basis':'acquiring / retail for completed daily sales'}
