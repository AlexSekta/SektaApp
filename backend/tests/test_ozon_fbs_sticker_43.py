import os
os.environ.setdefault('DATABASE_URL','sqlite://')
from unittest.mock import Mock
import pytest
from backend.services.ozon_fbs_sticker_monitor_43 import (
    normalize_list,parse_task,parse_task_status,allowed_pdf_url,download_pdf,
)

def test_list_v4_and_bad_pagination():
    assert normalize_list({'postings':[{'posting_number':'p'}],'has_next':False})[0][0]['posting_number']=='p'
    with pytest.raises(ValueError):normalize_list({'result':{}})

def test_task_prefers_small_sticker_and_rejects_missing():
    assert parse_task({'tasks':[{'task_id':1,'task_type':'big_label'},{'task_id':2,'task_type':'small_label'}]})==(2,'small_label')
    with pytest.raises(ValueError):parse_task({'tasks':[]})

def test_status_new_and_legacy():
    assert parse_task_status({'status':{'code':'pending'}})==('pending',None)
    assert parse_task_status({'status':{'code':'completed','unprinted_postings':[]},'file_url':'https://x.ozon.ru/f.pdf'})[0]=='completed'
    with pytest.raises(ValueError):parse_task_status({'status':{'code':'completed','unprinted_postings':['p']},'file_url':'https://x.ozon.ru/f.pdf'})

def test_no_arbitrary_pdf_urls(monkeypatch):
    monkeypatch.delenv('OZON_FBS_LABEL_HOST_SUFFIXES',raising=False)
    assert allowed_pdf_url('https://storage.ozon.ru/test.pdf')
    for url in ['http://ozon.ru/file.pdf','https://ozon.ru.attacker.invalid/a','https://127.0.0.1/x','https://user@ozon.ru/x']:
        assert not allowed_pdf_url(url)

def test_download_requires_pdf_and_size(monkeypatch):
    response=Mock(status_code=200)
    response.iter_content.return_value=[b'%PDF-1.4\nhello']
    monkeypatch.setattr('backend.services.ozon_fbs_sticker_monitor_43.requests.get',lambda *a,**kw: response)
    assert download_pdf('https://test.ozon.ru/a.pdf').startswith(b'%PDF-')
    response.close.assert_called()
    response.iter_content.return_value=[b'not pdf']
    with pytest.raises(ValueError):download_pdf('https://test.ozon.ru/a.pdf')
