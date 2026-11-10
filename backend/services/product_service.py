"""WB product catalog upsert. Keep master products and stock history untouched."""
from datetime import datetime
from sqlalchemy.orm import Session
from backend.models.product import Product
from backend.services.wb_identity_service import observe


def save_products(db: Session, cards):
    saved = 0
    for card in cards:
        article = str(card.get("vendorCode") or "").strip()
        nm_id = str(card.get("nmID") or "").strip()
        if not article or not nm_id:
            continue
        sizes = card.get("sizes") or []
        first_size = sizes[0] if sizes else {}
        skus = first_size.get("skus") or []
        barcode = str(skus[0]) if skus else None
        chrt = first_size.get("chrtID")

        # The stable Wildberries identity is nmID, not vendorCode.
        matches = db.query(Product).filter(
            Product.marketplace == "WB", Product.nm_id == nm_id
        ).all()
        if len(matches) > 1:
            observe(db, card)
            continue
        product = matches[0] if matches else None
        article_matches = db.query(Product).filter(
            Product.marketplace == "WB", Product.seller_article == article
        ).all()
        if any(item is not product for item in article_matches) or (product is not None and product.seller_article != article):
            observe(db, card)
            continue
        if product is None:
            # New WB card needs manual confirmation before being linked to master catalog.
            observe(db, card)
            continue
        if product is None:
            product = Product(
                marketplace="WB", nm_id=nm_id, seller_article=article,
                organization_id=int(db.connection().exec_driver_sql(
                    "SELECT current_setting('app.organization_id')"
                ).scalar_one()),
            )
            db.add(product)
        # Update only the WB product, never MasterProduct (Ozon/Yandex mapping).
        product.seller_article = article
        product.barcode = barcode
        product.chrt_id = str(chrt) if chrt is not None else None
        product.name = card.get("title")
        product.updated_at = datetime.utcnow()
        saved += 1
    db.commit()
    return saved
