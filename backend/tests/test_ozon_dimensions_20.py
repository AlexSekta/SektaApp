"""Read-only Ozon dimensions reconciliation regressions."""
from backend.services.marketplace_catalog_import import (
    normalize_ozon, enrich_ozon_dimensions, ozon_package_dimensions,
)


def _card(**updates):
    return dict(id=439269413, offer_id='HS061', name='Sample', barcodes=['123'], **updates)


def test_mm_conversion():
    row = normalize_ozon(_card(depth=110, width=90, height=80, dimension_unit='mm'))
    assert row['dimensions'] == dict(length_cm=11, width_cm=9, height_cm=8)
    assert row['dimension_fetch_status'] == 'OK'


def test_cm_and_inches_are_not_assumed_mm():
    cm, state = ozon_package_dimensions(_card(depth=11, width=9, height=8, dimension_unit='cm'))
    assert cm['length_cm'] == 11 and state == 'OK'
    inches, state = ozon_package_dimensions(_card(depth=1, width=2, height=3, dimension_unit='in'))
    assert inches['length_cm'] == 2.54 and state == 'OK'


def test_missing_unit_never_guessed():
    dimensions, state = ozon_package_dimensions(_card(depth=110, width=90, height=80))
    assert dimensions is None and state == 'MISSING_UNIT'


def test_attributes_fill_missing_dimensions_read_only():
    class Client:
        def post(self, path, payload):
            assert path == '/v4/product/info/attributes'
            assert payload['filter']['product_id'] == [439269413]
            return {'result':[dict(id=439269413, depth=110, width=90, height=80, dimension_unit='mm')]}
    row = normalize_ozon(_card())
    enrich_ozon_dimensions(Client(), [row])
    assert row['dimensions'] == dict(length_cm=11, width_cm=9, height_cm=8)
    assert row['dimension_source'] == 'v4/product/info/attributes'


def test_api_failure_is_not_misreported_as_missing_data():
    class Client:
        def post(self, *args, **kwargs):
            raise TimeoutError('timeout')
    row = normalize_ozon(_card())
    enrich_ozon_dimensions(Client(), [row])
    assert row['dimensions'] is None
    assert row['dimension_fetch_status'] == 'API_ERROR'


def test_partial_dimensions_not_accepted():
    dims, state = ozon_package_dimensions(_card(depth=110, width=90, height=0, dimension_unit='mm'))
    assert dims is None and state == 'MISSING_VALUES'
