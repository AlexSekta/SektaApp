import os
os.environ.setdefault('DATABASE_URL', 'sqlite://')
import pytest
from backend.services.ozon_fbs_sticker_monitor_43 import parse_detail_identifiers, detail_posting


def test_exact_posting_and_codes():
    data = parse_detail_identifiers({'result': {'posting_number':'0136766041-0010-1',
        'status':'awaiting_deliver', 'scanit':'ii50243803131',
        'barcodes':{'upper_barcode':'202440612902000','lower_barcode':'202440612902000'}}},
        '0136766041-0010-1')
    assert data['scanit'] == 'ii50243803131'
    assert data['upper_barcode'] == data['lower_barcode']


def test_other_posting_rejected():
    with pytest.raises(ValueError, match='mismatch'):
        parse_detail_identifiers({'result':{'posting_number':'wrong'}},'expected')


def test_detail_read_only_and_payload():
    class Client:
        def post_raw(self, path, payload):
            assert path == '/v3/posting/fbs/get'
            assert payload['posting_number'] == 'test-1'
            assert payload['with']['barcodes'] is True
            return {'status_code':200,'body':{'result':{'posting_number':'test-1','scanit':'ii123'}}}
    assert detail_posting(Client(),'test-1')['scanit'] == 'ii123'


def test_invalid_barcodes_rejected():
    with pytest.raises(ValueError):
        parse_detail_identifiers({'result':{'posting_number':'p','barcodes':['wrong']}},'p')
