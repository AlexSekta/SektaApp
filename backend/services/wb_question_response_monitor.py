import time
from datetime import datetime
from threading import RLock

from sqlalchemy.orm import Session

from backend.database import Base, engine
from backend.logging_config import get_logger
from backend.models.wb_question import WBQuestion
from backend.models.wb_question_response_monitor_state import WBQuestionResponseMonitorState
from backend.models.wb_question_response_tracking import WBQuestionResponseTracking
from backend.services.marketplace_clients import get_wb_client

logger = get_logger("wb_question_response_monitor")
MONITOR_LOCK = RLock()
MONITOR_TAKE = 5000


def ensure_wb_question_response_monitor_schema():
    Base.metadata.create_all(
        bind=engine,
        tables=[
            WBQuestionResponseTracking.__table__,
            WBQuestionResponseMonitorState.__table__,
        ],
    )

    with engine.begin() as conn:
        conn.exec_driver_sql(
            "GRANT SELECT, INSERT, UPDATE, DELETE ON TABLE "
            "wb_question_response_tracking, wb_question_response_monitor_state "
            "TO marketplace_app"
        )
        for table in (
            "wb_question_response_tracking",
            "wb_question_response_monitor_state",
        ):
            conn.exec_driver_sql(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY")
            conn.exec_driver_sql(f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY")
            conn.exec_driver_sql(
                f"DROP POLICY IF EXISTS tenant_isolation ON {table}"
            )
            conn.exec_driver_sql(
                f"""
                CREATE POLICY tenant_isolation ON {table}
                USING (
                    organization_id =
                    current_setting('app.organization_id', true)::integer
                )
                WITH CHECK (
                    organization_id =
                    current_setting('app.organization_id', true)::integer
                )
                """
            )


def _parse_datetime(value):
    if not value:
        return None
    try:
        return datetime.fromisoformat(
            str(value).replace("Z", "+00:00")
        ).replace(tzinfo=None)
    except (TypeError, ValueError):
        return None


def _fetch_current_unanswered(client):
    items = []
    skip = 0

    for _ in range(100):
        last_error = None
        for attempt in range(4):
            try:
                response = client.get_questions(
                    is_answered=False,
                    take=MONITOR_TAKE,
                    skip=skip,
                    order="dateDesc",
                )
                page = (response.get("data") or {}).get("questions") or []
                items.extend(page)
                break
            except Exception as exc:
                last_error = exc
                status_code = getattr(exc, "status_code", None)
                if status_code not in (429, 500, 502, 503, 504) or attempt >= 3:
                    raise
                time.sleep(2 ** attempt)
        else:
            raise last_error

        if len(page) < MONITOR_TAKE:
            break
        skip += len(page)

    return items


def _estimate_minutes(question_created_at, last_seen_at, left_at):
    """Missing observation timestamps must not crash the monitor or invent durations."""
    if question_created_at is None:
        return None, None, None
    lower = None
    upper = None
    if last_seen_at is not None:
        lower = max(0.0, (last_seen_at - question_created_at).total_seconds() / 60.0)
    if left_at is not None:
        upper = max(0.0, (left_at - question_created_at).total_seconds() / 60.0)
        if lower is not None:
            upper = max(upper, lower)
    estimate = (lower + upper) / 2.0 if lower is not None and upper is not None else None
    return lower, upper, estimate


def _finalize_answered(db, organization_id, now):
    pending = (
        db.query(WBQuestionResponseTracking)
        .filter(
            WBQuestionResponseTracking.organization_id == organization_id,
            WBQuestionResponseTracking.left_unanswered_at.is_not(None),
            WBQuestionResponseTracking.resolution == "pending",
        )
        .all()
    )

    finalized = 0

    for item in pending:
        question = (
            db.query(WBQuestion)
            .filter(
                WBQuestion.organization_id == organization_id,
                WBQuestion.question_id == item.question_id,
            )
            .one_or_none()
        )

        if question is None or not question.seller_has_answer:
            continue

        lower, upper, estimate = _estimate_minutes(
            item.question_created_at,
            item.last_seen_unanswered_at,
            item.left_unanswered_at,
        )

        item.resolution = "answered"
        # Baseline questions can be confirmed as answered, but their response
        # durations must not enter the historical response-time statistics.
        item.response_lower_minutes = None if item.baseline else lower
        item.response_upper_minutes = None if item.baseline else upper
        item.response_estimate_minutes = None if item.baseline else estimate
        item.last_checked_at = now
        finalized += 1

    return finalized


def monitor_wb_question_responses(db: Session, organization_id: int):
    # Schema/RLS setup is performed once by the scheduler before the DB role
    # is switched to marketplace_app. Do not ALTER TABLE on every polling cycle.
    with MONITOR_LOCK:
        now = datetime.utcnow()
        client = get_wb_client(db)

        raw_items = _fetch_current_unanswered(client)
        current = {}

        for item in raw_items:
            question_id = item.get("id")
            if question_id is None:
                continue

            current[str(question_id)] = _parse_datetime(
                item.get("createdDate")
            )

        state = (
            db.query(WBQuestionResponseMonitorState)
            .filter(
                WBQuestionResponseMonitorState.organization_id == organization_id
            )
            .one_or_none()
        )

        if state is None:
            for question_id, created_at in current.items():
                db.add(
                    WBQuestionResponseTracking(
                        organization_id=organization_id,
                        question_id=question_id,
                        question_created_at=created_at,
                        first_seen_unanswered_at=now,
                        last_seen_unanswered_at=now,
                        baseline=True,
                        last_checked_at=now,
                    )
                )

            db.add(
                WBQuestionResponseMonitorState(
                    organization_id=organization_id,
                    initialized_at=now,
                    last_poll_at=now,
                    last_current_count=len(current),
                )
            )
            db.commit()

            logger.info(
                "WB_QUESTION_RESPONSE_MONITOR_BASELINE | current=%s",
                len(current),
            )
            return {
                "status": "ok",
                "baseline": True,
                "current_unanswered": len(current),
                "new_tracked": 0,
                "left_queue": 0,
                "answered_finalized": 0,
            }

        active = (
            db.query(WBQuestionResponseTracking)
            .filter(
                WBQuestionResponseTracking.organization_id == organization_id,
                WBQuestionResponseTracking.left_unanswered_at.is_(None),
            )
            .all()
        )
        active_by_id = {row.question_id: row for row in active}

        new_tracked = 0

        for question_id, created_at in current.items():
            row = active_by_id.get(question_id)

            if row is not None:
                row.last_seen_unanswered_at = now
                row.last_checked_at = now
                if row.question_created_at is None:
                    row.question_created_at = created_at
                continue

            existing = (
                db.query(WBQuestionResponseTracking)
                .filter(
                    WBQuestionResponseTracking.organization_id == organization_id,
                    WBQuestionResponseTracking.question_id == question_id,
                )
                .one_or_none()
            )

            if existing is not None:
                existing.left_unanswered_at = None
                existing.resolution = None
                existing.response_lower_minutes = None
                existing.response_upper_minutes = None
                existing.response_estimate_minutes = None
                existing.last_seen_unanswered_at = now
                existing.last_checked_at = now
                if existing.question_created_at is None:
                    existing.question_created_at = created_at
            else:
                db.add(
                    WBQuestionResponseTracking(
                        organization_id=organization_id,
                        question_id=question_id,
                        question_created_at=created_at,
                        first_seen_unanswered_at=now,
                        last_seen_unanswered_at=now,
                        baseline=False,
                        last_checked_at=now,
                    )
                )
                new_tracked += 1

        left_queue = 0

        for row in active:
            if row.question_id not in current:
                row.left_unanswered_at = now
                row.resolution = "pending"
                row.last_checked_at = now
                left_queue += 1

        answered_finalized = _finalize_answered(
            db,
            organization_id,
            now,
        )

        state.last_poll_at = now
        state.last_current_count = len(current)
        db.commit()

        logger.info(
            "WB_QUESTION_RESPONSE_MONITOR_OK | current=%s new=%s "
            "left_queue=%s answered_finalized=%s",
            len(current),
            new_tracked,
            left_queue,
            answered_finalized,
        )

        return {
            "status": "ok",
            "baseline": False,
            "current_unanswered": len(current),
            "new_tracked": new_tracked,
            "left_queue": left_queue,
            "answered_finalized": answered_finalized,
        }
