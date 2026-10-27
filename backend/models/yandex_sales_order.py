"""Historical Yandex order-line snapshots; raw buyer details are not persisted."""
from datetime import datetime
from sqlalchemy import Column, Integer, BigInteger, String, Date, DateTime, Numeric, Boolean, UniqueConstraint, Index, text
from backend.database import Base

class YandexSalesOrderLine(Base):
    __tablename__ = 'yandex_sales_order_lines'
    id = Column(Integer, primary_key=True)
    organization_id = Column(Integer, nullable=False, index=True, server_default=text("current_setting('app.organization_id', true)::integer"))
    business_id = Column(BigInteger, nullable=False)
    order_id = Column(String(64), nullable=False)
    line_index = Column(Integer, nullable=False)
    sale_date = Column(Date, nullable=False)
    created_at = Column(DateTime)
    offer_id = Column(String(150))
    program_type = Column(String(32))
    order_status = Column(String(48))
    order_substatus = Column(String(100))
    quantity = Column(Integer, nullable=False)
    payment = Column(Numeric(22, 4), nullable=False)
    cashback = Column(Numeric(22, 4), nullable=False)
    subsidy = Column(Numeric(22, 4), nullable=False)
    currency_code = Column(String(8), nullable=False)
    last_synced_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    __table_args__ = (
        UniqueConstraint('organization_id', 'business_id', 'order_id', 'line_index', name='uq_ym_sales_order_line'),
        Index('ix_ym_sales_order_org_day', 'organization_id', 'sale_date'),
    )

class YandexSalesSyncDay(Base):
    __tablename__ = 'yandex_sales_sync_days'
    id = Column(Integer, primary_key=True)
    organization_id = Column(Integer, nullable=False, index=True, server_default=text("current_setting('app.organization_id', true)::integer"))
    sale_date = Column(Date, nullable=False)
    orders_count = Column(Integer, nullable=False)
    lines_count = Column(Integer, nullable=False)
    units_count = Column(Integer, nullable=False)
    provisional = Column(Boolean, nullable=False, default=False)
    last_synced_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    __table_args__ = (UniqueConstraint('organization_id', 'sale_date', name='uq_ym_sales_sync_day'),)
