"""Per-organization catalog reconciliation preferences; schedule is not active yet."""
from sqlalchemy import Column, Integer, String, Boolean, Text, DateTime, UniqueConstraint, text
from datetime import datetime
from backend.database import Base


class CatalogSyncSetting(Base):
    __tablename__ = 'catalog_sync_settings'
    __table_args__ = (UniqueConstraint('organization_id', name='uq_catalog_sync_settings_org'),)
    id = Column(Integer, primary_key=True)
    organization_id = Column(Integer, nullable=False, index=True, server_default=text("current_setting('app.organization_id', true)::integer"))
    match_by = Column(String(16), nullable=False, default='ARTICLE')
    auto_enabled = Column(Boolean, nullable=False, default=False)
    timezone = Column(String(64), nullable=False, default='Europe/Moscow')
    times_json = Column(Text, nullable=False, default='["06:00","18:00","23:00"]')
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)
