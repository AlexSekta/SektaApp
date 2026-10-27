from sqlalchemy import Column, Integer, String, Date, DateTime, UniqueConstraint, text
from datetime import datetime

from backend.database import Base


class StockHistory(Base):

    __tablename__ = "stock_history"
    organization_id = Column(Integer, nullable=False, index=True, server_default=text("current_setting(\'app.organization_id\', true)::integer"))

    __table_args__ = (
        UniqueConstraint(
            "organization_id",
            "date",
            "marketplace",
            "warehouse_id",
            "sku",
            name="unique_stock_snapshot"
        ),
    )


    id = Column(
        Integer,
        primary_key=True
    )


    date = Column(
        Date,
        nullable=False
    )


    marketplace = Column(
        String,
        nullable=False
    )


    warehouse_id = Column(
        String(255),
        nullable=False
    )


    warehouse_name = Column(
        String,
        nullable=False
    )


    warehouse_type = Column(
        String,
        nullable=False
    )


    seller_article = Column(
        String,
        nullable=False
    )


    nm_id = Column(
        String,
        nullable=False
    )


    sku = Column(
        String,
        nullable=False
    )


    stock = Column(
        Integer,
        nullable=False
    )


    created_at = Column(
        DateTime,
        default=datetime.utcnow
    )
