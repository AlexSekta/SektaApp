from datetime import datetime

from sqlalchemy import Boolean, Column, DateTime, Float, Integer, String, UniqueConstraint, text

from backend.database import Base


class WBReviewResponseTracking(Base):
    __tablename__ = "wb_review_response_tracking"

    organization_id = Column(Integer, primary_key=True, nullable=False, index=True,
                             server_default=text("current_setting('app.organization_id', true)::integer"))
    feedback_id = Column(String(128), primary_key=True, nullable=False)
    review_created_at = Column(DateTime, nullable=True, index=True)
    first_seen_unanswered_at = Column(DateTime, nullable=False)
    last_seen_unanswered_at = Column(DateTime, nullable=False)
    left_unanswered_at = Column(DateTime, nullable=True)
    resolution = Column(String(32), nullable=True, index=True)
    response_lower_minutes = Column(Float, nullable=True)
    response_upper_minutes = Column(Float, nullable=True)
    response_estimate_minutes = Column(Float, nullable=True)
    baseline = Column(Boolean, nullable=False, default=False)
    last_checked_at = Column(DateTime, nullable=False, default=datetime.utcnow)

    __table_args__ = (
        UniqueConstraint("organization_id", "feedback_id",
                         name="uq_wb_review_response_tracking_org_feedback"),
    )
