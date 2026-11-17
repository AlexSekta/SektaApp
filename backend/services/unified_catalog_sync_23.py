"""On-demand, tenant-scoped catalog snapshot collection.

Does not create/confirm identities, modify master_products, or affect schedulers.
"""
from backend.models.marketplace_connection import MarketplaceConnection
from backend.services.marketplace_catalog_import import read_marketplace
from backend.services.marketplace_snapshot_service import save_snapshot

MARKETS = ('WB', 'OZON', 'YANDEX')


def configured_markets(db):
    connections = {r.marketplace.upper(): r for r in db.query(MarketplaceConnection).all()}
    eligible = []
    skipped = []
    for market in MARKETS:
        conn = connections.get(market)
        if not conn or not conn.enabled:
            skipped.append({'marketplace': market, 'reason': 'DISABLED'})
        elif not conn.credentials_encrypted:
            skipped.append({'marketplace': market, 'reason': 'NO_CREDENTIALS'})
        else:
            eligible.append(market)
    return eligible, skipped


def snapshot_values(row):
    """Explicit native units. Unknown units must never be guessed."""
    dims = row.get('dimensions') or {}
    state = row.get('dimension_fetch_status')
    if state == 'API_ERROR':
        return None  # Keep the last successful full snapshot.
    if all(dims.get(k) is not None for k in ('length_cm', 'width_cm', 'height_cm')):
        native = row.get('dimension_native')
        if row.get('marketplace') == 'OZON':
            if not native or native.get('unit') not in ('mm','cm'):
                return (None, None, None), None
            return tuple(native['values']), native['unit']
        # WB dimensions are cm in the WB card API; Yandex weightDimensions
        # have already been normalized to cm by the existing importer.
        return tuple(dims[k] for k in ('length_cm','width_cm','height_cm')), 'cm'
    return (None, None, None), None


def sync_connected_catalogs(db, *, organization_id, reader=read_marketplace):
    """Persist successful marketplaces independently; report per-source failures.

    Transaction ownership: each successful marketplace is committed once, and
    failed marketplaces are rolled back without affecting already saved ones.
    """
    enabled, skipped = configured_markets(db)
    result = {'marketplaces': [], 'skipped': skipped, 'mode': 'SNAPSHOTS_ONLY'}
    for market in enabled:
        try:
            rows = reader(db, market)
            if not isinstance(rows, list):
                raise ValueError('Invalid catalog response')
            # Validate all remote identifiers before writing ANY card in this market.
            external_ids = [str(r.get('external_id') or '').strip() for r in rows]
            if any(not x for x in external_ids) or len(set(external_ids)) != len(external_ids):
                raise ValueError('Missing or duplicate marketplace external IDs')
            changed = 0
            ignored_dimension_errors = 0
            for row in rows:
                dims = snapshot_values(row)
                if dims is None:
                    ignored_dimension_errors += 1
                    continue
                _, did_change = save_snapshot(
                    db, organization_id=organization_id, marketplace=market,
                    external_id=row['external_id'], seller_article=row.get('article'),
                    title=row.get('name'), description=row.get('description'),
                    barcodes=row.get('barcodes'), platform_ids=row.get('platform_ids'),
                    dimensions=dims[0], dimension_unit=dims[1],
                )
                changed += int(did_change)
            db.commit()
            result['marketplaces'].append({'marketplace':market,'status':'OK',
                'received':len(rows),'changed':changed,
                'skipped_api_errors':ignored_dimension_errors})
        except Exception:
            db.rollback()
            # Avoid reporting credentials, response contents or user data.
            result['marketplaces'].append({'marketplace':market,'status':'ERROR',
                'reason':'SYNC_FAILED_CHECK_SERVER_LOG'})
    return result
