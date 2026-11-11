"""Read-only catalog preview respects WB confirmations from both workflows."""
import unittest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from backend.models.master_product import MasterProduct
from backend.models.wb_identity import WBIdentityLink
from backend.models.marketplace_catalog_card import MarketplaceCatalogCard
from backend.api.marketplace_catalog_import import classify


class PreviewIdentityTests(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine('sqlite:///:memory:')
        for model in (MasterProduct, WBIdentityLink, MarketplaceCatalogCard):
            model.__table__.c.organization_id.server_default = None
            model.__table__.create(self.engine)
        self.db = Session(self.engine)
        self.db.add_all([
            MasterProduct(id=11, organization_id=2, seller_article='HS044', internal_article='HS044', name='Existing', group='Маркетплейс', purchase_price=0, additional_costs=0),
            MasterProduct(id=12, organization_id=2, seller_article='HS045', internal_article='HS045', name='Other', group='Маркетплейс', purchase_price=0, additional_costs=0),
        ])
        self.db.commit()

    def tearDown(self):
        self.db.close()
        self.engine.dispose()

    @staticmethod
    def row(market='WB', ext='123', article='HS044'):
        return dict(marketplace=market, external_id=ext, article=article, name='Product')

    def test_legacy_confirmed_identity_is_linked(self):
        self.db.add(WBIdentityLink(organization_id=2, nm_id='123', master_id=11, current_article='HS044'))
        self.db.commit()
        result = classify(self.db, [self.row()])[0]
        self.assertEqual((result['status'],result['master_id']), ('LINKED',11))
        self.assertEqual(result['conflict_reason'],None)

    def test_missing_identity_is_only_article_match(self):
        result = classify(self.db, [self.row()])[0]
        self.assertEqual((result['status'],result['master_id']), ('MATCH',11))

    def test_disagreement_blocks_import(self):
        self.db.add(WBIdentityLink(organization_id=2,nm_id='123', master_id=11,current_article='HS044'))
        self.db.add(MarketplaceCatalogCard(organization_id=2,marketplace='WB',external_id='123',seller_article='HS044',master_id=12))
        self.db.commit()
        result = classify(self.db,[self.row()])[0]
        self.assertEqual(result['status'],'CONFLICT')
        self.assertEqual(result['conflict_reason'],'IDENTITY_DISAGREEMENT')

    def test_article_change_requires_review(self):
        self.db.add(WBIdentityLink(organization_id=2,nm_id='123', master_id=11,current_article='HS044'))
        self.db.commit()
        result=classify(self.db,[self.row(article='HS045')])[0]
        self.assertEqual(result['status'],'CONFLICT')
        self.assertEqual(result['master_id'],11)

    def test_ozon_ignores_wb_confirmations(self):
        self.db.add(WBIdentityLink(organization_id=2,nm_id='123', master_id=11,current_article='HS044'))
        self.db.commit()
        result=classify(self.db,[self.row('OZON','123')])[0]
        self.assertEqual(result['status'],'MATCH')

    def test_generic_confirmed_identity_remains_linked(self):
        self.db.add(MarketplaceCatalogCard(organization_id=2,marketplace='OZON',external_id='456',seller_article='HS044',master_id=11))
        self.db.commit()
        result=classify(self.db,[self.row('OZON','456')])[0]
        self.assertEqual(result['status'],'LINKED')

class ImportLegacyGuardTests(PreviewIdentityTests):
    def test_import_does_not_recreate_existing_legacy_link(self):
        from unittest.mock import patch
        from types import SimpleNamespace
        from backend.api.marketplace_catalog_import import import_one, ImportOne
        self.db.add(WBIdentityLink(organization_id=2, nm_id='123', master_id=11, current_article='HS044'))
        self.db.commit()
        request=SimpleNamespace(state=SimpleNamespace(organization_id=2))
        with patch('backend.api.marketplace_catalog_import.owner',return_value=None), patch('backend.api.marketplace_catalog_import.org_id',return_value=2), patch('backend.api.marketplace_catalog_import.read_marketplace',return_value=[self.row()]):
            result=import_one('WB',ImportOne(external_id='123',article='HS044'),request,self.db)
        self.assertEqual(result['status'],'already_linked')
        self.assertEqual(result['master_id'],11)
        self.assertEqual(self.db.query(MarketplaceCatalogCard).count(),0)
