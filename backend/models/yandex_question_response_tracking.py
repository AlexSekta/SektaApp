from datetime import datetime
from sqlalchemy import BigInteger, Boolean, Column, DateTime, Float, Integer, String, text
from backend.database import Base


class YandexQuestionResponseTracking(Base):
    __tablename__ = 'yandex_question_response_tracking'
    organization_id = Column(Integer, primary_key=True, server_default=text("current_setting('app.organization_id', true)::integer"))
    business_id = Column(BigInteger, primary_key=True)
    question_id = Column(BigInteger, primary_key=True)
    question_created_at = Column(DateTime)
    first_seen_unanswered_at = Column(DateTime, nullable=False)
    last_seen_unanswered_at = Column(DateTime, nullable=False)
    left_unanswered_at = Column(DateTime)
    resolution = Column(String(32), nullable=False, default='pending')
    response_lower_minutes = Column(Float)
    response_upper_minutes = Column(Float)
    response_estimate_minutes = Column(Float)
    baseline = Column(Boolean, nullable=False, default=False)
    last_checked_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    consecutive_not_found = Column(Integer, nullable=False, default=0)
    last_not_found_at = Column(DateTime)
    unavailable_at = Column(DateTime)


class YandexQuestionResponseMonitorState(Base):
    __tablename__ = 'yandex_question_response_monitor_state'
    organization_id = Column(Integer, primary_key=True, server_default=text("current_setting('app.organization_id', true)::integer"))
    business_id = Column(BigInteger, primary_key=True)
    initialized_at = Column(DateTime, nullable=False)
    last_poll_at = Column(DateTime, nullable=False)
    last_current_count = Column(Integer, nullable=False, default=0)
