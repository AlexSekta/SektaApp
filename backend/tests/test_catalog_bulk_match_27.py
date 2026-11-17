"""Offline regression tests for conservative bulk matching and schedule validation."""
from types import SimpleNamespace
from unittest.mock import patch
from fastapi import HTTPException
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from backend.models.master_product import MasterProduct
from backend.models.marketplace_catalog_card import MarketplaceCatalogCard
from backend.models.marketplace_product_barcode import MarketplaceProductBarcode
from backend.models.catalog_sync_setting import CatalogSyncSetting
from backend.services.catalog_bulk_match_27 import candidates, fingerprint
from backend.api.marketplace_catalog_import import (
    MatchingSettingsInput, matching_settings_save, matching_settings_get,
    ozon_auto_preview, ozon_auto_apply, AutoApplyInput)


def row(article, external, barcode):
    return {'marketplace':'OZON','article':article,'external_id':external,
            'name':'Ozon product','barcodes':[barcode], 'platform_ids':{'product_id':external},
            'dimensions':None}


@pytest.fixture
def db():
    engine=create_engine('sqlite:///:memory:')
    for model in (MasterProduct, MarketplaceCatalogCard, MarketplaceProductBarcode, CatalogSyncSetting):
        model.__table__.c.organization_id.server_default=None
        model.__table__.create(engine)
    with Session(engine) as session:
        session.add_all([
            MasterProduct(organization_id=2, id=1, seller_article='HS061', barcode='111',
                          internal_article='HS061', name='My product', sort_order=1,
                          group='G', purchase_price=12, additional_costs=2, active=True, status='SELLING'),
            MasterProduct(organization_id=2, id=2, seller_article='HS062', barcode='222',
                          internal_article='HS062', name='Second', sort_order=2,
                          group='G', purchase_price=15, additional_costs=3, active=False, status='READY'),
        ])
        session.commit()
        yield session
    engine.dispose()


def test_article_unique_and_exclusions(db):
    proposals, excluded=candidates(db,[row('HS061','10','999'),row('HS062','20','222'),row('NEW','30','x')],'ARTICLE')
    assert len(proposals)==2 and len(excluded)==1
    assert proposals[0]['master_id']==1


def test_duplicates_and_reused_target_are_blocked(db):
    proposals, excluded=candidates(db,[row('HS061','10','111'),row('HS061','20','111')],'ARTICLE')
    assert proposals==[] and len(excluded)==2


def test_barcode_match_and_mismatch_prevented(db):
    proposals, excluded=candidates(db,[row('DIFFERENT','10','111')],'BARCODE')
    assert len(proposals)==1 and proposals[0]['master_article']=='HS061'
    proposals, excluded=candidates(db,[row('HS062','10','111')],'BARCODE')
    assert proposals==[] and excluded[0]['reason']=='ARTICLE_BARCODE_DISAGREEMENT'


def test_match_fingerprint_tracks_changes(db):
    a,_=candidates(db,[row('HS061','10','111')],'ARTICLE')
    b,_=candidates(db,[row('HS061','10','NEW')],'ARTICLE')
    assert fingerprint(a,'ARTICLE')!=fingerprint(b,'ARTICLE')


def test_invalid_schedule_is_rejected(db):
    with patch('backend.api.marketplace_catalog_import.owner',return_value=None),patch('backend.api.marketplace_catalog_import.org_id',return_value=2):
        with pytest.raises(HTTPException) as exc:
            matching_settings_save(MatchingSettingsInput(match_by='ARTICLE',times=['25:30']),SimpleNamespace(),db)
    assert exc.value.status_code==422


def test_schedule_settings_are_scoped_and_inactive(db):
    with patch('backend.api.marketplace_catalog_import.owner',return_value=None),patch('backend.api.marketplace_catalog_import.org_id',return_value=2):
        saved=matching_settings_save(MatchingSettingsInput(match_by='BARCODE',auto_enabled=True,
            timezone='Europe/Moscow',times=['06:00','22:30']),SimpleNamespace(),db)
        reread=matching_settings_get(SimpleNamespace(),db)
    assert saved['auto_enabled'] and reread['times']==['06:00','22:30']
    assert reread['scheduler_active'] is False


def test_apply_all_one_transaction_and_replay_rejected(db):
    remote=[row('HS061','10','777'),row('HS062','20','888')]
    patches=(patch('backend.api.marketplace_catalog_import.owner',return_value=None),
             patch('backend.api.marketplace_catalog_import.org_id',return_value=2),
             patch('backend.services.unified_catalog_sync_23.configured_markets',return_value=(['OZON'],[])),
             patch('backend.api.marketplace_catalog_import.read_marketplace',return_value=remote))
    with patches[0],patches[1],patches[2],patches[3]:
        preview=ozon_auto_preview(SimpleNamespace(),db)
        assert len(preview['proposals'])==2 and db.query(MarketplaceCatalogCard).count()==0
        payload=AutoApplyInput(fingerprint=preview['fingerprint'],match_by='ARTICLE')
        result=ozon_auto_apply(payload,SimpleNamespace(),db)
        assert result['linked']==2
        assert db.query(MarketplaceProductBarcode).count()==2
        assert db.get(MasterProduct, 1).name=='My product'
        with pytest.raises(HTTPException):
            ozon_auto_apply(payload,SimpleNamespace(),db)
