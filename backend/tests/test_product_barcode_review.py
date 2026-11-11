from types import SimpleNamespace
import pytest
from fastapi import HTTPException
from backend.api.wb_identity import _barcode_snapshot, _barcode_fingerprint


def test_empty_catalog_barcode_can_be_filled_from_wb():
    master = SimpleNamespace(id=95, barcode=None)
    snapshot = _barcode_snapshot(master, 'HS226', '1970294237', ['4610240935374'], '4610240935374')
    assert snapshot['catalog_barcode'] == ''
    assert snapshot['new_barcode'] == '4610240935374'


def test_barcode_must_be_one_of_current_wb_values():
    master = SimpleNamespace(id=95, barcode='12345')
    with pytest.raises(HTTPException) as exc:
        _barcode_snapshot(master, 'HS226', '1970294237', ['4610240935374'], '1111111111111')
    assert exc.value.status_code == 409


def test_no_barcodes_on_wb_fails_closed():
    master = SimpleNamespace(id=95, barcode=None)
    with pytest.raises(HTTPException) as exc:
        _barcode_snapshot(master, 'HS226', '1970294237', [], '4610240935374')
    assert exc.value.status_code == 409


def test_snapshot_fingerprint_includes_original_barcode():
    a = _barcode_snapshot(SimpleNamespace(id=95, barcode='123'), 'HS226', '1970294237', ['4610240935374'], '4610240935374')
    b = _barcode_snapshot(SimpleNamespace(id=95, barcode='456'), 'HS226', '1970294237', ['4610240935374'], '4610240935374')
    assert _barcode_fingerprint(a) != _barcode_fingerprint(b)


def test_multivalue_sku_requires_explicit_selection():
    master = SimpleNamespace(id=95, barcode=None)
    values = ['4610240935374', '4610240935375']
    assert _barcode_snapshot(master, 'HS226', '1970294237', values, values[1])['new_barcode'] == values[1]
