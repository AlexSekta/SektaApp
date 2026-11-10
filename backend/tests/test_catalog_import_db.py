"""SQLite isolated smoke tests for catalog import; never connects to user PostgreSQL."""
import unittest
from unittest.mock import patch
from types import SimpleNamespace
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from backend.models.master_product import MasterProduct
from backend.models.product import Product
from backend.models.wb_identity import WBIdentityLink
from backend.models.marketplace_catalog_card import MarketplaceCatalogCard
from backend.api.marketplace_catalog_import import import_one, import_batch, ImportOne, ImportBatch

class ImportTests(unittest.TestCase):
    def setUp(self):
        self.engine=create_engine('sqlite:///:memory:')
        for model in [MasterProduct, Product, WBIdentityLink, MarketplaceCatalogCard]:
            # PostgreSQL-specific current_setting() default is not available in SQLite.
            model.__table__.c.organization_id.server_default = None
            model.__table__.create(self.engine)
        self.db=Session(self.engine)
        self.request=SimpleNamespace(state=SimpleNamespace(organization_id=2))
    def tearDown(self):
        self.db.close();self.engine.dispose()
    def card(self):
        return [{'marketplace':'WB','external_id':'1840650707','article':'HS218',
                 'name':'Безопасная смывка','barcodes':['4610240935336'],
                 'dimensions':{'length_cm':12,'width_cm':8,'height_cm':5},
                 'platform_ids':{'nmID':'1840650707'}}]
    def test_new_product_stays_inactive(self):
        with patch('backend.api.marketplace_catalog_import.owner',return_value=None), patch('backend.api.marketplace_catalog_import.org_id',return_value=2), patch('backend.api.marketplace_catalog_import.read_marketplace',return_value=self.card()):
            result=import_one('WB',ImportOne(external_id='1840650707',article='HS218'),self.request,self.db)
            self.assertEqual(result['status'],'imported')
            p=self.db.query(MasterProduct).first()
            self.assertEqual((p.status,p.active,p.wb_enabled),('READY',False,True))
            self.assertEqual(p.name,'Безопасная смывка')
            self.assertEqual(float(p.length_cm),12)
            self.assertEqual(self.db.query(WBIdentityLink).count(),1)
            second=import_one('WB',ImportOne(external_id='1840650707',article='HS218'),self.request,self.db)
            self.assertEqual(second['status'],'already_linked')
            self.assertEqual(self.db.query(MasterProduct).count(),1)
    def test_batch_atomicity_and_two_new_cards(self):
        rows=self.card()+[{'marketplace':'WB','external_id':'1970402141','article':'HS225',
            'name':'Спрей ROVNO','barcodes':['4610240935367'],'dimensions':None,
            'platform_ids':{'nmID':'1970402141'}}]
        with patch('backend.api.marketplace_catalog_import.owner',return_value=None), patch('backend.api.marketplace_catalog_import.org_id',return_value=2), patch('backend.api.marketplace_catalog_import.read_marketplace',return_value=rows):
            bad=ImportBatch(items=[ImportOne(external_id='1840650707',article='HS218'),
                                   ImportOne(external_id='1970402141',article='WRONG')])
            from fastapi import HTTPException
            with self.assertRaises(HTTPException):
                import_batch('WB',bad,self.request,self.db)
            self.assertEqual(self.db.query(MasterProduct).count(),0)
            good=ImportBatch(items=[ImportOne(external_id='1840650707',article='HS218'),
                                    ImportOne(external_id='1970402141',article='HS225')])
            result=import_batch('WB',good,self.request,self.db)
            self.assertEqual(result['count'],2)
            self.assertEqual(self.db.query(MasterProduct).count(),2)
            self.assertEqual(self.db.query(MarketplaceCatalogCard).count(),2)
    def test_existing_manual_fields_preserved(self):
        existing=MasterProduct(organization_id=2,id=93,sort_order=1,
            seller_article='HS218',internal_article='HS218',name='Название вручную',
            barcode='MYBAR',purchase_price=234,status='ARCHIVE',active=False,wb_enabled=False,
            length_cm=30,width_cm=20,height_cm=10,group='Маркетплейс')
        self.db.add(existing);self.db.commit()
        with patch('backend.api.marketplace_catalog_import.owner',return_value=None), patch('backend.api.marketplace_catalog_import.org_id',return_value=2), patch('backend.api.marketplace_catalog_import.read_marketplace',return_value=self.card()):
            import_one('WB',ImportOne(external_id='1840650707',article='HS218',master_id=93),self.request,self.db)
        self.db.refresh(existing)
        self.assertEqual((existing.name,existing.barcode,float(existing.purchase_price),existing.status,float(existing.length_cm)),
                         ('Название вручную','MYBAR',234,'ARCHIVE',30))

if __name__=='__main__': unittest.main()
