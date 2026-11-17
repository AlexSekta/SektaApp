"""Read-only categorized summary of bulk marketplace match preview."""
from types import SimpleNamespace
from unittest.mock import patch
from backend.api.marketplace_catalog_import import _matching_report


def test_categorizes_by_marketplace_without_writes():
    db = SimpleNamespace(query=lambda model: SimpleNamespace(all=lambda: [
        SimpleNamespace(seller_article='HS061', barcode='111'),
        SimpleNamespace(seller_article='HS062', barcode='222')]))
    markets=['WB','OZON','YANDEX']
    data={'WB':[{'external_id':'w1','article':'HS061'}],
          'OZON':[{'external_id':'o1','article':'HS061'}, {'external_id':'o2','article':'HS099'}],
          'YANDEX':[{'external_id':'y1','article':'HS062'}]}
    proposed=[dict(marketplace='OZON',external_id='o1',article='HS061',master_id=1)]
    excluded=[dict(marketplace='WB',external_id='w1',article='HS061',reason='ALREADY_LINKED'),
              dict(marketplace='OZON',external_id='o2',article='HS099',reason='NO_UNIQUE_CATALOG_ARTICLE'),
              dict(marketplace='YANDEX',external_id='y1',article='HS062',reason='DUPLICATE_REMOTE_ARTICLE')]
    report=_matching_report(db,markets,data,proposed,excluded,'ARTICLE',[])
    assert report['operation_count']==1
    assert report['by_marketplace']['WB']['already_linked']==1
    assert report['by_marketplace']['OZON']['new_links']==1
    assert report['by_marketplace']['OZON']['new_products']==1
    assert report['by_marketplace']['YANDEX']['needs_review']==1
    assert sum(report['by_marketplace']['OZON'][k] for k in ('new_links','already_linked','new_products','needs_review'))==2
    assert [x['category'] for x in report['excluded_details']]==['ALREADY_LINKED','NEW_PRODUCT','NEEDS_REVIEW']


def test_failed_market_is_marked_and_not_counted_as_zero():
    db = SimpleNamespace(query=lambda model: SimpleNamespace(all=lambda: []))
    report=_matching_report(db,['OZON','WB'],{'WB':[]},[],[],'ARTICLE',['OZON'])
    assert report['by_marketplace']['OZON']['received'] is None
    assert report['by_marketplace']['OZON']['api_error'] is True


def test_barcode_without_match_but_existing_article_needs_review():
    db = SimpleNamespace(query=lambda model: SimpleNamespace(all=lambda: [
        SimpleNamespace(seller_article='HS061', barcode='111')]))
    excluded=[dict(marketplace='OZON',external_id='o1',article='HS061',reason='NO_UNIQUE_CATALOG_BARCODE')]
    report=_matching_report(db,['OZON'],{'OZON':[{'external_id':'o1','article':'HS061','barcodes':['999']}]},[],excluded,'BARCODE',[])
    assert report['by_marketplace']['OZON']['new_products']==0
    assert report['by_marketplace']['OZON']['needs_review']==1
