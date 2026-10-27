from datetime import datetime
from sqlalchemy import Boolean, Column, DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.orm import relationship
from backend.database import Base

class MarketplaceConnection(Base):
    __tablename__ = "marketplace_connections"
    id = Column(Integer, primary_key=True)
    organization_id = Column(Integer, ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False, index=True)
    marketplace = Column(String(20), nullable=False)
    enabled = Column(Boolean, nullable=False, default=False)
    credentials_encrypted = Column(Text, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)
    last_connected_at = Column(DateTime, nullable=True)
    last_error = Column(Text, nullable=True)
    organization = relationship("Organization")
