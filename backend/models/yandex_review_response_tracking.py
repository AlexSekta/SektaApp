from datetime import datetime
from sqlalchemy import BigInteger, Boolean, Column, DateTime, Float, Integer, String, text
from backend.database import Base

class YandexReviewResponseTracking(Base):
    __tablename__ = "yandex_review_response_tracking"
    organization_id = Column(Integer, primary_key=True, server_default=text("current_setting('app.organization_id', true)::integer"))
    business_id = Column(BigInteger, primary_key=True)
    feedback_id = Column(String(128), primary_key=True)
    review_created_at = Column(DateTime)
    first_seen_unanswered_at = Column(DateTime, nullable=False)
    last_seen_unanswered_at = Column(DateTime, nullable=False)
    left_unanswered_at = Column(DateTime)
    resolution = Column(String(32), nullable=False, default="pending")
    response_lower_minutes = Column(Float)
    response_upper_minutes = Column(Float)
    response_estimate_minutes = Column(Float)
    baseline = Column(Boolean, nullable=False, default=False)
    last_checked_at = Column(DateTime, nullable=False, default=datetime.utcnow)

class YandexReviewResponseMonitorState(Base):
    __tablename__ = "yandex_review_response_monitor_state"
    organization_id = Column(Integer, primary_key=True, server_default=text("current_setting('app.organization_id', true)::integer"))
    business_id = Column(BigInteger, primary_key=True)
    initialized_at = Column(DateTime, nullable=False)
    last_poll_at = Column(DateTime, nullable=False)
    last_current_count = Column(Integer, nullable=False, default=0)
