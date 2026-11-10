from datetime import datetime
from sqlalchemy import Column, DateTime, Integer, String, Text, UniqueConstraint, text
from backend.database import Base

class WBIdentityReview(Base):
    __tablename__ = 'wb_identity_reviews'
    __table_args__ = (UniqueConstraint('organization_id', 'nm_id', name='uq_wb_identity_reviews_org_nm'),)
    id = Column(Integer, primary_key=True)
    organization_id = Column(Integer, nullable=False)
    nm_id = Column(String(32), nullable=False)
    observed_article = Column(String(128), nullable=False)
    stored_article = Column(String(128), nullable=True)
    reason = Column(String(40), nullable=False)
    status = Column(String(20), nullable=False, default='OPEN')
    master_id = Column(Integer, nullable=True)
    barcodes = Column(Text, nullable=True)
    title = Column(Text, nullable=True)
    reviewed_by = Column(String(120), nullable=True)
    reviewed_at = Column(DateTime, nullable=True)
    first_seen_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    last_seen_at = Column(DateTime, default=datetime.utcnow, nullable=False)

class WBIdentityLink(Base):
    __tablename__ = 'wb_identity_links'
    __table_args__ = (UniqueConstraint('organization_id', 'nm_id', name='uq_wb_identity_links_org_nm'),)
    id = Column(Integer, primary_key=True)
    organization_id = Column(Integer, nullable=False)
    nm_id = Column(String(32), nullable=False)
    master_id = Column(Integer, nullable=False)
    current_article = Column(String(128), nullable=False)
    confirmed_at = Column(DateTime, default=datetime.utcnow, nullable=False)
