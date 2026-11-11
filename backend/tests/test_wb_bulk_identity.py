from types import SimpleNamespace as Obj
from backend.services.wb_bulk_identity import build_proposals


def card(nm, article):
    return {'nmID': nm, 'vendorCode': article, 'title': article}


def test_unique_exact_local_and_master_is_proposed():
    matches, skips = build_proposals([card(123,'HS044')], [], [Obj(id=9,seller_article='HS044',name='Product')], [Obj(id=8,nm_id='123',seller_article='HS044')])
    assert matches[0]['master_id'] == 9
    assert matches[0]['nm_id'] == '123'
    assert skips == []


def test_article_without_local_nm_never_proposed():
    matches, skips = build_proposals([card(123,'HS044')], [], [Obj(id=9,seller_article='HS044',name='')], [Obj(id=8,nm_id='999',seller_article='HS044')])
    assert matches == []
    assert skips[0]['reason'] == 'local_missing_or_duplicate'


def test_changed_article_is_rejected():
    matches, skips = build_proposals([card(123,'HS219')], [], [Obj(id=9,seller_article='HS219',name='')], [Obj(id=8,nm_id='123',seller_article='HS066')])
    assert not matches and skips[0]['reason'] == 'local_article_conflict'


def test_duplicate_live_article_is_rejected():
    matches, skips = build_proposals([card(123,'HS044'),card(456,'HS044')], [], [Obj(id=9,seller_article='HS044',name='')], [Obj(id=8,nm_id='123',seller_article='HS044')])
    assert matches == []
    assert len(skips) == 2


def test_existing_master_link_is_rejected():
    matches, skips = build_proposals([card(123,'HS044')], [Obj(nm_id='999',master_id=9)], [Obj(id=9,seller_article='HS044',name='')], [Obj(id=8,nm_id='123',seller_article='HS044')])
    assert not matches and skips[0]['reason'] == 'master_already_linked'


def test_dismissed_review_is_rejected():
    matches, skips = build_proposals([card(123,'HS044')], [], [Obj(id=9,seller_article='HS044',name='')], [Obj(id=8,nm_id='123',seller_article='HS044')], [Obj(nm_id='123',status='DISMISSED')])
    assert not matches and skips[0]['reason'] == 'dismissed'


def test_existing_import_conflict_is_rejected():
    matches, skips = build_proposals([card(123,'HS044')], [],
        [Obj(id=9,seller_article='HS044',name='')],
        [Obj(id=8,nm_id='123',seller_article='HS044')],
        imported_cards=[Obj(external_id='123',master_id=18,seller_article='HS044')])
    assert not matches and skips[0]['reason'] == 'imported_identity_conflict'
