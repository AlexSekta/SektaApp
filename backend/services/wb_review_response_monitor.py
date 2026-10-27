import time
from datetime import datetime
from threading import RLock

from sqlalchemy.orm import Session

from backend.auth.tenant import set_tenant_context
from backend.database import Base, engine
from backend.logging_config import get_logger
from backend.models.wb_review import WBReview
from backend.models.wb_review_response_monitor_state import WBReviewResponseMonitorState
from backend.models.wb_review_response_tracking import WBReviewResponseTracking
from backend.services.marketplace_clients import get_wb_client

logger = get_logger("wb_review_response_monitor")
MONITOR_LOCK = RLock()
MONITOR_TAKE = 5000
UNANSWERED_FROM = datetime(2026, 1, 1)


def ensure_wb_review_response_monitor_schema():
    Base.metadata.create_all(
        bind=engine,
        tables=[
            WBReviewResponseTracking.__table__,
            WBReviewResponseMonitorState.__table__,
        ],
    )
    with engine.begin() as conn:
        conn.exec_driver_sql(
            "GRANT SELECT, INSERT, UPDATE, DELETE ON TABLE "
            "wb_review_response_tracking, wb_review_response_monitor_state "
            "TO marketplace_app"
        )
        for table in ("wb_review_response_tracking", "wb_review_response_monitor_state"):
            conn.exec_driver_sql(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY")
            conn.exec_driver_sql(f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY")
            conn.exec_driver_sql(f"DROP POLICY IF EXISTS tenant_isolation ON {table}")
            conn.exec_driver_sql(
                f"""CREATE POLICY tenant_isolation ON {table}
                USING (organization_id = current_setting('app.organization_id', true)::integer)
                WITH CHECK (organization_id = current_setting('app.organization_id', true)::integer)"""
            )


def _has_review_content(item):
    return bool(
        str(item.get("text") or "").strip()
        or str(item.get("pros") or "").strip()
        or str(item.get("cons") or "").strip()
        or (item.get("photoLinks") or [])
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
    for attempt in range(4):
        try:
            response = client.get_feedbacks(
                is_answered=False,
                take=MONITOR_TAKE,
                skip=0,
                order="dateDesc",
            )
            return (response.get("data") or {}).get("feedbacks") or []
        except Exception as exc:
            if attempt >= 3:
                raise
            status = getattr(exc, "status_code", None)
            if status not in (429, 500, 502, 503, 504):
                raise
            time.sleep(2 ** attempt)
    return []


def _estimate(review_created_at, last_seen_unanswered_at, left_at):
    """Bracket the reply between the last unanswered poll and first absent poll."""
    if not all((review_created_at, last_seen_unanswered_at, left_at)):
        return None, None, None
    if not (review_created_at <= last_seen_unanswered_at <= left_at):
        logger.warning(
            "WB_REVIEW_RESPONSE_INVALID_TIMELINE created=%s last_unanswered=%s left=%s",
            review_created_at, last_seen_unanswered_at, left_at,
        )
        return None, None, None
    lower = (last_seen_unanswered_at - review_created_at).total_seconds() / 60.0
    upper = (left_at - review_created_at).total_seconds() / 60.0
    return lower, upper, (lower + upper) / 2.0


def _finalize_answered(db, now, organization_id):
    pending = db.query(WBReviewResponseTracking).filter(
        WBReviewResponseTracking.left_unanswered_at.is_not(None),
        WBReviewResponseTracking.resolution == "pending",
        WBReviewResponseTracking.organization_id == organization_id,
    ).all()

    finalized = 0
    for item in pending:
        # Retry verification for baseline reviews too. Baseline is excluded
        # from response-time statistics, not from status confirmation.
        item.last_checked_at = now
        review = (
            db.query(WBReview)
            .filter(
                WBReview.organization_id == organization_id,
                WBReview.feedback_id == item.feedback_id,
            )
            .one_or_none()
        )
        if review is not None and review.seller_has_answer:
            if item.baseline:
                # A baseline review has unknown pre-monitoring wait time.
                lower = upper = estimate = None
            else:
                lower, upper, estimate = _estimate(
                    item.review_created_at,
                    item.last_seen_unanswered_at,
                    item.left_unanswered_at,
                )
            item.resolution = "answered"
            item.response_lower_minutes = lower
            item.response_upper_minutes = upper
            item.response_estimate_minutes = estimate
            item.last_checked_at = now
            finalized += 1
    return finalized


def monitor_wb_review_responses(db: Session, organization_id: int):
    # Schema/RLS setup is performed once by the scheduler before the DB role
    # is switched to marketplace_app. Do not ALTER TABLE on every polling
    # cycle: marketplace_app is not the owner of these tables.
    with MONITOR_LOCK:
        set_tenant_context(db, organization_id)
        now = datetime.utcnow()
        client = get_wb_client(db)

        raw_items = _fetch_current_unanswered(client)
        current = {}
        for item in raw_items:
            feedback_id = item.get("id")
            created_at = _parse_datetime(item.get("createdDate"))
            if feedback_id is None or not _has_review_content(item):
                continue
            if created_at is not None and created_at < UNANSWERED_FROM:
                continue
            current[str(feedback_id)] = created_at

        state = (
            db.query(WBReviewResponseMonitorState)
            .filter(
                WBReviewResponseMonitorState.organization_id == organization_id
            )
            .one_or_none()
        )

        if state is None:
            for feedback_id, created_at in current.items():
                db.add(
                    WBReviewResponseTracking(
                        organization_id=organization_id,
                        feedback_id=feedback_id,
                        review_created_at=created_at,
                        first_seen_unanswered_at=now,
                        last_seen_unanswered_at=now,
                        baseline=True,
                        last_checked_at=now,
                    )
                )
            db.add(
                WBReviewResponseMonitorState(
                    organization_id=organization_id,
                    initialized_at=now,
                    last_poll_at=now,
                    last_current_count=len(current),
                )
            )
            db.commit()
            logger.info(
                "WB_REVIEW_RESPONSE_MONITOR_BASELINE | current=%s",
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
            db.query(WBReviewResponseTracking)
            .filter(
                WBReviewResponseTracking.organization_id == organization_id,
                WBReviewResponseTracking.left_unanswered_at.is_(None),
            )
            .all()
        )
        active_by_id = {row.feedback_id: row for row in active}

        new_tracked = 0
        for feedback_id, created_at in current.items():
            row = active_by_id.get(feedback_id)
            if row is not None:
                row.last_seen_unanswered_at = now
                row.last_checked_at = now
                if row.review_created_at is None:
                    row.review_created_at = created_at
                continue

            existing = (
                db.query(WBReviewResponseTracking)
                .filter(
                    WBReviewResponseTracking.organization_id == organization_id,
                    WBReviewResponseTracking.feedback_id == feedback_id,
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
            else:
                db.add(
                    WBReviewResponseTracking(
                        organization_id=organization_id,
                        feedback_id=feedback_id,
                        review_created_at=created_at,
                        first_seen_unanswered_at=now,
                        last_seen_unanswered_at=now,
                        baseline=False,
                        last_checked_at=now,
                    )
                )
                new_tracked += 1

        left_queue = 0
        for row in active:
            if row.feedback_id not in current:
                row.left_unanswered_at = now
                row.resolution = "pending"
                row.last_checked_at = now
                left_queue += 1

        finalized = _finalize_answered(db, now, organization_id)
        state.last_poll_at = now
        state.last_current_count = len(current)
        db.commit()

        logger.info(
            "WB_REVIEW_RESPONSE_MONITOR_OK | current=%s new=%s left_queue=%s answered_finalized=%s",
            len(current), new_tracked, left_queue, finalized,
        )
        return {
            "status": "ok",
            "baseline": False,
            "current_unanswered": len(current),
            "new_tracked": new_tracked,
            "left_queue": left_queue,
            "answered_finalized": finalized,
        }
