from datetime import datetime

from sqlalchemy import Column, Integer, String, Date, DateTime, Float, UniqueConstraint, text
from backend.database import Base


class AutoStockHistory(Base):

    __tablename__ = "auto_stock_history"
    organization_id = Column(Integer, nullable=False, index=True, server_default=text("current_setting(\'app.organization_id\', true)::integer"))

    __table_args__ = (
        UniqueConstraint("organization_id", "date", "marketplace", name="uq_auto_stock_date_marketplace"),
    )

    id = Column(Integer, primary_key=True)

    date = Column(Date, nullable=False, index=True)

    marketplace = Column(String, nullable=False, index=True)

    total_products = Column(Integer, nullable=False)

    zero_products = Column(Integer, nullable=False)

    autostock_percent = Column(Float, nullable=False)

    created_at = Column(
        DateTime,
        default=datetime.utcnow,
        nullable=False,
    )
