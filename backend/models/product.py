from sqlalchemy import Column, Integer, String, DateTime, text
from datetime import datetime

from backend.database import Base


class Product(Base):

    __tablename__ = "products"
    organization_id = Column(Integer, nullable=False, index=True, server_default=text("current_setting(\'app.organization_id\', true)::integer"))


    id = Column(
        Integer,
        primary_key=True
    )


    marketplace = Column(
        String,
        nullable=False
    )


    nm_id = Column(
        String,
        nullable=False
    )


    seller_article = Column(
        String,
        nullable=False
    )


    barcode = Column(
        String,
        nullable=True
    )


    chrt_id = Column(
        String,
        nullable=True
    )


    name = Column(
        String,
        nullable=True
    )


    updated_at = Column(
        DateTime,
        default=datetime.utcnow
    )
