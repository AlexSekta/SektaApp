"""Regression tests: a previously OPEN review must close after verified import."""
from datetime import datetime
from types import SimpleNamespace
from unittest.mock import MagicMock

from backend.models.product import Product
from backend.models.master_product import MasterProduct
from backend.models.wb_identity import WBIdentityReview, WBIdentityLink
from backend.services.wb_identity_service import observe


def _session(local, master, link, review, collisions=None):
    db = MagicMock()
    results = {
        Product: [local, collisions or []],
        MasterProduct: [master],
        WBIdentityLink: [link],
        WBIdentityReview: [review],
    }
    calls = {type_: 0 for type_ in results}

    def query(model):
        idx = calls[model]
        calls[model] += 1
        output = results[model][min(idx, len(results[model]) - 1)]
        q = MagicMock()
        q.filter.return_value = q
        q.all.return_value = output
        q.first.return_value = output
        return q

    db.query.side_effect = query
    return db


def test_confirmed_import_closes_stale_open_review():
    local = SimpleNamespace(seller_article='HS218')
    master = SimpleNamespace(id=97, seller_article='HS218')
    when = datetime(2026, 11, 10)
    link = SimpleNamespace(master_id=97, current_article='HS218', confirmed_at=when)
    review = SimpleNamespace(status='OPEN', master_id=None)
    db = _session([local], master, link, review)
    result = observe(db, {'nmID': 1840650707, 'vendorCode': 'HS218'})
    assert result is None
    assert review.status == 'APPROVED'
    assert review.master_id == 97
    assert review.reviewed_at == when


def test_missing_local_card_cannot_be_auto_resolved():
    link = SimpleNamespace(master_id=97, current_article='HS218', confirmed_at=datetime.utcnow())
    review = SimpleNamespace(status='OPEN', master_id=None)
    db = _session([], SimpleNamespace(id=97, seller_article='HS218'), link, review)
    assert observe(db, {'nmID': 1840650707, 'vendorCode': 'HS218'}) is review
    assert review.status == 'OPEN'
    assert review.reason == 'MISSING_LOCAL_CARD'


def test_wrong_master_article_cannot_be_auto_resolved():
    link = SimpleNamespace(master_id=97, current_article='HS218', confirmed_at=datetime.utcnow())
    review = SimpleNamespace(status='OPEN', master_id=None)
    db = _session([SimpleNamespace(seller_article='HS218')], None, link, review)
    assert observe(db, {'nmID': 1840650707, 'vendorCode': 'HS218'}) is review
    assert review.status == 'OPEN'
