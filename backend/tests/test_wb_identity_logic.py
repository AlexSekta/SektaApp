"""Lightweight static/contract tests. Full integration requires test PostgreSQL."""
from pathlib import Path

def test_no_data_rewriting_in_approval():
    code=Path(__file__).resolve().parents[1].joinpath('api/wb_identity.py').read_text(encoding='utf-8')
    assert 'StockHistory' not in code
    assert 'MasterProduct(' not in code
    assert 'get_products()' in code

def test_wb_stocks_use_effective_link():
    code=Path(__file__).resolve().parents[1].joinpath('services/stock_service.py').read_text(encoding='utf-8')
    assert 'active_article(db, product)' in code
