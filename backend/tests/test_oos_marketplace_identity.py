"""Run: python -m unittest backend.tests.test_oos_marketplace_identity -v"""
import unittest
from datetime import date, datetime, timedelta

from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from backend.database import Base
from backend.models.master_product import MasterProduct
from backend.models.product import Product
from backend.models.stock_history import StockHistory
from backend.models.wb_identity import WBIdentityLink
from backend.services.out_of_stock_service import calculate_out_of_stock, current_oos_details


class OOSIdentityTests(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine('sqlite:///:memory:')
        # PostgreSQL RLS session defaults are not valid SQLite DDL.
        for table in (MasterProduct.__table__, Product.__table__, StockHistory.__table__, WBIdentityLink.__table__):
            if table.c.organization_id.server_default is not None:
                table.c.organization_id.server_default = None
        Base.metadata.create_all(self.engine, tables=[
            MasterProduct.__table__, Product.__table__, StockHistory.__table__, WBIdentityLink.__table__,
        ])
        self.db = Session(self.engine)
        self.db.add_all([
            MasterProduct(id=10, organization_id=2, seller_article='HS066', name='Old', active=True, wb_enabled=True, ozon_enabled=True, yandex_enabled=True),
            MasterProduct(id=93, organization_id=2, seller_article='HS219', name='New', active=True, wb_enabled=False, ozon_enabled=False, yandex_enabled=False),
            MasterProduct(id=94, organization_id=2, seller_article='HS225', name='ROVNO', active=True),
            MasterProduct(id=95, organization_id=2, seller_article='HS999', name='No marketplace', active=True),
        ])
        self.db.add_all([
            Product(id=455, organization_id=2, marketplace='WB', nm_id='151451408', seller_article='HS219'),
            Product(id=523, organization_id=2, marketplace='WB', nm_id='1933851521', seller_article='WB_RETIRED:1933851521'),
            Product(id=524, organization_id=2, marketplace='WB', nm_id='1970402141', seller_article='HS225'),
            WBIdentityLink(organization_id=2, nm_id='151451408', master_id=93, current_article='HS219'),
            WBIdentityLink(organization_id=2, nm_id='1970402141', master_id=94, current_article='HS225'),
        ])
        day = date.today() - timedelta(days=2)
        self.db.add_all([
            StockHistory(organization_id=2, date=day, marketplace='WB', warehouse_id='w1', warehouse_name='w1', warehouse_type='SELLER', seller_article='HS066', nm_id='151451408', sku='sku1', stock=10, created_at=datetime.combine(day, datetime.min.time())),
            StockHistory(organization_id=2, date=date.today(), marketplace='WB', warehouse_id='w1', warehouse_name='w1', warehouse_type='SELLER', seller_article='HS219', nm_id='151451408', sku='sku1', stock=0, created_at=datetime.utcnow()),
            StockHistory(organization_id=2, date=date.today(), marketplace='WB', warehouse_id='w2', warehouse_name='w2', warehouse_type='SELLER', seller_article='HS225', nm_id='1970402141', sku='sku2', stock=4, created_at=datetime.utcnow()),
            StockHistory(organization_id=2, date=date.today(), marketplace='OZON', warehouse_id='w3', warehouse_name='w3', warehouse_type='FBS', seller_article='HS066', nm_id='0', sku='sku3', stock=0, created_at=datetime.utcnow()),
        ])
        self.db.commit()

    def tearDown(self):
        self.db.close()
        self.engine.dispose()

    def test_dash_is_excluded_and_wb_nm_id_is_used(self):
        result = calculate_out_of_stock(self.db)
        self.assertEqual(result['marketplaces']['WB']['total_products'], 2)
        self.assertEqual(result['marketplaces']['WB']['zero_products'], 1)
        wb = current_oos_details(self.db, 'WB')
        self.assertEqual([row['article'] for row in wb['items']], ['HS219'])
        self.assertEqual(wb['items'][0]['days_oos'], 1)
        self.assertEqual(result['marketplaces']['OZON']['total_products'], 1)
        self.assertEqual(result['marketplaces']['YANDEX']['total_products'], 1)
        self.assertEqual(result['total_positions'], 4)
        self.assertEqual(result['overall']['zero_products'], 3)
        self.assertNotIn('HS066', [row['article'] for row in wb['items']])

    def test_empty_marketplace_has_no_false_oos(self):
        self.db.query(WBIdentityLink).delete()
        self.db.query(Product).delete()
        self.db.query(StockHistory).delete()
        for product in self.db.query(MasterProduct):
            product.wb_enabled = False
            product.ozon_enabled = False
            product.yandex_enabled = False
        self.db.commit()
        result = calculate_out_of_stock(self.db)
        self.assertEqual(result['overall']['total_positions'], 0)
        self.assertEqual(result['overall']['percent'], 0.0)
        self.assertEqual(current_oos_details(self.db, 'WB')['count'], 0)


if __name__ == '__main__':
    unittest.main()
