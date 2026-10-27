from datetime import datetime
from sqlalchemy import BigInteger, Boolean, Column, DateTime, Integer, JSON, String, Text, UniqueConstraint, text
from backend.database import Base

class YandexReview(Base):
    __tablename__ = "yandex_reviews"
    organization_id = Column(Integer, nullable=False, index=True, server_default=text("current_setting(\'app.organization_id\', true)::integer"))
    __table_args__ = (UniqueConstraint("organization_id", "business_id", "feedback_id", name="uq_yandex_review_business_feedback"),)
    id = Column(Integer, primary_key=True)
    business_id = Column(BigInteger, nullable=False, index=True)
    feedback_id = Column(String(128), nullable=False, index=True)
    created_at = Column(DateTime, nullable=True, index=True)
    author = Column(String, nullable=True)
    offer_id = Column(String, nullable=True, index=True)
    order_id = Column(BigInteger, nullable=True, index=True)
    product_name = Column(String, nullable=True)
    advantages = Column(Text, nullable=False, default="")
    disadvantages = Column(Text, nullable=False, default="")
    comment = Column(Text, nullable=False, default="")
    rating = Column(Integer, nullable=True)
    recommended = Column(Boolean, nullable=True)
    paid_amount = Column(Integer, nullable=True)
    photos = Column(JSON, nullable=False, default=list)
    videos = Column(JSON, nullable=False, default=list)
    comments_count = Column(Integer, nullable=False, default=0)
    seller_comments_count = Column(Integer, nullable=False, default=0)
    seller_has_answer = Column(Boolean, nullable=False, default=False, index=True)
    waiting_for_seller = Column(Boolean, nullable=False, default=False, index=True)
    last_synced_at = Column(DateTime, nullable=False, default=datetime.utcnow, index=True)
    raw_data = Column(JSON, nullable=True)
