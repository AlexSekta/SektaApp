from decimal import Decimal
import pytest
from patch41_restore.wb_finance_restore_511856341 import to_values, totals_for_raw

def test_api_mapping_and_negative_return():
    rows=[{'rrdId':1,'docTypeName':'Продажа','retailAmount':100,'forPay':80},
          {'rrdId':2,'docTypeName':'Возврат','retailAmount':25,'forPay':20}]
    v=totals_for_raw(rows)
    assert v['retail']==Decimal('75')
    assert v['for_pay']==Decimal('60')
    assert to_values(rows[1])['doc_type']=='Возврат'

def test_duplicate_rrd_invalid():
    with pytest.raises(ValueError):
        to_values({'rrdId':0})

def test_row_fields():
    v=to_values({'rrdId':11,'nmId':345,'retailAmount':'12.50','deliveryService':3})
    assert v['id']==11 and v['nm']=='345'
    assert v['ret']==Decimal('12.50') and v['log']==Decimal('3')
    assert v['o']==2 and v['r']==511856341
