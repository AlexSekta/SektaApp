from datetime import datetime

from sqlalchemy import BigInteger, Boolean, Column, DateTime, Integer, JSON, String, Text, UniqueConstraint, text
from backend.database import Base


class WBReview(Base):
    __tablename__ = "wb_reviews"
    organization_id = Column(Integer, nullable=False, index=True, server_default=text("current_setting(\'app.organization_id\', true)::integer"))
    __table_args__ = (UniqueConstraint("organization_id", "feedback_id", name="uq_wb_review_feedback_id"),)

    id = Column(Integer, primary_key=True)
    feedback_id = Column(String(128), nullable=False, index=True)
    text = Column(Text, nullable=False, default="")
    pros = Column(Text, nullable=False, default="")
    cons = Column(Text, nullable=False, default="")
    rating = Column(Integer, nullable=True)
    created_at = Column(DateTime, nullable=True, index=True)
    updated_at = Column(DateTime, nullable=True)
    buyer_name = Column(String, nullable=True)
    article = Column(String, nullable=True, index=True)
    nm_id = Column(BigInteger, nullable=True, index=True)
    product_name = Column(String, nullable=True)
    brand_name = Column(String, nullable=True)
    subject_name = Column(String, nullable=True)
    color = Column(String, nullable=True)
    photo_links = Column(JSON, nullable=False, default=list)
    bables = Column(JSON, nullable=False, default=list)
    was_viewed = Column(Boolean, nullable=False, default=False)
    state = Column(String, nullable=True)
    seller_has_answer = Column(Boolean, nullable=False, default=False, index=True)
    answer_id = Column(String(128), nullable=True, index=True)
    answer_text = Column(Text, nullable=True)
    answer_state = Column(String, nullable=True)
    answer_editable = Column(Boolean, nullable=False, default=False)
    answer_created_at = Column(DateTime, nullable=True)
    last_synced_at = Column(DateTime, nullable=False, default=datetime.utcnow, index=True)
    raw_data = Column(JSON, nullable=True)
