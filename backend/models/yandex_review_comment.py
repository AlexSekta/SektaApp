from datetime import datetime
from sqlalchemy import BigInteger, Boolean, Column, DateTime, Integer, String, Text, UniqueConstraint, text
from backend.database import Base

class YandexReviewComment(Base):
    __tablename__ = "yandex_review_comments"
    organization_id = Column(Integer, nullable=False, index=True, server_default=text("current_setting(\'app.organization_id\', true)::integer"))
    __table_args__ = (UniqueConstraint("organization_id", "business_id", "feedback_id", "comment_id", name="uq_yandex_review_comment"),)
    id = Column(Integer, primary_key=True)
    business_id = Column(BigInteger, nullable=False, index=True)
    feedback_id = Column(String(128), nullable=False, index=True)
    comment_id = Column(BigInteger, nullable=False, index=True)
    parent_id = Column(BigInteger, nullable=True, index=True)
    text = Column(Text, nullable=False, default="")
    author = Column(String, nullable=True)
    author_type = Column(String, nullable=True, index=True)
    status = Column(String, nullable=True)
    can_modify = Column(Boolean, nullable=False, default=False)
    created_at = Column(DateTime, nullable=True)
    last_synced_at = Column(DateTime, nullable=False, default=datetime.utcnow, index=True)
