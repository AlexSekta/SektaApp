"""SQLite-only checks: Ozon matching must not mutate manually maintained catalog data."""
from types import SimpleNamespace
from unittest.mock import patch
import pytest
from fastapi import HTTPException
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from backend.models.master_product import MasterProduct
from backend.models.marketplace_catalog_card import MarketplaceCatalogCard
from backend.models.marketplace_product_barcode import MarketplaceProductBarcode
from backend.api.marketplace_catalog_import import (
    ozon_link_preview, ozon_link_batch, OzonLinkBatch, OzonLinkSelected)


@pytest.fixture
def fixture_db():
    engine = create_engine('sqlite:///:memory:')
    for model in [MasterProduct, MarketplaceCatalogCard, MarketplaceProductBarcode]:
        model.__table__.c.organization_id.server_default = None
        model.__table__.create(engine)
    with Session(engine) as db:
        p = MasterProduct(organization_id=2, id=12, sort_order=1, seller_article='HS061',
                          internal_article='HS061', name='Название вручную', barcode='OURBAR',
                          length_cm=20, width_cm=7, height_cm=6, purchase_price=100,
                          additional_costs=12, group='Готовая продукция', status='SELLING',
                          active=True, ozon_enabled=False)
        db.add(p)
        db.commit()
        yield db
    engine.dispose()


def remote(barcodes=None, article='HS061'):
    return [{'marketplace': 'OZON', 'external_id': '439269413', 'article': article,
             'name': 'Название Ozon', 'barcodes': barcodes if barcodes is not None else
             ['4673733298233', 'OZN840900401'], 'dimensions': None,
             'platform_ids': {'product_id': '439269413', 'sku': '840900401'}}]


def ctx(db, cards):
    return (patch('backend.api.marketplace_catalog_import.owner', return_value=None),
            patch('backend.api.marketplace_catalog_import.org_id', return_value=2),
            patch('backend.api.marketplace_catalog_import.read_marketplace', return_value=cards))


def make_payload(preview):
    c = preview['proposals'][0]
    return OzonLinkBatch(fingerprint=preview['fingerprint'], items=[
        OzonLinkSelected(external_id=c['external_id'], article=c['article'], master_id=c['master_id'])])


def test_ozon_preview_is_read_only(fixture_db):
    db = fixture_db
    a, b, c = ctx(db, remote())
    with a, b, c:
        result = ozon_link_preview(SimpleNamespace(), db)
    assert len(result['proposals']) == 1
    assert result['read_only']
    assert db.query(MarketplaceCatalogCard).count() == 0
    assert db.query(MarketplaceProductBarcode).count() == 0


def test_ozon_confirm_links_only_and_saves_all_barcodes(fixture_db):
    db = fixture_db
    a, b, c = ctx(db, remote())
    with a, b, c:
        preview = ozon_link_preview(SimpleNamespace(), db)
        result = ozon_link_batch(make_payload(preview), SimpleNamespace(), db)
    assert result['linked'] == 1
    m = db.query(MasterProduct).one()
    assert (m.name, m.barcode, m.status, m.active, m.ozon_enabled) == (
        'Название вручную', 'OURBAR', 'SELLING', True, False)
    assert (float(m.length_cm), float(m.purchase_price)) == (20.0, 100.0)
    link = db.query(MarketplaceCatalogCard).one()
    assert (link.marketplace, link.external_id, link.master_id) == ('OZON', '439269413', 12)
    bars = sorted(x.barcode for x in db.query(MarketplaceProductBarcode).all())
    assert bars == ['4673733298233', 'OZN840900401']
    with a, b, c:
        with pytest.raises(HTTPException) as exc:
            ozon_link_batch(make_payload(preview), SimpleNamespace(), db)
    assert exc.value.status_code == 409
    assert db.query(MarketplaceCatalogCard).count() == 1


def test_ozon_remote_changes_stop_confirmation(fixture_db):
    db = fixture_db
    a, b, c = ctx(db, remote())
    with a, b, c:
        preview = ozon_link_preview(SimpleNamespace(), db)
    a, b, c = ctx(db, remote(barcodes=['OTHER']))
    with a, b, c:
        with pytest.raises(HTTPException) as exc:
            ozon_link_batch(make_payload(preview), SimpleNamespace(), db)
    assert exc.value.status_code == 409
    assert db.query(MarketplaceCatalogCard).count() == 0


def test_ozon_wrong_catalog_target_rejected(fixture_db):
    db = fixture_db
    a, b, c = ctx(db, remote())
    with a, b, c:
        preview = ozon_link_preview(SimpleNamespace(), db)
        payload = make_payload(preview)
        payload.items[0].master_id = 99
        with pytest.raises(HTTPException) as exc:
            ozon_link_batch(payload, SimpleNamespace(), db)
    assert exc.value.status_code == 409


def test_other_article_not_offered(fixture_db):
    db = fixture_db
    a, b, c = ctx(db, remote(article='OTHER'))
    with a, b, c:
        preview = ozon_link_preview(SimpleNamespace(), db)
    assert not preview['proposals']
    assert len(preview['excluded']) == 1


def test_duplicate_ozon_article_not_mass_linked(fixture_db):
    db = fixture_db
    rows = remote() + [{**remote()[0], 'external_id': 'OTHER-ID',
                        'platform_ids': {'product_id': 'OTHER-ID', 'sku': 'X'}}]
    a, b, c = ctx(db, rows)
    with a, b, c:
        preview = ozon_link_preview(SimpleNamespace(), db)
    assert not preview['proposals']
    assert len(preview['excluded']) == 2
