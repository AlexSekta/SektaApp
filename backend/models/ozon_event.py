from datetime import datetime
from sqlalchemy import Column, Integer, String, Date, DateTime, UniqueConstraint, Index, text
from backend.database import Base

class OzonEvent(Base):
    __tablename__ = 'ozon_events'
    id = Column(Integer, primary_key=True)
    organization_id = Column(Integer, nullable=False, index=True, server_default=text("current_setting('app.organization_id', true)::integer"))
    event_type = Column(String(20), nullable=False)  # delivered/cancelled/returned
    event_key = Column(String(180), nullable=False)
    event_date = Column(Date, nullable=False, index=True)
    posting_number = Column(String(100))
    scheme = Column(String(3))
    quantity = Column(Integer, nullable=False)
    last_seen_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    __table_args__ = (UniqueConstraint('organization_id','event_type','event_key', name='uq_ozon_event_org_type_key'),
                      Index('ix_ozon_events_org_type_date','organization_id','event_type','event_date'))

class OzonEventCoverage(Base):
    __tablename__ = 'ozon_event_coverage'
    id = Column(Integer, primary_key=True)
    organization_id = Column(Integer, nullable=False, index=True, server_default=text("current_setting('app.organization_id', true)::integer"))
    event_type = Column(String(20), nullable=False)
    event_date = Column(Date, nullable=False)
    refreshed_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    __table_args__ = (UniqueConstraint('organization_id','event_type','event_date',name='uq_ozon_event_coverage'),)
