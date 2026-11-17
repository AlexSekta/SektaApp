"""Append-only decisions about confirmed marketplace packaging dimensions."""
from datetime import datetime, timezone
from sqlalchemy import Column, Integer, String, DateTime, Text, Index, text
from backend.database import Base


class MarketplaceDimensionDecision(Base):
    __tablename__ = 'marketplace_dimension_decisions'
    __table_args__ = (
        Index('ix_mp_dimension_decision_lookup', 'organization_id', 'marketplace', 'external_id', 'master_id', 'id'),
    )
    id = Column(Integer, primary_key=True)
    organization_id = Column(Integer, nullable=False, index=True, server_default=text("current_setting('app.organization_id', true)::integer"))
    marketplace = Column(String(16), nullable=False)
    external_id = Column(String(128), nullable=False)
    master_id = Column(Integer, nullable=False)
    issue_code = Column(String(40), nullable=False)
    fingerprint = Column(String(64), nullable=False)
    decision = Column(String(24), nullable=False)  # DISPUTED / ACCEPTED
    catalog_cm_json = Column(Text, nullable=False)
    marketplace_cm_json = Column(Text, nullable=False)
    actor_user_id = Column(Integer, nullable=False)
    created_at = Column(DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc))
