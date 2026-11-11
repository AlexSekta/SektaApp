"""Audit trail of confirmed local barcode changes."""
from datetime import datetime
from sqlalchemy import Column, Integer, String, DateTime, ForeignKey, text
from backend.database import Base

class ProductBarcodeChange(Base):
    __tablename__ = 'product_barcode_changes'
    id = Column(Integer, primary_key=True)
    organization_id = Column(Integer, nullable=False, index=True, server_default=text("current_setting('app.organization_id', true)::integer"))
    master_id = Column(Integer, ForeignKey('master_products.id'), nullable=False)
    marketplace = Column(String(16), nullable=False)
    external_id = Column(String(128), nullable=False)
    old_barcode = Column(String(64), nullable=True)
    new_barcode = Column(String(64), nullable=False)
    changed_by = Column(Integer, nullable=False)
    changed_at = Column(DateTime, default=datetime.utcnow, nullable=False)
