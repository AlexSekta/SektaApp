"""Explicit, tenant-scoped snapshot recording for future unified marketplace sync.

Not wired into existing background schedulers in foundation patch #21.
"""
import json
from decimal import Decimal, InvalidOperation
from datetime import datetime, timezone
from sqlalchemy.orm import Session
from backend.models.marketplace_product_snapshot import MarketplaceProductSnapshot, MarketplaceProductSnapshotChange

SUPPORTED = {'WB', 'OZON', 'YANDEX'}
STATE = {'VALID', 'MISSING', 'PARTIAL', 'UNKNOWN', 'API_ERROR', 'INVALID_UNIT'}


def normalized_dimensions(length, width, height, unit):
    """Return normalized cm tuple and status; never assume units."""
    values = (length, width, height)
    if all(x is None or x == '' for x in values):
        return (None, None, None), 'MISSING'
    if any(x is None or x == '' for x in values):
        return (None, None, None), 'PARTIAL'
    u = str(unit or '').strip().lower()
    factors = {'cm': Decimal('1'), 'mm': Decimal('0.1')}
    if u not in factors:
        return (None, None, None), 'INVALID_UNIT'
    try:
        d = tuple(Decimal(str(x).replace(',', '.')) for x in values)
    except (InvalidOperation, ValueError):
        return (None, None, None), 'UNKNOWN'
    if any(x <= 0 or not x.is_finite() for x in d):
        return (None, None, None), 'UNKNOWN'
    return tuple(x * factors[u] for x in d), 'VALID'


def _text_json(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':'))


def _data_state(row):
    return {
        'seller_article': row.seller_article,
        'title': row.title,
        'description': row.description,
        'barcodes': json.loads(row.barcodes_json or '[]'),
        'platform_ids': json.loads(row.platform_ids_json or '{}'),
        'dimensions': [format(Decimal(str(getattr(row, field))).normalize(), 'f') if getattr(row, field) is not None else None for field in ('length_raw','width_raw','height_raw')],
        'dimension_unit': row.dimension_unit,
        'dimension_state': row.dimension_state,
    }


def save_snapshot(db: Session, *, organization_id: int, marketplace: str, external_id: str,
                  seller_article=None, title=None, description=None, barcodes=None,
                  platform_ids=None, dimensions=(None, None, None), dimension_unit=None,
                  api_error=False):
    """Upsert latest snapshot and append history only when content changes.

    Caller must provide authenticated tenant organization_id. Does NOT change
    master_products, confirmed links, stocks, or marketplace configuration.
    Caller owns transaction commit/rollback.
    """
    mp = str(marketplace).upper().strip()
    eid = str(external_id or '').strip()
    if mp not in SUPPORTED or not eid or not isinstance(organization_id, int) or organization_id <= 0:
        raise ValueError('Invalid marketplace identity or organization')
    if len(dimensions) != 3:
        raise ValueError('Dimensions must be a triple')
    if api_error:
        # A transient API failure must never replace a previously successful snapshot.
        return None, False
    normalized, state = normalized_dimensions(*dimensions, dimension_unit)
    normalized_codes = sorted({str(v).strip() for v in (barcodes or []) if str(v).strip()})
    if not isinstance(platform_ids or {}, dict):
        raise ValueError('platform_ids must be a dict')
    record = db.query(MarketplaceProductSnapshot).filter_by(
        organization_id=organization_id, marketplace=mp, external_id=eid
    ).with_for_update().first()
    before = _data_state(record) if record else None
    if record is None:
        record = MarketplaceProductSnapshot(organization_id=organization_id, marketplace=mp, external_id=eid)
        db.add(record)
    record.seller_article = str(seller_article).strip() if seller_article is not None else None
    record.title = title
    record.description = description
    record.barcodes_json = _text_json(normalized_codes)
    record.platform_ids_json = _text_json(platform_ids or {})
    for key, value in zip(('length_raw', 'width_raw', 'height_raw'), dimensions):
        try:
            parsed = Decimal(str(value).replace(',', '.')) if value is not None and value != '' else None
            if parsed is not None and not parsed.is_finite():
                parsed = None
        except (InvalidOperation, ValueError):
            parsed = None
        setattr(record, key, parsed)
    for key, value in zip(('length_cm','width_cm','height_cm'), normalized):
        setattr(record, key, value)
    record.dimension_unit = str(dimension_unit).strip().lower() if dimension_unit is not None else None
    record.dimension_state = state
    record.checked_at = datetime.now(timezone.utc)
    after = _data_state(record)
    if before != after:
        db.add(MarketplaceProductSnapshotChange(
            organization_id=organization_id, marketplace=mp, external_id=eid,
            before_json=_text_json(before) if before is not None else None,
            after_json=_text_json(after),
        ))
    return record, before != after
