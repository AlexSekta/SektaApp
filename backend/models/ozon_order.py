from datetime import datetime
from sqlalchemy import Column, Date, DateTime, Integer, String, Numeric, UniqueConstraint, Index, text
from backend.database import Base

class OzonOrderLine(Base):
    __tablename__ = 'ozon_order_lines'
    id = Column(Integer, primary_key=True)
    organization_id = Column(Integer, nullable=False, index=True, server_default=text("current_setting('app.organization_id', true)::integer"))
    posting_number = Column(String(100), nullable=False)
    scheme = Column(String(3), nullable=False)
    line_index = Column(Integer, nullable=False)
    sale_date = Column(Date, nullable=False, index=True)
    sku = Column(String(40), nullable=False)
    offer_id = Column(String(150))
    order_number = Column(String(100))
    status = Column(String(80))
    quantity = Column(Integer, nullable=False)
    customer_currency = Column(String(4), nullable=False)
    customer_unit_price = Column(Numeric(22, 6), nullable=False)
    seller_unit_price_rub = Column(Numeric(22, 6))
    fx_rate_rub = Column(Numeric(20, 10), nullable=False)
    estimated_rub = Column(Numeric(22, 6), nullable=False)
    last_synced_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    __table_args__ = (
        UniqueConstraint('organization_id','scheme','posting_number','line_index',name='uq_ozon_order_line_org_scheme_posting_index'),
        Index('ix_ozon_order_lines_org_date_sku','organization_id','sale_date','sku'),
    )

class OzonOrderSyncDay(Base):
    __tablename__ = 'ozon_order_sync_days'
    id = Column(Integer, primary_key=True)
    organization_id = Column(Integer, nullable=False, index=True, server_default=text("current_setting('app.organization_id', true)::integer"))
    sale_date = Column(Date, nullable=False)
    posting_count = Column(Integer, nullable=False)
    line_count = Column(Integer, nullable=False)
    last_synced_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    __table_args__ = (UniqueConstraint('organization_id','sale_date',name='uq_ozon_order_sync_day'),)
