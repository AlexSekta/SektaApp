"""Conservative preview of WB identity proposals. Pure planning, no writes."""
from collections import Counter, defaultdict


def build_proposals(cards, links, masters, locals_, reviews=(), imported_cards=()):
    """Only unlinked WB nmIDs with one identical article in both local and master.

    Results are explicit proposals, NOT automatic assignments. Any ambiguity is excluded.
    """
    live = {}
    nm_count = Counter(str(c.get('nmID') or '').strip() for c in cards)
    article_count = Counter(str(c.get('vendorCode') or '').strip() for c in cards)
    for c in cards:
        nm = str(c.get('nmID') or '').strip()
        if nm and nm_count[nm] == 1:
            live[nm] = c
    linked_nm = {str(l.nm_id) for l in links}
    linked_master = {int(l.master_id) for l in links}
    masters_by_article = defaultdict(list)
    local_by_nm = defaultdict(list)
    local_by_article = defaultdict(list)
    for m in masters:
        masters_by_article[str(m.seller_article or '').strip()].append(m)
    for p in locals_:
        local_by_nm[str(p.nm_id or '').strip()].append(p)
        local_by_article[str(p.seller_article or '').strip()].append(p)
    imported_by_nm = defaultdict(list)
    for imported in imported_cards:
        imported_by_nm[str(imported.external_id)].append(imported)
    dismissed = {str(r.nm_id) for r in reviews if r.status == 'DISMISSED'}
    proposals, skipped = [], []
    for nm, card in sorted(live.items(), key=lambda kv: (str(kv[1].get('vendorCode') or ''), kv[0])):
        if nm in linked_nm:
            continue
        article = str(card.get('vendorCode') or '').strip()
        reason = None
        if nm in dismissed:
            reason = 'dismissed'
        elif not article or article_count[article] != 1:
            reason = 'duplicate_or_empty_article'
        elif len(local_by_nm[nm]) != 1:
            reason = 'local_missing_or_duplicate'
        elif len(local_by_article[article]) != 1 or local_by_nm[nm][0].seller_article != article:
            reason = 'local_article_conflict'
        elif len(masters_by_article[article]) != 1:
            reason = 'master_missing_or_duplicate'
        elif masters_by_article[article][0].id in linked_master:
            reason = 'master_already_linked'
        elif imported_by_nm[nm] and (len(imported_by_nm[nm]) != 1 or
              imported_by_nm[nm][0].master_id != masters_by_article[article][0].id or
              imported_by_nm[nm][0].seller_article != article):
            reason = 'imported_identity_conflict'
        if reason:
            skipped.append({'nm_id': nm, 'article': article, 'reason': reason})
            continue
        master = masters_by_article[article][0]
        proposals.append({'nm_id': nm, 'article': article, 'master_id': master.id,
                          'master_name': master.name or '', 'wb_title': str(card.get('title') or ''),
                          'local_product_id': local_by_nm[nm][0].id})
    return proposals, skipped
