from sqlalchemy import Column, Integer, String, DateTime, text
from datetime import datetime

from backend.database import Base


class Warehouse(Base):

    __tablename__ = "warehouses"
    organization_id = Column(Integer, nullable=False, index=True, server_default=text("current_setting(\'app.organization_id\', true)::integer"))


    id = Column(
        Integer,
        primary_key=True
    )

    marketplace = Column(
        String,
        nullable=False
    )

    warehouse_id = Column(
        String,
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

    updated_at = Column(
        DateTime,
        default=datetime.utcnow
    )
