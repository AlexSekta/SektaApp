from decimal import Decimal
import unittest
from backend.services.marketplace_snapshot_service import normalized_dimensions, _data_state
from backend.models.marketplace_product_snapshot import MarketplaceProductSnapshot

class SnapshotNormalizationTests(unittest.TestCase):
    def test_mm_to_cm(self):
        dimensions, status = normalized_dimensions('277', '192', '81', 'mm')
        self.assertEqual((Decimal('27.7'), Decimal('19.2'), Decimal('8.1')), dimensions)
        self.assertEqual('VALID', status)

    def test_cm_kept(self):
        dimensions, status = normalized_dimensions(7, 7, 24, 'cm')
        self.assertEqual((Decimal(7), Decimal(7), Decimal(24)), dimensions)
        self.assertEqual('VALID', status)

    def test_unit_not_guessed(self):
        dims, status = normalized_dimensions(277, 192, 81, None)
        self.assertEqual((None, None, None), dims)
        self.assertEqual('INVALID_UNIT', status)

    def test_partial_not_completed(self):
        self.assertEqual('PARTIAL', normalized_dimensions(7, None, 24, 'cm')[1])

    def test_zero_invalid(self):
        self.assertEqual('UNKNOWN', normalized_dimensions(0, 5, 20, 'cm')[1])

    def test_missing(self):
        self.assertEqual('MISSING', normalized_dimensions(None, None, None, 'mm')[1])

    def test_snapshot_state_serializable(self):
        row = MarketplaceProductSnapshot(seller_article='HS061', title='Spray', description=None,
            barcodes_json='["123"]', platform_ids_json='{"sku":"1"}',
            dimension_unit='mm', dimension_state='VALID', length_raw=277, width_raw=192,height_raw=81)
        self.assertEqual(_data_state(row)['barcodes'], ['123'])

if __name__ == '__main__':
    unittest.main()

class SnapshotStorageTests(unittest.TestCase):
    def setUp(self):
        from sqlalchemy import create_engine
        from sqlalchemy.orm import sessionmaker
        from backend.models.marketplace_product_snapshot import MarketplaceProductSnapshot, MarketplaceProductSnapshotChange
        self.engine = create_engine('sqlite:///:memory:')
        # Clone PostgreSQL models without their PostgreSQL-only current_setting defaults.
        from sqlalchemy import MetaData
        md = MetaData()
        for model in (MarketplaceProductSnapshot, MarketplaceProductSnapshotChange):
            table = model.__table__.to_metadata(md)
            table.c.organization_id.server_default = None
        md.create_all(self.engine)
        self.db = sessionmaker(bind=self.engine)()

    def tearDown(self):
        self.db.close()
        self.engine.dispose()

    def test_change_logged_once_and_api_error_preserves_snapshot(self):
        from backend.services.marketplace_snapshot_service import save_snapshot
        from backend.models.marketplace_product_snapshot import MarketplaceProductSnapshot, MarketplaceProductSnapshotChange
        kwargs = dict(organization_id=2, marketplace='OZON', external_id='439269413',
                      seller_article='HS061', title='Nemochalka', barcodes=['Z', '123', '123'],
                      platform_ids={'sku': '840900401'}, dimensions=(277,192,81), dimension_unit='mm')
        row, changed = save_snapshot(self.db, **kwargs)
        self.assertTrue(changed)
        self.db.commit()
        self.assertEqual(row.length_cm, Decimal('27.7'))
        self.assertEqual(self.db.query(MarketplaceProductSnapshotChange).count(), 1)
        row, changed = save_snapshot(self.db, **kwargs)
        self.assertFalse(changed)
        self.db.commit()
        self.assertEqual(self.db.query(MarketplaceProductSnapshotChange).count(), 1)
        row, changed = save_snapshot(self.db, **{**kwargs, 'api_error': True})
        self.assertFalse(changed)
        self.db.commit()
        self.assertEqual(self.db.query(MarketplaceProductSnapshotChange).count(), 1)
        self.assertEqual(self.db.query(MarketplaceProductSnapshot).first().length_cm, Decimal('27.7'))
        row, changed = save_snapshot(self.db, **{**kwargs, 'dimensions': (280,192,81)})
        self.assertTrue(changed)
        self.db.commit()
        self.assertEqual(self.db.query(MarketplaceProductSnapshotChange).count(), 2)

    def test_tenant_identity_separation(self):
        from backend.services.marketplace_snapshot_service import save_snapshot
        from backend.models.marketplace_product_snapshot import MarketplaceProductSnapshot
        for oid in (2,3):
            save_snapshot(self.db, organization_id=oid, marketplace='OZON', external_id='1',
                          seller_article='HS001', dimensions=(1,2,3), dimension_unit='cm')
        self.db.commit()
        self.assertEqual(self.db.query(MarketplaceProductSnapshot).count(), 2)
