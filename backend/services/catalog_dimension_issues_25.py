"""Read-only cross-marketplace attention candidates from saved snapshots.

A matching seller article never creates a link.  A candidate's dimensions are
preliminary until the marketplace identity is explicitly confirmed.
"""
from collections import defaultdict
from hashlib import sha256
import json
from backend.services.catalog_dimension_issues_24 import dimension_issue, FIELDS


def dimension_fingerprint(master_id, marketplace, external_id, code, catalog, remote):
    """Stable for equivalent values, changes if either side changes."""
    def norm(values):
        return [None if v is None else str(round(float(v), 4)) for v in values]
    payload = [master_id, marketplace.upper(), str(external_id), code, norm(catalog), norm(remote)]
    return sha256(json.dumps(payload, separators=(',', ':'), ensure_ascii=False).encode()).hexdigest()


def group_snapshot_problems(products, snapshots, catalog_links, wb_links, decisions=()):
    """Pure matching/classification: no writes and no external API calls."""
    by_id = {p.id: p for p in products}
    by_article = defaultdict(list)
    for p in products:
        if p.seller_article:
            by_article[p.seller_article.strip()].append(p)
    confirmed = {}
    for c in catalog_links:
        if c.master_id:
            confirmed[(c.marketplace.upper(), str(c.external_id))] = c.master_id
    for c in wb_links:
        if c.master_id:
            confirmed[('WB', str(c.nm_id))] = c.master_id

    latest = {}
    for d in sorted(decisions, key=lambda item: item.id):
        latest[(d.marketplace.upper(), str(d.external_id), d.master_id, d.issue_code)] = d

    rows = []
    for snap in snapshots:
        marketplace = snap.marketplace.upper()
        identity = (marketplace, str(snap.external_id))
        linked_id = confirmed.get(identity)
        is_confirmed = linked_id is not None
        possible = by_article.get(str(snap.seller_article or '').strip(), [])
        # Never merge ambiguous article matches or a confirmed link into another product.
        if is_confirmed:
            master = by_id.get(linked_id)
            if master is None:
                continue
        elif len(possible) == 1:
            master = possible[0]
        else:
            # No safe master_id; show the external card separately.
            master = None
        problems = []
        if not is_confirmed:
            if len(possible) > 1:
                problems.append({'code': 'AMBIGUOUS_ARTICLE', 'label': 'Неоднозначное совпадение артикула'})
            elif master is None:
                problems.append({'code': 'UNMATCHED_CARD', 'label': 'Нет товара в общем каталоге'})
            else:
                problems.append({'code': 'LINK_UNCONFIRMED', 'label': 'Связь с товаром не подтверждена'})
        catalog = [getattr(master, field) for field in FIELDS] if master else [None] * 3
        remote = [getattr(snap, field) for field in FIELDS]
        if master is not None:
            difference = dimension_issue(catalog, remote, snap.dimension_state)
            if difference:
                details = {**difference, 'preliminary': not is_confirmed}
                if is_confirmed:
                    code = difference['code']
                    fp = dimension_fingerprint(master.id, marketplace, snap.external_id, code, catalog, remote)
                    details['fingerprint'] = fp
                    previous = latest.get((marketplace, str(snap.external_id), master.id, code))
                    if previous and previous.fingerprint == fp:
                        if previous.decision == 'ACCEPTED':
                            details = None
                        elif previous.decision == 'DISPUTED':
                            details['decision'] = 'DISPUTED'
                if details is not None:
                    problems.append(details)
        if not problems:
            continue
        rows.append({
            'master_id': master.id if master else None,
            'article': master.seller_article if master else (snap.seller_article or ''),
            'title': master.name if master else (snap.title or ''),
            'marketplace': marketplace, 'external_id': str(snap.external_id),
            'confirmed': is_confirmed,
            'catalog_cm': [float(x) if x is not None else None for x in catalog],
            'marketplace_cm': [float(x) if x is not None else None for x in remote],
            'checked_at': snap.checked_at.isoformat() if snap.checked_at else None,
            'problems': problems,
        })
    return sorted(rows, key=lambda r: (r['article'], r['marketplace'], r['external_id']))


def list_snapshot_attention(db, organization_id):
    from backend.models.master_product import MasterProduct
    from backend.models.marketplace_catalog_card import MarketplaceCatalogCard
    from backend.models.marketplace_product_snapshot import MarketplaceProductSnapshot
    from backend.models.wb_identity import WBIdentityLink
    from backend.models.marketplace_dimension_decision import MarketplaceDimensionDecision
    return group_snapshot_problems(
        db.query(MasterProduct).filter_by(organization_id=organization_id).all(),
        db.query(MarketplaceProductSnapshot).filter_by(organization_id=organization_id).all(),
        db.query(MarketplaceCatalogCard).filter_by(organization_id=organization_id).all(),
        db.query(WBIdentityLink).filter_by(organization_id=organization_id).all(),
        db.query(MarketplaceDimensionDecision).filter_by(organization_id=organization_id).all(),
    )
