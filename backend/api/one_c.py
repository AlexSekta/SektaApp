from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from backend.dependencies import get_db
from backend.logging_config import get_logger

from backend.models.one_c_stock import OneCStock
from backend.services.one_c_stock_service import (
    OneCImportError,
    import_one_c_stocks,
)

router = APIRouter(
    prefix="/1c",
    tags=["1C"],
)

logger = get_logger("one_c_api")


@router.post("/sync-stocks", summary="Импортировать остатки из 1С")
def sync_one_c_stocks(
    db: Session = Depends(get_db),
):

    try:
        return import_one_c_stocks(db)

    except OneCImportError as error:

        return {
            "status": "error",
            "message": str(error),
        }

    except Exception:

        db.rollback()

        logger.exception("1C_SYNC_FAILED")

        return {
            "status": "error",
            "message": ("Внутренняя ошибка при " "импорте остатков 1С."),
        }


@router.get("/stocks", summary="Получить остатки из 1С")
def get_one_c_stocks(
    db: Session = Depends(get_db),
):

    stocks = (
        db.query(OneCStock)
        .order_by(
            OneCStock.group,
            OneCStock.seller_article,
        )
        .all()
    )

    return [
        {
            "article": item.seller_article,
            "group": item.group,
            "stock": item.stock,
            "source_file": item.source_file,
            "updated_at": item.updated_at,
        }
        for item in stocks
    ]
