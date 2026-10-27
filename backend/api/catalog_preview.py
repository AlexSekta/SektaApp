"""Безопасная предпросмотр-сверка каталога WB без записи в БД."""
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from backend.dependencies import get_db
from backend.models.product import Product
from backend.models.master_product import MasterProduct
from backend.services.marketplace_clients import get_wb_client
from backend.services.marketplace_credentials import MarketplaceNotConfiguredError
from backend.logging_config import get_logger

router = APIRouter(prefix="/catalog", tags=["Каталог — диагностика"])
logger = get_logger("catalog_preview")


@router.get("/wb/preview")
def preview_wb_catalog(
    offset: int = Query(0, ge=0),
    limit: int = Query(100, ge=1, le=500),
    db: Session = Depends(get_db),
):
    """Сопоставляет карточки WB и локальные таблицы только для чтения.

    Никакие таблицы, в том числе products/master_products/остатки, не меняются.
    Статус совпадения артикулов лишь подсказка, не автоматическое связывание.
    """
    try:
        cards = get_wb_client(db).get_products().get("cards") or []
    except MarketplaceNotConfiguredError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        logger.exception("CATALOG_WB_PREVIEW_API_ERROR")
        raise HTTPException(status_code=502, detail="Не удалось получить карточки WB; подробности в журнале backend") from exc

    existing_products = db.query(Product).filter(Product.marketplace == "WB").all()
    masters = db.query(MasterProduct).all()
    known_nm_ids = {str(p.nm_id) for p in existing_products if p.nm_id is not None}
    master_by_article = {}
    for master in masters:
        key = (master.seller_article or "").strip()
        if key:
            master_by_article.setdefault(key, []).append(master.id)

    rows = []
    seen_nm_ids = set()
    missing = 0
    article_matches = 0
    duplicates = 0
    for card in cards:
        nm_id = str(card.get("nmID") or "").strip()
        if not nm_id:
            continue
        if nm_id in seen_nm_ids:
            duplicates += 1
            continue
        seen_nm_ids.add(nm_id)
        article = str(card.get("vendorCode") or "").strip()
        match_ids = master_by_article.get(article, []) if article else []
        exists = nm_id in known_nm_ids
        missing += not exists
        article_matches += bool(match_ids)
        sizes = card.get("sizes") or []
        skus = list(dict.fromkeys(
            str(sku) for size in sizes for sku in (size.get("skus") or []) if sku
        ))
        rows.append({
            "nm_id": nm_id,
            "seller_article": article,
            "name": card.get("title"),
            "barcodes": skus,
            "exists_in_wb_products": exists,
            "master_article_candidate_ids": match_ids,
            "match_verified": False,
        })

    return {
        "marketplace": "WB",
        "mode": "read_only",
        "total_cards": len(rows),
        "missing_in_wb_products": missing,
        "article_match_candidates": article_matches,
        "duplicate_nm_ids_in_response": duplicates,
        "offset": offset,
        "limit": limit,
        "returned": len(rows[offset:offset + limit]),
        "items": rows[offset:offset + limit],
    }
