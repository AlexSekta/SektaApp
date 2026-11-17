"""Read-only, confirmed-identity dimension comparison for catalog review."""

FIELDS = ('length_cm', 'width_cm', 'height_cm')


def dimension_issue(catalog, remote, state='OK', *, tolerance_cm=0.05):
    """Compare ordered dimensions in centimeters, without inventing absent measurements.

    Returns None if no issue or if the remote snapshot is not successfully verified.
    """
    if str(state).upper() in ('UNKNOWN', 'API_ERROR', 'INVALID_UNIT'):
        return None
    if str(state).upper() not in ('OK', 'COMPLETE', 'VALID', 'MISSING', 'PARTIAL'):
        return None
    if not remote or len(remote) != 3 or any(v is None or float(v) <= 0 for v in remote):
        return {'code': 'MARKETPLACE_MISSING', 'label': 'Не заполнены габариты на МП'}
    if not catalog or len(catalog) != 3 or any(v is None or float(v) <= 0 for v in catalog):
        return {'code': 'CATALOG_MISSING', 'label': 'Не заполнены габариты каталога'}
    if any(abs(float(a) - float(b)) > tolerance_cm for a, b in zip(catalog, remote)):
        return {'code': 'DIFFERENT', 'label': 'Габариты отличаются'}
    return None


def list_dimension_issues(db, organization_id):
    from backend.models.master_product import MasterProduct
    from backend.models.marketplace_catalog_card import MarketplaceCatalogCard
    from backend.models.marketplace_product_snapshot import MarketplaceProductSnapshot
    from backend.models.wb_identity import WBIdentityLink

    products = {p.id: p for p in db.query(MasterProduct).filter_by(organization_id=organization_id).all()}
    links = {(c.marketplace.upper(), str(c.external_id)): c.master_id
             for c in db.query(MarketplaceCatalogCard).filter_by(organization_id=organization_id).all()}
    for c in db.query(WBIdentityLink).filter_by(organization_id=organization_id).all():
        links[('WB', str(c.nm_id))] = c.master_id
    result = []
    for snap in db.query(MarketplaceProductSnapshot).filter_by(organization_id=organization_id).all():
        mid = links.get((snap.marketplace.upper(), str(snap.external_id)))
        p = products.get(mid)
        if p is None:
            continue
        remote = [getattr(snap, field) for field in FIELDS]
        catalog = [getattr(p, field) for field in FIELDS]
        issue = dimension_issue(catalog, remote, snap.dimension_state)
        if not issue:
            continue
        result.append({
            'master_id': p.id, 'article': p.seller_article, 'title': p.name,
            'marketplace': snap.marketplace.upper(), 'external_id': snap.external_id,
            'code': issue['code'], 'label': issue['label'],
            'catalog_cm': [float(x) if x is not None else None for x in catalog],
            'marketplace_cm': [float(x) if x is not None else None for x in remote],
            'checked_at': snap.checked_at.isoformat() if snap.checked_at else None,
        })
    return result
