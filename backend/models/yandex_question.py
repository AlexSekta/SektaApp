from datetime import datetime

from sqlalchemy import BigInteger, Boolean, Column, DateTime, Integer, String, Text, UniqueConstraint, text

from backend.database import Base


class YandexQuestion(Base):
    __tablename__ = "yandex_questions"
    organization_id = Column(Integer, nullable=False, index=True, server_default=text("current_setting(\'app.organization_id\', true)::integer"))

    __table_args__ = (
        UniqueConstraint(
            "organization_id",
            "business_id",
            "question_id",
            name="uq_yandex_question_business_question",
        ),
    )

    id = Column(Integer, primary_key=True)
    business_id = Column(BigInteger, nullable=False, index=True)
    question_id = Column(BigInteger, nullable=False, index=True)
    offer_id = Column(String, nullable=True, index=True)
    product_name = Column(String, nullable=True)
    category_id = Column(BigInteger, nullable=True)
    text = Column(Text, nullable=False, default="")
    author = Column(String, nullable=True)
    author_type = Column(String, nullable=True)
    created_at = Column(DateTime, nullable=True, index=True)
    likes = Column(Integer, nullable=False, default=0)
    dislikes = Column(Integer, nullable=False, default=0)
    yandex_need_answer = Column(Boolean, nullable=False, default=False)
    # Реальное состояние очереди магазина. Не путать с yandex_need_answer:
    # web-кабинет Яндекса использует собственный фильтр merchAnswer=true.
    waiting_for_seller = Column(Boolean, nullable=False, default=False, index=True)
    seller_has_answer = Column(Boolean, nullable=False, default=False, index=True)
    answers_count = Column(Integer, nullable=False, default=0)
    seller_answers_count = Column(Integer, nullable=False, default=0)
    other_answers_count = Column(Integer, nullable=False, default=0)
    last_synced_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    last_answers_synced_at = Column(DateTime, nullable=True)
    answers_sync_ok = Column(Boolean, nullable=False, default=False, index=True)
    answers_sync_error = Column(Text, nullable=True)


class YandexQuestionAnswer(Base):
    __tablename__ = "yandex_question_answers"
    organization_id = Column(Integer, nullable=False, index=True, server_default=text("current_setting(\'app.organization_id\', true)::integer"))

    __table_args__ = (
        UniqueConstraint(
            "organization_id",
            "business_id",
            "question_id",
            "answer_id",
            name="uq_yandex_question_answer",
        ),
    )

    id = Column(Integer, primary_key=True)
    business_id = Column(BigInteger, nullable=False, index=True)
    question_id = Column(BigInteger, nullable=False, index=True)
    answer_id = Column(BigInteger, nullable=False, index=True)
    text = Column(Text, nullable=False, default="")
    author = Column(String, nullable=True)
    author_type = Column(String, nullable=True, index=True)
    status = Column(String, nullable=True)
    created_at = Column(DateTime, nullable=True, index=True)
    can_modify = Column(Boolean, nullable=False, default=False)


class YandexQuestionAnswerComment(Base):
    __tablename__ = "yandex_question_answer_comments"
    organization_id = Column(Integer, nullable=False, index=True, server_default=text("current_setting(\'app.organization_id\', true)::integer"))

    __table_args__ = (
        UniqueConstraint(
            "organization_id",
            "business_id",
            "question_id",
            "comment_id",
            name="uq_yandex_question_answer_comment",
        ),
    )

    id = Column(Integer, primary_key=True)
    business_id = Column(BigInteger, nullable=False, index=True)
    question_id = Column(BigInteger, nullable=False, index=True)
    answer_id = Column(BigInteger, nullable=True, index=True)
    comment_id = Column(BigInteger, nullable=False, index=True)
    text = Column(Text, nullable=False, default="")
    author = Column(String, nullable=True)
    author_type = Column(String, nullable=True)
    status = Column(String, nullable=True)
    parent_id = Column(BigInteger, nullable=True)
    can_modify = Column(Boolean, nullable=False, default=False)
