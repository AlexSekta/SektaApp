from datetime import datetime
from sqlalchemy import Column, Integer, String, Boolean, DateTime, Numeric, UniqueConstraint, text
from backend.database import Base


class MasterProduct(Base):
    __tablename__ = "master_products"
    __table_args__ = (
        UniqueConstraint("organization_id", "internal_article", name="uq_master_products_internal_article"),
        UniqueConstraint("organization_id", "seller_article", name="uq_master_products_seller_article"),
    )
    organization_id = Column(Integer, nullable=False, index=True, server_default=text("current_setting(\'app.organization_id\', true)::integer"))

    id = Column(Integer, primary_key=True)
    sort_order = Column(Integer, nullable=False, default=0)

    # Внутренний артикул каталога.
    internal_article = Column(String(128), nullable=True, index=True)

    # Артикул продавца. Сохраняем старое имя для совместимости с Реестром,
    # остатками, 1С и коммуникациями.
    seller_article = Column(String(128), nullable=False, index=True)
    barcode = Column(String(64), nullable=True, index=True)
    name = Column(String, nullable=True)

    # Старое поле: используется как группа/склад 1С.
    group = Column(String, nullable=False, default="Маркетплейс")

    purchase_price = Column(Numeric(12, 2), nullable=False, default=0)
    additional_costs = Column(Numeric(12, 2), nullable=False, default=0)

    length_cm = Column(Numeric(10, 2), nullable=True)
    width_cm = Column(Numeric(10, 2), nullable=True)
    height_cm = Column(Numeric(10, 2), nullable=True)

    wb_enabled = Column(Boolean, nullable=False, default=False)
    ozon_enabled = Column(Boolean, nullable=False, default=False)
    yandex_enabled = Column(Boolean, nullable=False, default=False)
    status = Column(String(16), nullable=False, default="READY", index=True)

    # Сохраняем смысл active: участие товара в Реестре остатков/1С.
    active = Column(Boolean, nullable=False, default=True)

    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
