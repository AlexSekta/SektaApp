"""Mixed-market matching regressions. Offline SQLite, no marketplace writes."""
from types import SimpleNamespace
from unittest.mock import patch
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from backend.models.master_product import MasterProduct
from backend.models.marketplace_catalog_card import MarketplaceCatalogCard
from backend.models.marketplace_product_barcode import MarketplaceProductBarcode
from backend.models.catalog_sync_setting import CatalogSyncSetting
from backend.models.wb_identity import WBIdentityLink, WBIdentityReview
from backend.models.product import Product
from backend.services.catalog_bulk_match_27 import candidates
from backend.api.marketplace_catalog_import import all_auto_preview, all_auto_apply, AutoApplyInput
from fastapi import HTTPException
import pytest


def remote(market, article, external, barcode):
    return dict(marketplace=market, article=article, external_id=external,
                name='Remote', barcodes=[barcode],
                platform_ids={'id':external}, dimensions=None)


@pytest.fixture
def db():
    engine=create_engine('sqlite:///:memory:')
    models=(MasterProduct,MarketplaceCatalogCard,MarketplaceProductBarcode,
            CatalogSyncSetting,WBIdentityLink,WBIdentityReview,Product)
    for model in models:
        model.__table__.c.organization_id.server_default=None
        model.__table__.create(engine)
    with Session(engine) as session:
        session.add_all([
            MasterProduct(organization_id=2,id=1,seller_article='HS061',barcode='111',
                internal_article='HS061',name='Product',sort_order=1,group='G',
                purchase_price=10,additional_costs=0,active=True,status='SELLING'),
            MasterProduct(organization_id=2,id=2,seller_article='HS062',barcode='222',
                internal_article='HS062',name='Second',sort_order=2,group='G',
                purchase_price=10,additional_costs=0,active=True,status='SELLING'),
            Product(organization_id=2, marketplace='WB',nm_id='1111',seller_article='HS061'),
        ])
        session.commit()
        yield session
    engine.dispose()


def test_same_master_can_be_linked_on_multiple_platforms(db):
    rows=[remote('WB','HS061','1111','111'), remote('OZON','HS061','2222','333'),
          remote('YANDEX','HS061','offer-1','444')]
    by_market={m:candidates(db,[r],'ARTICLE',marketplace=m)[0] for m,r in
               [('WB',rows[0]),('OZON',rows[1]),('YANDEX',rows[2])]}
    assert all(len(x)==1 for x in by_market.values())
    assert {x[0]['master_id'] for x in by_market.values()}=={1}


def test_missing_wb_local_card_cannot_auto_link(db):
    proposals,excluded=candidates(db,[remote('WB','HS062','9999','222')],'ARTICLE',marketplace='WB')
    assert proposals==[] and excluded[0]['reason']=='WB_LOCAL_CARD_MISSING_OR_CONFLICT'


def test_duplicate_yandex_article_excluded(db):
    proposals,excluded=candidates(db,[remote('YANDEX','HS061','a','111'),
                 remote('YANDEX','HS061','b','111')],'ARTICLE',marketplace='YANDEX')
    assert len(proposals)==0 and len(excluded)==2


def test_wb_existing_identity_not_relinked(db):
    db.add(WBIdentityLink(organization_id=2,nm_id='1111',master_id=1,current_article='HS061'))
    db.commit()
    p,exc=candidates(db,[remote('WB','HS061','1111','111')],'ARTICLE',marketplace='WB')
    assert not p and exc[0]['reason']=='ALREADY_LINKED'


def test_preview_and_single_atomic_apply_across_three_markets(db):
    remotes={'WB':[remote('WB','HS061','1111','111')],
             'OZON':[remote('OZON','HS061','2222','333')],
             'YANDEX':[remote('YANDEX','HS061','offer-1','444')]}
    def read(db, market):return remotes[market]
    with patch('backend.api.marketplace_catalog_import.owner',return_value=SimpleNamespace(id=42)),\
         patch('backend.api.marketplace_catalog_import.org_id',return_value=2),\
         patch('backend.services.unified_catalog_sync_23.configured_markets',return_value=(list(remotes),[])),\
         patch('backend.api.marketplace_catalog_import.read_marketplace',side_effect=read):
        preview=all_auto_preview(SimpleNamespace(),db)
        assert preview['can_apply'] and len(preview['proposals'])==3
        assert db.query(MarketplaceCatalogCard).count()==0
        result=all_auto_apply(AutoApplyInput(fingerprint=preview['fingerprint'],match_by='ARTICLE'),SimpleNamespace(),db)
        assert result['linked']==3
        assert db.query(WBIdentityLink).count()==1
        assert db.query(MarketplaceCatalogCard).count()==2
        assert db.query(MarketplaceProductBarcode).count()==2
        with pytest.raises(HTTPException) as err:
            all_auto_apply(AutoApplyInput(fingerprint=preview['fingerprint'],match_by='ARTICLE'),SimpleNamespace(),db)
        assert err.value.status_code==409


def test_failed_market_blocks_apply(db):
    def read(db,market):
        if market=='YANDEX':raise RuntimeError('temporary error')
        return [remote(market,'HS061','1111' if market=='WB' else '2222','111')]
    with patch('backend.api.marketplace_catalog_import.owner',return_value=SimpleNamespace(id=42)),\
         patch('backend.api.marketplace_catalog_import.org_id',return_value=2),\
         patch('backend.services.unified_catalog_sync_23.configured_markets',return_value=(['WB','OZON','YANDEX'],[])),\
         patch('backend.api.marketplace_catalog_import.read_marketplace',side_effect=read):
        preview=all_auto_preview(SimpleNamespace(),db)
        assert preview['failed']==['YANDEX'] and not preview['can_apply']
        with pytest.raises(HTTPException):
            all_auto_apply(AutoApplyInput(fingerprint='fake',match_by='ARTICLE'),SimpleNamespace(),db)
        assert db.query(MarketplaceCatalogCard).count()==0
