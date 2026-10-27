from datetime import datetime

from sqlalchemy import Column, DateTime, Integer, text

from backend.database import Base


class WBQuestionResponseMonitorState(Base):
    __tablename__ = "wb_question_response_monitor_state"

    organization_id = Column(
        Integer,
        primary_key=True,
        nullable=False,
        server_default=text("current_setting('app.organization_id', true)::integer"),
    )
    initialized_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    last_poll_at = Column(DateTime, nullable=True)
    last_current_count = Column(Integer, nullable=False, default=0)
