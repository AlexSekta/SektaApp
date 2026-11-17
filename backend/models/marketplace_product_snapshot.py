"""Latest marketplace-origin product attributes, independent of confirmed links."""
from datetime import datetime, timezone
from sqlalchemy import Column, Integer, String, Text, DateTime, Numeric, UniqueConstraint, Index, text
from backend.database import Base


class MarketplaceProductSnapshot(Base):
    __tablename__ = 'marketplace_product_snapshots'
    __table_args__ = (
        UniqueConstraint('organization_id', 'marketplace', 'external_id', name='uq_marketplace_product_snapshot_identity'),
        Index('ix_mp_snapshot_org_article', 'organization_id', 'marketplace', 'seller_article'),
    )
    id = Column(Integer, primary_key=True)
    organization_id = Column(Integer, nullable=False, index=True, server_default=text("current_setting('app.organization_id', true)::integer"))
    marketplace = Column(String(16), nullable=False)
    external_id = Column(String(128), nullable=False)
    seller_article = Column(String(128), nullable=True)
    title = Column(Text, nullable=True)
    description = Column(Text, nullable=True)
    barcodes_json = Column(Text, nullable=False, default='[]')
    platform_ids_json = Column(Text, nullable=False, default='{}')
    # Dimensions from marketplace API, original units and normalized cm.
    length_raw = Column(Numeric(14, 3), nullable=True)
    width_raw = Column(Numeric(14, 3), nullable=True)
    height_raw = Column(Numeric(14, 3), nullable=True)
    dimension_unit = Column(String(16), nullable=True)
    length_cm = Column(Numeric(14, 3), nullable=True)
    width_cm = Column(Numeric(14, 3), nullable=True)
    height_cm = Column(Numeric(14, 3), nullable=True)
    dimension_state = Column(String(24), nullable=False, default='UNKNOWN')
    checked_at = Column(DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc))


class MarketplaceProductSnapshotChange(Base):
    __tablename__ = 'marketplace_product_snapshot_changes'
    __table_args__ = (Index('ix_mp_snapshot_change_identity', 'organization_id', 'marketplace', 'external_id', 'changed_at'),)
    id = Column(Integer, primary_key=True)
    organization_id = Column(Integer, nullable=False, index=True, server_default=text("current_setting('app.organization_id', true)::integer"))
    marketplace = Column(String(16), nullable=False)
    external_id = Column(String(128), nullable=False)
    before_json = Column(Text, nullable=True)
    after_json = Column(Text, nullable=False)
    changed_at = Column(DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc))
