"""Immutable audit of dimensions copied from an external marketplace."""
from datetime import datetime
from sqlalchemy import Column, Integer, String, DateTime, Numeric, ForeignKey, text
from backend.database import Base

class ProductDimensionChange(Base):
    __tablename__ = 'product_dimension_changes'
    id = Column(Integer, primary_key=True)
    organization_id = Column(Integer, nullable=False, index=True, server_default=text("current_setting('app.organization_id', true)::integer"))
    master_id = Column(Integer, ForeignKey('master_products.id'), nullable=False)
    marketplace = Column(String(16), nullable=False)
    external_id = Column(String(128), nullable=False)
    field = Column(String(32), nullable=False)
    old_cm = Column(Numeric(10, 2), nullable=True)
    new_cm = Column(Numeric(10, 2), nullable=False)
    changed_by = Column(Integer, nullable=False)
    changed_at = Column(DateTime, default=datetime.utcnow, nullable=False)
