"""Ozon barcode comparisons must not create identities or overwrite catalog values."""
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from backend.api.marketplace_catalog_import import classify
from backend.models.master_product import MasterProduct
from backend.models.marketplace_catalog_card import MarketplaceCatalogCard


def test_ozon_article_match_different_barcode_is_not_identity_conflict():
    engine = create_engine('sqlite:///:memory:')
    for model in (MasterProduct, MarketplaceCatalogCard):
        model.__table__.c.organization_id.server_default = None
        model.__table__.create(engine)
    with Session(engine) as db:
        db.add(MasterProduct(id=1, organization_id=2, internal_article='HS061',
                             seller_article='HS061', name='Товар', barcode='111',
                             group='Маркетплейс', purchase_price=0, additional_costs=0))
        db.commit()
        row = {'marketplace':'OZON', 'external_id':'439269413', 'article':'HS061',
               'name':'Товар на Ozon', 'barcodes':['222','333']}
        output = classify(db, [row])[0]
        assert output['status'] == 'MATCH'
        assert output['barcode_check'] == 'DIFFERENT'
        assert output['catalog_barcode'] == '111'
        assert db.query(MasterProduct).first().barcode == '111'
        assert db.query(MarketplaceCatalogCard).count() == 0
    engine.dispose()


def test_ozon_empty_catalog_barcode_is_distinct_from_different_barcode():
    engine = create_engine('sqlite:///:memory:')
    for model in (MasterProduct, MarketplaceCatalogCard):
        model.__table__.c.organization_id.server_default = None
        model.__table__.create(engine)
    with Session(engine) as db:
        db.add(MasterProduct(id=1, organization_id=2, internal_article='HS061',
                             seller_article='HS061', name='Товар', barcode=None,
                             group='Маркетплейс', purchase_price=0, additional_costs=0))
        db.commit()
        row = {'marketplace':'OZON', 'external_id':'439269413', 'article':'HS061',
               'name':'Товар', 'barcodes':['222']}
        output=classify(db,[row])[0]
        assert output['barcode_check']=='MISSING_IN_CATALOG'
        assert output['status']=='MATCH'
    engine.dispose()
