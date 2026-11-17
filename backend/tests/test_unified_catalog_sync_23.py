from unittest.mock import MagicMock, patch
from backend.models.auth import Organization
from backend.services.unified_catalog_sync_23 import configured_markets, snapshot_values, sync_connected_catalogs


def test_enabled_with_credentials_only():
    db = MagicMock()
    db.query.return_value.all.return_value = [
        type('C', (), {'marketplace':'WB', 'enabled':True, 'credentials_encrypted':'encrypted'})(),
        type('C', (), {'marketplace':'OZON', 'enabled':False, 'credentials_encrypted':'encrypted'})(),
        type('C', (), {'marketplace':'YANDEX', 'enabled':True, 'credentials_encrypted':None})(),
    ]
    enabled, skipped = configured_markets(db)
    assert enabled == ['WB']
    assert {r['marketplace']:r['reason'] for r in skipped} == {'OZON':'DISABLED','YANDEX':'NO_CREDENTIALS'}


def test_ozon_native_mm_preserved():
    row = {'marketplace':'OZON','dimensions':{'length_cm':27.7,'width_cm':19.2,'height_cm':8.1},
           'dimension_native':{'values':[277,192,81],'unit':'mm'}}
    assert snapshot_values(row) == ((277,192,81),'mm')


def test_error_does_not_erase_existing_snapshot():
    row = {'marketplace':'OZON','dimension_fetch_status':'API_ERROR'}
    assert snapshot_values(row) is None


def test_safe_marketplace_commit_and_failed_source_rollback():
    db = MagicMock()
    data = [{'marketplace':'WB','external_id':'100','article':'HS001','name':'Test',
             'dimensions':{'length_cm':2,'width_cm':3,'height_cm':4}, 'barcodes':[],'platform_ids':{}}]
    with patch('backend.services.unified_catalog_sync_23.configured_markets',return_value=(['WB','OZON'],[])),\
         patch('backend.services.unified_catalog_sync_23.save_snapshot',return_value=(None,True)) as save:
        result=sync_connected_catalogs(db,organization_id=2,reader=lambda db,mp:data if mp=='WB' else (_ for _ in ()).throw(ValueError('unavailable')))
    assert [x['status'] for x in result['marketplaces']] == ['OK','ERROR']
    assert db.commit.call_count == 1 and db.rollback.call_count == 1
    assert save.call_args.kwargs['organization_id'] == 2


def test_bad_remote_duplicate_ids_abort_market_before_writes():
    db=MagicMock()
    with patch('backend.services.unified_catalog_sync_23.configured_markets',return_value=(['WB'],[])),\
         patch('backend.services.unified_catalog_sync_23.save_snapshot') as save:
        result=sync_connected_catalogs(db,organization_id=2,reader=lambda db,mp:[{'external_id':'1'},{'external_id':'1'}])
    assert result['marketplaces'][0]['status']=='ERROR'
    save.assert_not_called()
