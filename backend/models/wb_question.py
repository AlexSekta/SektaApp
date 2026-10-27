from datetime import datetime

from sqlalchemy import BigInteger, Boolean, Column, DateTime, Integer, JSON, String, Text, UniqueConstraint, text

from backend.database import Base


class WBQuestion(Base):
    __tablename__ = "wb_questions"
    organization_id = Column(Integer, nullable=False, index=True, server_default=text("current_setting(\'app.organization_id\', true)::integer"))
    __table_args__ = (UniqueConstraint("organization_id", "question_id", name="uq_wb_question_question_id"),)

    id = Column(Integer, primary_key=True)
    question_id = Column(String(128), nullable=False, index=True)
    text = Column(Text, nullable=False, default="")
    created_at = Column(DateTime, nullable=True, index=True)
    updated_at = Column(DateTime, nullable=True)
    article = Column(String, nullable=True, index=True)
    nm_id = Column(BigInteger, nullable=True, index=True)
    product_name = Column(String, nullable=True)
    brand_name = Column(String, nullable=True)
    was_viewed = Column(Boolean, nullable=False, default=False)
    is_warned = Column(Boolean, nullable=False, default=False)
    state = Column(String, nullable=True)
    seller_has_answer = Column(Boolean, nullable=False, default=False, index=True)
    answer_id = Column(String(128), nullable=True, index=True)
    answer_text = Column(Text, nullable=True)
    answer_state = Column(String, nullable=True)
    answer_editable = Column(Boolean, nullable=False, default=False)
    answer_created_at = Column(DateTime, nullable=True)
    last_synced_at = Column(DateTime, nullable=False, default=datetime.utcnow, index=True)
    raw_data = Column(JSON, nullable=True)
