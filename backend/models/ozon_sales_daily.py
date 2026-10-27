from datetime import datetime

from sqlalchemy import Column, Date, DateTime, Integer, JSON, Numeric, UniqueConstraint, text

from backend.database import Base


class OzonSalesDaily(Base):
    __tablename__ = "ozon_sales_daily"

    id = Column(Integer, primary_key=True)
    organization_id = Column(
        Integer,
        nullable=False,
        index=True,
        server_default=text("current_setting('app.organization_id', true)::integer"),
    )
    sale_date = Column(Date, nullable=False, index=True)
    revenue = Column(Numeric(18, 2), nullable=False, default=0)
    ordered_units = Column(Integer, nullable=False, default=0)
    delivered_units = Column(Integer, nullable=True, default=None)
    returns = Column(Integer, nullable=True, default=None)
    cancellations = Column(Integer, nullable=True, default=None)
    raw_data = Column(JSON, nullable=True)
    last_synced_at = Column(DateTime, nullable=False, default=datetime.utcnow)

    __table_args__ = (
        UniqueConstraint(
            "organization_id",
            "sale_date",
            name="uq_ozon_sales_daily_org_date",
        ),
    )
