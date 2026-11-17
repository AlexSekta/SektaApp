"""SQL sign-rule regression tests; no application DB or WB API calls."""
import sqlite3
from decimal import Decimal
from backend.services.wb_finance_doc_type_32 import signed


def amount(operation, doc_type, for_pay):
    db=sqlite3.connect(':memory:')
    db.create_function('btrim',1,lambda s: (s or '').strip())
    db.create_function('lower',1,lambda s: (s or '').lower())
    db.execute('CREATE TABLE entries (operation text,doc_type text,for_pay numeric,retail numeric)')
    db.execute('INSERT INTO entries VALUES (?,?,?,0)', (operation,doc_type,for_pay))
    result = db.execute(f'SELECT {signed("for_pay")} FROM entries').fetchone()[0]
    db.close()
    return Decimal(str(result))


def test_official_wb_05_nov_correction_with_return_doc_type():
    assert amount('Коррекция продаж','Возврат',52.51) == Decimal('-52.51')


def test_sale_correction_must_stay_positive():
    assert amount('Коррекция продаж','Продажа',52.51) == Decimal('52.51')


def test_legacy_return_without_doc_type_still_negative():
    assert amount('Возврат',None,52.51) == Decimal('-52.51')


def test_explicit_doc_type_overrides_operation():
    assert amount('Возврат','Продажа',52.51) == Decimal('52.51')
