from datetime import datetime

from sqlalchemy import Column, DateTime, Integer, String, UniqueConstraint, text

from backend.database import Base


class OneCStock(Base):

    __tablename__ = "one_c_stocks"
    organization_id = Column(Integer, nullable=False, index=True, server_default=text("current_setting(\'app.organization_id\', true)::integer"))

    __table_args__ = (
        UniqueConstraint(
            "organization_id",
            "seller_article",
            "group",
            name="uq_one_c_stock_article_group",
        ),
    )

    id = Column(Integer, primary_key=True)

    seller_article = Column(
        String,
        nullable=False,
        index=True,
    )

    group = Column(
        String,
        nullable=False,
        index=True,
    )

    stock = Column(
        Integer,
        nullable=False,
    )

    source_file = Column(
        String,
        nullable=False,
    )

    updated_at = Column(
        DateTime,
        nullable=False,
        default=datetime.utcnow,
    )
