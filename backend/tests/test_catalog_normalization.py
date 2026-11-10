import unittest
from backend.services.marketplace_catalog_import import normalize_wb, normalize_ozon, normalize_yandex

class CatalogMappingTests(unittest.TestCase):
    def test_wb_card(self):
        c=normalize_wb({'nmID':1840650707,'vendorCode':'HS218','title':'Смывка','sizes':[{'skus':['4610240935336']}],
                        'dimensions':{'length':21,'width':12,'height':8}})
        self.assertEqual(c['external_id'],'1840650707')
        self.assertEqual(c['barcodes'],['4610240935336'])
        self.assertEqual(c['dimensions']['length_cm'],21)
    def test_ozon_product(self):
        c=normalize_ozon({'id':123,'offer_id':'HS218','name':'Товар','barcodes':['123456'],
                          'dimension_unit':'mm','depth':200,'width':100,'height':50})
        self.assertEqual(c['external_id'],'123')
        self.assertEqual(c['dimensions'],{'length_cm':20.0,'width_cm':10.0,'height_cm':5.0})
    def test_ozon_no_guessed_units(self):
        c=normalize_ozon({'id':123,'offer_id':'HS218','depth':200,'width':100,'height':50})
        self.assertIsNone(c['dimensions'])
    def test_yandex_offer(self):
        c=normalize_yandex({'offer':{'offerId':'HS218','name':'Смывка','barcodes':['4610240935336'],
                    'weightDimensions':{'length':20,'width':10,'height':7}},'mapping':{'marketSku':111}})
        self.assertEqual(c['platform_ids']['marketSku'],'111')
        self.assertEqual(c['dimensions']['height_cm'],7)

if __name__=='__main__': unittest.main()
