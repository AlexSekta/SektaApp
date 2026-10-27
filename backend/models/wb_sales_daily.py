from datetime import datetime
from sqlalchemy import Column, Integer, Date, DateTime, Numeric, UniqueConstraint, text
from backend.database import Base

class WBSalesDaily(Base):
    __tablename__ = 'wb_sales_daily'
    id = Column(Integer, primary_key=True)
    organization_id = Column(Integer, nullable=False, index=True, server_default=text("current_setting('app.organization_id', true)::integer"))
    sale_date = Column(Date, nullable=False)
    order_count = Column(Integer, nullable=False)
    order_sum = Column(Numeric(20, 2), nullable=False)
    cancel_count = Column(Integer, nullable=False)
    cancel_sum = Column(Numeric(20, 2), nullable=False)
    products_count = Column(Integer, nullable=False)
    synced_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    __table_args__ = (UniqueConstraint('organization_id', 'sale_date', name='uq_wb_sales_daily_org_date'),)
