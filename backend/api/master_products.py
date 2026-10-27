from decimal import Decimal, InvalidOperation
from typing import Any

from fastapi import APIRouter, Depends
from sqlalchemy import inspect, text
from sqlalchemy.orm import Session

from backend.database import engine, SessionLocal
from backend.dependencies import get_db
from backend.logging_config import get_logger
from backend.models.master_product import MasterProduct
from backend.models.product import Product
from backend.models.stock_history import StockHistory

router = APIRouter()
logger = get_logger("products")


def _as_decimal(value: Any, field: str, *, allow_blank: bool = True) -> Decimal | None:
    if value is None or (isinstance(value, str) and not value.strip()):
        if allow_blank:
            return None
        raise ValueError(f"{field}: значение обязательно")
    try:
        result = Decimal(str(value).replace(",", ".").strip())
    except (InvalidOperation, ValueError) as error:
        raise ValueError(f"{field}: некорректное число") from error
    if result < 0:
        raise ValueError(f"{field}: значение не может быть отрицательным")
    return result


def _as_bool(value: Any, default: bool = False) -> bool:
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value.strip().lower() in {"true", "1", "yes", "on", "да"}
    return bool(value)


def _status(value: Any, default: str = "READY") -> str:
    value = str(value or default).strip().upper()
    if value not in {"READY", "SELLING", "ARCHIVE"}:
        raise ValueError("Статус должен быть: Готовится, Продается или Архив")
    return value


def _serialize_product(item: MasterProduct) -> dict:
    purchase = Decimal(item.purchase_price or 0)
    extra = Decimal(item.additional_costs or 0)
    final_cost = purchase + extra

    volume_cm3 = None
    volume_liters = None
    if item.length_cm is not None and item.width_cm is not None and item.height_cm is not None:
        volume_cm3 = Decimal(item.length_cm) * Decimal(item.width_cm) * Decimal(item.height_cm)
        volume_liters = volume_cm3 / Decimal("1000")

    return {
        "id": item.id,
        "sort_order": item.sort_order,
        "internal_article": item.internal_article,
        "seller_article": item.seller_article,
        "barcode": item.barcode,
        "name": item.name,
        "group": item.group,
        "purchase_price": float(purchase),
        "additional_costs": float(extra),
        "final_cost": float(final_cost),
        "length_cm": float(item.length_cm) if item.length_cm is not None else None,
        "width_cm": float(item.width_cm) if item.width_cm is not None else None,
        "height_cm": float(item.height_cm) if item.height_cm is not None else None,
        "volume_cm3": float(volume_cm3) if volume_cm3 is not None else None,
        "volume_liters": float(volume_liters) if volume_liters is not None else None,
        "wb_enabled": bool(item.wb_enabled),
        "ozon_enabled": bool(item.ozon_enabled),
        "yandex_enabled": bool(item.yandex_enabled),
        "active": bool(item.active),
        "status": item.status or ("SELLING" if item.active else "READY"),
        "created_at": item.created_at.isoformat() if item.created_at else None,
        "updated_at": item.updated_at.isoformat() if item.updated_at else None,
    }


def ensure_master_product_schema(db: Session) -> None:
    """Добавляет новые поля в существующую таблицу без удаления данных."""
    inspector = inspect(engine)
    existing_columns = {column["name"] for column in inspector.get_columns("master_products")}
    status_added = "status" not in existing_columns

    additions = {
        "internal_article": "VARCHAR(128)",
        "barcode": "VARCHAR(64)",
        "purchase_price": "NUMERIC(12,2) NOT NULL DEFAULT 0",
        "additional_costs": "NUMERIC(12,2) NOT NULL DEFAULT 0",
        "length_cm": "NUMERIC(10,2)",
        "width_cm": "NUMERIC(10,2)",
        "height_cm": "NUMERIC(10,2)",
        "wb_enabled": "BOOLEAN NOT NULL DEFAULT FALSE",
        "ozon_enabled": "BOOLEAN NOT NULL DEFAULT FALSE",
        "yandex_enabled": "BOOLEAN NOT NULL DEFAULT FALSE",
        "status": "VARCHAR(16) NOT NULL DEFAULT 'READY'",
        "updated_at": "TIMESTAMP NULL",
    }

    conn = db.connection()
    for column_name, definition in additions.items():
        if column_name not in existing_columns:
            conn.execute(text(f"ALTER TABLE master_products ADD COLUMN {column_name} {definition}"))

    if status_added:
        conn.execute(text("""
            UPDATE master_products
            SET status = CASE WHEN active = TRUE THEN 'SELLING' ELSE 'READY' END
        """))

    conn.execute(text("""
        UPDATE master_products
        SET internal_article = seller_article
        WHERE internal_article IS NULL
    """))

    conn.execute(text("""
        UPDATE master_products mp
        SET wb_enabled = TRUE
        WHERE EXISTS (
            SELECT 1 FROM products p
            WHERE p.marketplace = 'WB'
              AND p.seller_article = mp.seller_article
        )
    """))

    conn.execute(text("""
        UPDATE master_products mp
        SET barcode = p.barcode
        FROM products p
        WHERE mp.barcode IS NULL
          AND p.marketplace = 'WB'
          AND p.seller_article = mp.seller_article
    """))

    conn.execute(text("""
        UPDATE master_products
        SET updated_at = COALESCE(updated_at, created_at, NOW())
    """))

    conn.execute(text("""
        CREATE UNIQUE INDEX IF NOT EXISTS ux_master_products_internal_article
        ON master_products (organization_id, internal_article)
    """))

    conn.execute(text("""
        WITH ordered AS (
            SELECT id, ROW_NUMBER() OVER (ORDER BY sort_order, id) AS new_order
            FROM master_products
        )
        UPDATE master_products mp
        SET sort_order = ordered.new_order
        FROM ordered
        WHERE mp.id = ordered.id
    """))
    db.commit()


def ensure_master_product_schema_at_startup() -> None:
    """Выполняет DDL/миграцию каталога только административным подключением."""
    db = SessionLocal()
    try:
        ensure_master_product_schema(db)
    finally:
        db.close()


def _renumber_sort_order(db: Session) -> None:
    rows = db.query(MasterProduct).order_by(
        MasterProduct.sort_order,
        MasterProduct.id,
    ).all()
    for index, row in enumerate(rows, start=1):
        row.sort_order = index


@router.get("/master-products")
def get_master_products(db: Session = Depends(get_db)):
    products = db.query(MasterProduct).order_by(
        MasterProduct.sort_order,
        MasterProduct.id,
    ).all()
    return [_serialize_product(item) for item in products]


@router.post("/master-products")
def create_master_product(data: dict, db: Session = Depends(get_db)):

    internal_article = str(data.get("internal_article") or "").strip()
    seller_article = str(data.get("seller_article") or "").strip()
    name = str(data.get("name") or "").strip()
    barcode = str(data.get("barcode") or "").strip() or None
    group = str(data.get("group") or "Маркетплейс").strip() or "Маркетплейс"
    try:
        status = _status(data.get("status"), "READY")
    except ValueError as error:
        return {"status": "error", "message": str(error)}

    if not internal_article:
        return {"status": "error", "message": "Введите внутренний артикул"}
    if not seller_article:
        return {"status": "error", "message": "Введите артикул продавца"}
    if not name:
        return {"status": "error", "message": "Введите название товара"}

    try:
        purchase_price = _as_decimal(
            data.get("purchase_price"),
            "Закупочная цена",
            allow_blank=False,
        )
        additional_costs = _as_decimal(
            data.get("additional_costs"),
            "Дополнительные затраты",
        ) or Decimal("0")
        length_cm = _as_decimal(data.get("length_cm"), "Длина")
        width_cm = _as_decimal(data.get("width_cm"), "Ширина")
        height_cm = _as_decimal(data.get("height_cm"), "Высота")
    except ValueError as error:
        return {"status": "error", "message": str(error)}

    if db.query(MasterProduct).filter(
        MasterProduct.internal_article == internal_article
    ).first():
        return {"status": "error", "message": "Этот внутренний артикул уже существует"}

    if db.query(MasterProduct).filter(
        MasterProduct.seller_article == seller_article
    ).first():
        return {"status": "error", "message": "Этот артикул продавца уже существует"}

    last_order = db.query(MasterProduct.sort_order).order_by(
        MasterProduct.sort_order.desc()
    ).first()
    new_order = (last_order[0] if last_order and last_order[0] is not None else 0) + 1

    product = MasterProduct(
        sort_order=new_order,
        internal_article=internal_article,
        seller_article=seller_article,
        barcode=barcode,
        name=name,
        group=group,
        purchase_price=purchase_price,
        additional_costs=additional_costs,
        length_cm=length_cm,
        width_cm=width_cm,
        height_cm=height_cm,
        wb_enabled=_as_bool(data.get("wb_enabled")),
        ozon_enabled=_as_bool(data.get("ozon_enabled")),
        yandex_enabled=_as_bool(data.get("yandex_enabled")),
        status=status,
        # Новый каталог не ломает 1С: в Реестр остатков товар попадёт только после включения.
        active=_as_bool(data.get("active"), False),
    )

    try:
        db.add(product)
        db.commit()
        db.refresh(product)
    except Exception:
        db.rollback()
        logger.exception(
            "PRODUCT_CREATE_FAILED | internal=%s | seller=%s",
            internal_article,
            seller_article,
        )
        raise

    return {"status": "ok", "product": _serialize_product(product)}


@router.put("/master-products/{product_id}")
def update_master_product(
    product_id: int,
    data: dict,
    db: Session = Depends(get_db),
):

    product = db.query(MasterProduct).filter(
        MasterProduct.id == product_id
    ).first()
    if not product:
        return {"status": "error", "message": "Товар не найден"}

    # Перенос между складами — отдельная операция: не требует повторного ввода цены.
    if set(data.keys()) == {"group"}:
        from backend.models.one_c_stock import OneCStock
        from fastapi import HTTPException
        new_group = str(data.get("group") or "").strip()
        oid = product.organization_id
        found = db.execute(text("SELECT 1 FROM local_warehouses WHERE organization_id=:oid AND name=:name"), {"oid": oid, "name": new_group}).first()
        if not found:
            raise HTTPException(status_code=422, detail="Выбранный склад не существует")
        if new_group == product.group:
            return {"status": "ok", "product": _serialize_product(product)}
        old = db.query(OneCStock).filter(OneCStock.organization_id == oid, OneCStock.group == product.group, OneCStock.seller_article == product.seller_article).first()
        target = db.query(OneCStock).filter(OneCStock.organization_id == oid, OneCStock.group == new_group, OneCStock.seller_article == product.seller_article).first()
        if target and old:
            raise HTTPException(
                status_code=409,
                detail=(f"У артикула {product.seller_article} есть остатки на обоих складах: "
                        f"«{product.group}» — {old.stock} шт., «{new_group}» — {target.stock} шт. "
                        "Перенос отменён, чтобы не потерять данные. Требуется сверка остатков."),
            )
        if old and not target:
            old.group = new_group  # перенос существующего остатка без изменения количества
        # Если запись есть только на целевом складе, оставляем её без изменений.
        product.group = new_group
        db.commit()
        db.refresh(product)
        return {"status": "ok", "product": _serialize_product(product)}

    new_internal = str(
        data.get("internal_article")
        if data.get("internal_article") is not None
        else product.internal_article or ""
    ).strip()
    new_seller = str(
        data.get("seller_article")
        if data.get("seller_article") is not None
        else product.seller_article or ""
    ).strip()
    new_name = str(
        data.get("name")
        if data.get("name") is not None
        else product.name or ""
    ).strip()

    if not new_internal or not new_seller or not new_name:
        return {
            "status": "error",
            "message": "Внутренний артикул, артикул продавца и название обязательны",
        }

    if db.query(MasterProduct).filter(
        MasterProduct.internal_article == new_internal,
        MasterProduct.id != product.id,
    ).first():
        return {"status": "error", "message": "Этот внутренний артикул уже существует"}

    if new_seller != product.seller_article:
        has_stock_history = db.query(StockHistory.id).filter(
            StockHistory.seller_article == product.seller_article
        ).first()
        if has_stock_history:
            return {
                "status": "error",
                "message": (
                    "Артикул продавца нельзя менять: "
                    "по нему уже есть история остатков"
                ),
            }
        if db.query(MasterProduct).filter(
            MasterProduct.seller_article == new_seller,
            MasterProduct.id != product.id,
        ).first():
            return {"status": "error", "message": "Этот артикул продавца уже существует"}

    try:
        product.internal_article = new_internal
        product.seller_article = new_seller
        product.name = new_name
        product.barcode = str(data.get("barcode") or "").strip() or None
        product.group = str(
            data.get("group") or product.group or "Маркетплейс"
        ).strip()
        product.purchase_price = _as_decimal(
            data.get("purchase_price"),
            "Закупочная цена",
            allow_blank=False,
        )
        product.additional_costs = _as_decimal(
            data.get("additional_costs"),
            "Дополнительные затраты",
        ) or Decimal("0")
        product.length_cm = _as_decimal(data.get("length_cm"), "Длина")
        product.width_cm = _as_decimal(data.get("width_cm"), "Ширина")
        product.height_cm = _as_decimal(data.get("height_cm"), "Высота")
        product.wb_enabled = _as_bool(data.get("wb_enabled"))
        product.ozon_enabled = _as_bool(data.get("ozon_enabled"))
        product.yandex_enabled = _as_bool(data.get("yandex_enabled"))
        product.status = _status(data.get("status", product.status), product.status or "READY")
        if "active" in data:
            product.active = _as_bool(data.get("active"))
        db.commit()
        db.refresh(product)
    except ValueError as error:
        db.rollback()
        return {"status": "error", "message": str(error)}
    except Exception:
        db.rollback()
        logger.exception("PRODUCT_UPDATE_FAILED | id=%s", product_id)
        raise

    return {"status": "ok", "product": _serialize_product(product)}


@router.delete("/master-products/{product_id}")
def delete_master_product(
    product_id: int,
    db: Session = Depends(get_db),
):

    product = db.query(MasterProduct).filter(
        MasterProduct.id == product_id
    ).first()
    if not product:
        return {"status": "error", "message": "Товар не найден"}

    try:
        db.delete(product)
        db.commit()
        _renumber_sort_order(db)
        db.commit()
    except Exception:
        db.rollback()
        logger.exception("PRODUCT_DELETE_FAILED | id=%s", product_id)
        raise

    return {"status": "ok"}
