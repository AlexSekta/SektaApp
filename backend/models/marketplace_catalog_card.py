"""Confirmed per-marketplace external identity for master catalog products."""
from datetime import datetime
from sqlalchemy import Column, Integer, String, DateTime, Text, Numeric, ForeignKey, UniqueConstraint, text
from backend.database import Base

class MarketplaceCatalogCard(Base):
    __tablename__ = 'marketplace_catalog_cards'
    __table_args__ = (UniqueConstraint('organization_id', 'marketplace', 'external_id', name='uq_mp_catalog_identity'),)
    id = Column(Integer, primary_key=True)
    organization_id = Column(Integer, nullable=False, index=True, server_default=text("current_setting('app.organization_id', true)::integer"))
    marketplace = Column(String(16), nullable=False)
    external_id = Column(String(128), nullable=False)
    seller_article = Column(String(128), nullable=False)
    master_id = Column(Integer, ForeignKey('master_products.id'), nullable=False)
    title = Column(Text, nullable=True)
    barcode = Column(String(64), nullable=True)
    length_cm = Column(Numeric(10, 2), nullable=True)
    width_cm = Column(Numeric(10, 2), nullable=True)
    height_cm = Column(Numeric(10, 2), nullable=True)
    platform_ids_json = Column(Text, nullable=True)
    confirmed_at = Column(DateTime, default=datetime.utcnow, nullable=False)
