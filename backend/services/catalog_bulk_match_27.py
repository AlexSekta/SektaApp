"""Conservative matching for previously unlinked Ozon products.

Nothing here writes. Existing external identities always outrank chosen match policy.
"""
import hashlib
import json
from collections import Counter, defaultdict
from backend.models.master_product import MasterProduct
from backend.models.marketplace_catalog_card import MarketplaceCatalogCard
from backend.models.wb_identity import WBIdentityLink, WBIdentityReview
from backend.models.product import Product


def candidates(db, rows, match_by, marketplace="OZON"):
    if match_by not in ('ARTICLE', 'BARCODE'):
        raise ValueError('Unknown matching strategy')
    if marketplace not in ('WB', 'OZON', 'YANDEX'):
        raise ValueError('Unknown marketplace')
    masters = db.query(MasterProduct).all()
    links = db.query(MarketplaceCatalogCard).filter(MarketplaceCatalogCard.marketplace == marketplace).all()
    wb_links = db.query(WBIdentityLink).all() if marketplace == 'WB' else []
    linked_wb_ids = {str(x.nm_id) for x in wb_links}
    wb_masters = {x.master_id for x in wb_links}
    wb_articles = {x.current_article for x in wb_links}
    dismissed = {str(x.nm_id) for x in db.query(WBIdentityReview).filter(WBIdentityReview.status == 'DISMISSED').all()} if marketplace == 'WB' else set()
    local_wb = db.query(Product).filter(Product.marketplace == 'WB').all() if marketplace == 'WB' else []
    local_by_id = defaultdict(list)
    local_by_article = defaultdict(list)
    for p in local_wb:
        local_by_id[str(p.nm_id)].append(p)
        local_by_article[str(p.seller_article)].append(p)
    linked_ids = {str(x.external_id) for x in links} | linked_wb_ids
    linked_articles = {x.seller_article for x in links} | wb_articles
    linked_master_ids = {x.master_id for x in links} | wb_masters
    articles = defaultdict(list)
    barcodes = defaultdict(list)
    for m in masters:
        if m.seller_article:
            articles[m.seller_article.strip()].append(m)
        if m.barcode:
            barcodes[m.barcode.strip()].append(m)
    remote_article_count = Counter(str(r.get('article') or '').strip() for r in rows)
    remote_external_count = Counter(str(r.get('external_id') or '').strip() for r in rows)
    remote_barcode_count = Counter(b for r in rows for b in set(str(x).strip() for x in r.get('barcodes') or [] if str(x).strip()))
    result, excluded = [], []
    for row in rows:
        external = str(row.get('external_id') or '').strip()
        article = str(row.get('article') or '').strip()
        reason = None
        match = None
        if not external or not article:
            reason = 'MISSING_EXTERNAL_ID_OR_ARTICLE'
        elif remote_external_count[external] != 1:
            reason = 'DUPLICATE_REMOTE_EXTERNAL_ID'
        elif external in linked_ids:
            reason = 'ALREADY_LINKED'
        elif external in dismissed:
            reason = 'PREVIOUSLY_DISMISSED'
        elif article in linked_articles:
            reason = 'ARTICLE_ALREADY_LINKED'
        elif remote_article_count[article] != 1:
            reason = 'DUPLICATE_REMOTE_ARTICLE'
        elif match_by == 'ARTICLE':
            possible = articles.get(article, [])
            if len(possible) != 1:
                reason = 'NO_UNIQUE_CATALOG_ARTICLE'
            else:
                match = possible[0]
        else:
            remote_codes = set(str(b).strip() for b in (row.get('barcodes') or []) if str(b).strip())
            possible = {m.id:m for code in remote_codes for m in barcodes.get(code, [])}
            if len(possible) != 1:
                reason = 'NO_UNIQUE_CATALOG_BARCODE'
            elif any(remote_barcode_count[code] > 1 for code in remote_codes if code in barcodes):
                reason = 'BARCODE_SHARED_BY_REMOTE_CARDS'
            else:
                match = next(iter(possible.values()))
                # A barcode must not override a conflicting unique article identity.
                article_masters = articles.get(article, [])
                if article_masters and (len(article_masters) != 1 or article_masters[0].id != match.id):
                    reason, match = 'ARTICLE_BARCODE_DISAGREEMENT', None
        if match and not reason and match.id in linked_master_ids:
            reason = 'TARGET_ALREADY_LINKED_ON_MARKETPLACE'
        if match and not reason and marketplace == 'WB' and (
                len(local_by_id[external]) != 1 or
                local_by_id[external][0].seller_article != article or
                len(local_by_article[article]) != 1):
            reason = 'WB_LOCAL_CARD_MISSING_OR_CONFLICT'
        if match and not reason:
            result.append({'external_id':external,'article':article,'master_id':match.id,
                           'master_article':match.seller_article, 'master_name':match.name or '',
                           'remote_name':row.get('name') or '', 'barcodes':list(row.get('barcodes') or []),
                           'platform_ids':row.get('platform_ids') or {}, 'dimensions':row.get('dimensions')})
        else:
            excluded.append({'external_id':external,'article':article,'reason':reason or 'UNKNOWN'})
    # Two remote products must never be assigned to one master by automation.
    counts = Counter(p['master_id'] for p in result)
    kept = []
    for p in result:
        if counts[p['master_id']] != 1:
            excluded.append({'external_id':p['external_id'],'article':p['article'],'reason':'DUPLICATE_TARGET_MASTER'})
        else:
            kept.append(p)
    return kept, excluded


def fingerprint(proposals, match_by):
    normalized = [{'external_id':p['external_id'],'article':p['article'],
                   'master_id':p['master_id'], 'barcodes':sorted(set(p['barcodes'])),
                   'platform_ids':p['platform_ids'], 'dimensions':p['dimensions'],
                   'remote_name':p['remote_name']} for p in proposals]
    raw = json.dumps({'match_by':match_by,'items':sorted(normalized,key=lambda p:p['external_id'])},
                     ensure_ascii=False,sort_keys=True,default=str)
    return hashlib.sha256(raw.encode()).hexdigest()
