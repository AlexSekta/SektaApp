"""Tenant-isolated, read-only view over the persisted Ozon FBS archive.

No Ozon network requests; no package creation, shipping, or label generation.
WB/Yandex are intentionally reported as unavailable until a real collector exists.
"""
from datetime import date, datetime, time, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response
from pydantic import BaseModel, Field
from sqlalchemy import text
from sqlalchemy.orm import Session

from backend.auth.security import require_current_user
from backend.dependencies import get_db

router = APIRouter(prefix='/orders', tags=['FBS orders'])
MOSCOW = timezone(timedelta(hours=3))
STATUS_GROUPS = {
    'awaiting_packaging': 'new',
    'awaiting_registration': 'new',
    'acceptance_in_progress': 'new',
    'awaiting_deliver': 'assembly',
    'delivering': 'delivery',
    'delivered': 'delivery',
}


def group_for_status(value: str) -> str:
    return STATUS_GROUPS.get(value, 'other')


def _org(request: Request) -> int:
    require_current_user(request)
    org = getattr(request.state, 'organization_id', None)
    if org is None:
        raise HTTPException(403, 'Не определена организация')
    return int(org)


def _archive_ready(db: Session) -> None:
    exists = db.execute(text("SELECT to_regclass('public.ozon_fbs_sticker_archive')")).scalar()
    if exists is None:
        raise HTTPException(503, 'Архив Ozon FBS ещё не создан. Запустите монитор.')


def _dates(from_day: date, to_day: date):
    if to_day < from_day or (to_day - from_day).days > 366:
        raise HTTPException(422, 'Период должен быть от 1 до 367 дней')
    start = datetime.combine(from_day, time.min, tzinfo=MOSCOW)
    end = datetime.combine(to_day + timedelta(days=1), time.min, tzinfo=MOSCOW)
    return start, end


def _filters(from_day: date, to_day: date, query: str):
    start, end = _dates(from_day, to_day)
    query = query.strip()
    if len(query) > 100:
        raise HTTPException(422, 'Поисковая строка слишком длинная')
    return {'start': start, 'end': end, 'query': query}


def _base_where():
    return '''organization_id=:org AND first_seen_at>=:start AND first_seen_at<:end
              AND (:query='' OR strpos(lower(concat_ws(' ', posting_number, order_number,
                           scanit, upper_barcode, lower_barcode)), lower(:query))>0)'''


def _group_sql():
    return """CASE WHEN status IN ('awaiting_packaging','awaiting_registration','acceptance_in_progress') THEN 'new'
               WHEN status='awaiting_deliver' THEN 'assembly'
               WHEN status IN ('delivering','delivered') THEN 'delivery'
               ELSE 'other' END"""


@router.get('/fbs')
def orders_list(
    request: Request,
    marketplace: str = Query('OZON'),
    status: str = Query('all'),
    date_from: date = Query(...),
    date_to: date = Query(...),
    q: str = Query(''),
    limit: int = Query(50, ge=1, le=100),
    offset: int = Query(0, ge=0, le=100000),
    db: Session = Depends(get_db),
):
    org = _org(request)
    market = marketplace.upper()
    if market not in ('WB', 'OZON', 'YANDEX'):
        raise HTTPException(422, 'Неизвестный маркетплейс')
    if status not in ('all','new','assembly','delivery'):
        raise HTTPException(422, 'Неизвестный статус')
    params = _filters(date_from, date_to, q)
    if market != 'OZON':
        return {'marketplace': market, 'available': False,
                'message': 'Монитор FBS-заказов этого маркетплейса пока не подключён',
                'items': [], 'total': None, 'counts': None}
    _archive_ready(db)
    params.update({'org': org, 'limit': limit, 'offset': offset, 'status': status})
    base = _base_where()
    category = _group_sql()
    summary = db.execute(text(f'''SELECT
         count(*) FILTER (WHERE grp='new')::integer AS new_count,
         count(*) FILTER (WHERE grp='assembly')::integer AS assembly_count,
         count(*) FILTER (WHERE grp='delivery')::integer AS delivery_count,
         count(*)::integer AS all_count
         FROM (SELECT {category} AS grp FROM ozon_fbs_sticker_archive WHERE {base}) x'''), params).mappings().one()
    selection = f' AND ({category})=:status' if status != 'all' else ''
    total = db.execute(text(f'''SELECT count(*) FROM ozon_fbs_sticker_archive WHERE {base} {selection}'''), params).scalar_one()
    rows = db.execute(text(f'''SELECT posting_number, order_number, status, scanit,
        upper_barcode, lower_barcode, first_seen_at, last_seen_at,
        ozon_created_at, ready_detected_at, ready_from_new,
        sticker_saved_at, sticker_sha256, label_error,
        (sticker_pdf IS NOT NULL) AS has_pdf
        FROM ozon_fbs_sticker_archive WHERE {base} {selection}
        ORDER BY first_seen_at DESC, posting_number DESC
        LIMIT :limit OFFSET :offset'''), params).mappings().all()
    items = [{**dict(r), 'status_group': group_for_status(r['status'] or '')} for r in rows]
    return {'marketplace': market, 'available': True, 'items': items, 'total': total,
            'counts': dict(summary)}


@router.get('/fbs/ozon/{posting_number}/label')
def saved_ozon_label(request: Request, posting_number: str, db: Session = Depends(get_db)):
    org = _org(request)
    if not posting_number or len(posting_number) > 100:
        raise HTTPException(422, 'Неверный номер отправления')
    _archive_ready(db)
    row = db.execute(text('''SELECT sticker_pdf FROM ozon_fbs_sticker_archive
        WHERE organization_id=:org AND posting_number=:posting'''),
        {'org': org, 'posting': posting_number}).mappings().first()
    if row is None or row['sticker_pdf'] is None:
        raise HTTPException(404, 'Сохранённая этикетка отсутствует')
    pdf = bytes(row['sticker_pdf'])
    if not pdf.startswith(b'%PDF-') or len(pdf) > 8 * 1024 * 1024:
        raise HTTPException(409, 'Сохранённый PDF повреждён или слишком большой')
    return Response(content=pdf, media_type='application/pdf', headers={
        'Content-Disposition': 'inline; filename="ozon-fbs-label.pdf"',
        'Cache-Control': 'private, no-store',
        'X-Content-Type-Options': 'nosniff',
    })


class OzonLabelSettingsIn(BaseModel):
    delay_minutes: int = Field(ge=5, le=1440)
    auto_create_enabled: bool = False


@router.get('/fbs/ozon/label-settings')
def ozon_label_settings(request: Request, db: Session = Depends(get_db)):
    org = _org(request)
    _archive_ready(db)
    row = db.execute(text('''SELECT delay_minutes,auto_create_enabled
        FROM ozon_fbs_label_settings WHERE organization_id=:org'''),{'org':org}).mappings().first()
    return dict(row) if row else {'delay_minutes':20,'auto_create_enabled':False}


@router.put('/fbs/ozon/label-settings')
def update_ozon_label_settings(request: Request, settings: OzonLabelSettingsIn,
                               db: Session = Depends(get_db)):
    org = _org(request)
    _archive_ready(db)
    db.execute(text('''INSERT INTO ozon_fbs_label_settings
        (organization_id,delay_minutes,auto_create_enabled) VALUES (:org,:minutes,:enabled)
        ON CONFLICT (organization_id) DO UPDATE SET
        delay_minutes=EXCLUDED.delay_minutes,
        auto_create_enabled=EXCLUDED.auto_create_enabled,updated_at=now()'''),
        {'org':org,'minutes':settings.delay_minutes,'enabled':settings.auto_create_enabled})
    db.commit()
    return {'delay_minutes':settings.delay_minutes,'auto_create_enabled':settings.auto_create_enabled}
