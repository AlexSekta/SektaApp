"""Platform-specific barcodes confirmed for a specific marketplace catalog identity."""
from sqlalchemy import Column, Integer, String, ForeignKey, UniqueConstraint, text
from backend.database import Base


class MarketplaceProductBarcode(Base):
    __tablename__ = 'marketplace_product_barcodes'
    __table_args__ = (UniqueConstraint('organization_id', 'marketplace', 'external_id', 'barcode', name='uq_marketplace_product_barcode'),)
    id = Column(Integer, primary_key=True)
    organization_id = Column(Integer, nullable=False, index=True,
                             server_default=text("current_setting('app.organization_id', true)::integer"))
    master_id = Column(Integer, ForeignKey('master_products.id'), nullable=False)
    marketplace = Column(String(16), nullable=False)
    external_id = Column(String(128), nullable=False)
    barcode = Column(String(128), nullable=False)
