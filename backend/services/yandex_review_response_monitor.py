from datetime import datetime
from threading import RLock
from sqlalchemy.orm import Session
from backend.database import Base, engine
from backend.logging_config import get_logger
from backend.auth.tenant import set_tenant_context
from backend.services.marketplace_clients import get_yandex_client, get_yandex_business_id
from backend.services.yandex_review_sync import _iter_feedbacks, _load_comments, _parse_datetime
from backend.models.yandex_review_response_tracking import YandexReviewResponseTracking as Tracking, YandexReviewResponseMonitorState as State
from backend.models.yandex_review import YandexReview

logger = get_logger('yandex_review_response_monitor')


def _is_substantive(item):
    """Exclude rating-only feedbacks; text, media or selected tags qualify."""
    description = item.get('description') or {}
    media = item.get('media') or {}
    return (any(str(description.get(k) or '').strip() for k in
                ('comment', 'advantages', 'disadvantages', 'pros', 'cons'))
            or bool(description.get('tags') or media.get('photos') or media.get('videos')))

LOCK = RLock()

def ensure_yandex_review_response_schema():
    Base.metadata.create_all(bind=engine, tables=[Tracking.__table__, State.__table__])
    with engine.begin() as conn:
        for table in ('yandex_review_response_tracking', 'yandex_review_response_monitor_state'):
            conn.exec_driver_sql(f'GRANT SELECT, INSERT, UPDATE, DELETE ON {table} TO marketplace_app')
            conn.exec_driver_sql(f'ALTER TABLE {table} ENABLE ROW LEVEL SECURITY')
            conn.exec_driver_sql(f'ALTER TABLE {table} FORCE ROW LEVEL SECURITY')
            conn.exec_driver_sql(f'DROP POLICY IF EXISTS tenant_isolation ON {table}')
            conn.exec_driver_sql(f"""CREATE POLICY tenant_isolation ON {table}
                USING (organization_id = current_setting('app.organization_id', true)::integer)
                WITH CHECK (organization_id = current_setting('app.organization_id', true)::integer)""")

def monitor_yandex_review_responses(db: Session, organization_id: int):
    with LOCK:
        set_tenant_context(db, organization_id)
        client = get_yandex_client(db)
        business_id = int(get_yandex_business_id(db, client))
        # Fetch the entire NEED_REACTION queue before touching persistent state.
        current = {}
        inconsistent_flags = 0
        for item in _iter_feedbacks(client, business_id, None, None, 'NEED_REACTION'):
            feedback_id = str(item.get('feedbackId') or '')
            if feedback_id and _is_substantive(item):
                # The server-side NEED_REACTION filter is authoritative for
                # queue membership.  In practice the per-item needReaction flag
                # can be false even when the review is returned by this filter.
                current[feedback_id] = _parse_datetime(item.get('createdAt'))
                if item.get('needReaction') is False:
                    inconsistent_flags += 1
        if inconsistent_flags:
            logger.warning('YANDEX_REVIEW_NEED_REACTION_FLAG_MISMATCH business_id=%s count=%s',
                           business_id, inconsistent_flags)
        now = datetime.utcnow()
        state = db.query(State).filter_by(organization_id=organization_id, business_id=business_id).one_or_none()
        if state is None:
            for fid, created in current.items():
                db.add(Tracking(organization_id=organization_id, business_id=business_id,
                    feedback_id=fid, review_created_at=created,
                    first_seen_unanswered_at=now, last_seen_unanswered_at=now,
                    baseline=True, last_checked_at=now))
            db.add(State(organization_id=organization_id,business_id=business_id,
                initialized_at=now,last_poll_at=now,last_current_count=len(current)))
            db.commit()
            return dict(baseline=True,current_unanswered=len(current),new_tracked=0,answered_finalized=0,verification_failed=0)
        existing = {r.feedback_id:r for r in db.query(Tracking).filter_by(organization_id=organization_id,business_id=business_id).all()}
        # Legacy tracking can contain rating-only reviews. They remain in the
        # database for audit but must not consume reply-verification API calls.
        stored_reviews = {str(r.feedback_id): r for r in db.query(YandexReview).filter_by(
            organization_id=organization_id, business_id=business_id).all()}
        def eligible_stored(fid):
            review = stored_reviews.get(fid)
            if review is None:
                return True  # Preserve tracking if the catalogue has not synced it yet.
            return _is_substantive(review.raw_data or {}) or bool(
                (review.comment or '').strip() or (review.advantages or '').strip()
                or (review.disadvantages or '').strip() or review.photos or review.videos)

        # Double-check ambiguous queue omissions using an ID-filtered request.
        # This request is supplementary: a missing ID is not proof of a reply.
        absent_ids = [fid for fid, row in existing.items()
                      if row.resolution == 'pending' and fid not in current
                      and eligible_stored(fid) and fid.isdecimal()]
        reentered = 0
        for offset in range(0, len(absent_ids), 50):
            batch = absent_ids[offset:offset + 50]
            try:
                data = client.get_goods_feedbacks(
                    business_id=business_id, limit=50,
                    reaction_status='NEED_REACTION', feedback_ids=[int(fid) for fid in batch])
                found = (data.get('result') or {}).get('feedbacks') or []
                for item in found:
                    fid = str(item.get('feedbackId') or '')
                    if fid in existing and fid not in current and _is_substantive(item):
                        current[fid] = _parse_datetime(item.get('createdAt'))
                        reentered += 1
            except Exception:
                # Do not claim the review left the queue when the second
                # source could not be checked. Retain its prior state.
                logger.exception('YANDEX_REVIEW_QUEUE_RECHECK_FAILED business_id=%s batch_size=%s',
                                 business_id, len(batch))
                for fid in batch:
                    if fid in existing:
                        current[fid] = existing[fid].review_created_at
        if reentered:
            logger.info('YANDEX_REVIEW_REENTERED_QUEUE business_id=%s count=%s', business_id, reentered)

        new_count=answered=errors=0
        for fid,created in current.items():
            r=existing.get(fid)
            if r is None:
                db.add(Tracking(organization_id=organization_id,business_id=business_id,
                    feedback_id=fid,review_created_at=created,
                    first_seen_unanswered_at=now,last_seen_unanswered_at=now,
                    baseline=False,last_checked_at=now))
                new_count+=1
            elif r.resolution == 'pending':
                r.last_seen_unanswered_at=now
                r.left_unanswered_at=None
                r.last_checked_at=now
                if r.review_created_at is None:
                    r.review_created_at=created
        for fid,r in existing.items():
            if fid in current or r.resolution != 'pending' or not eligible_stored(fid):
                continue
            # Require TWO successive complete polls without this review before
            # marking its exit. On the first absence, keep it actively awaiting
            # an answer. This avoids oscillation caused by transient API omissions.
            # last_checked_at acts as the first-miss marker when it is newer
            # than last_seen_unanswered_at; no schema migration is necessary.
            if r.left_unanswered_at is None:
                if r.last_checked_at <= r.last_seen_unanswered_at:
                    r.last_checked_at = now
                    continue
                r.left_unanswered_at = now
                logger.info('YANDEX_REVIEW_EXIT_CONFIRMED feedback_id=%s', fid)
            try:
                comments = _load_comments(client,business_id,int(fid))
            except Exception:
                errors+=1
                r.last_checked_at = now
                logger.exception('YANDEX_REVIEW_REPLY_VERIFY_FAILED feedback_id=%s',fid)
                continue
            r.last_checked_at = now
            if not any(c.get('author_type')=='BUSINESS' or c.get('can_modify') for c in comments):
                continue
            r.left_unanswered_at=now
            r.resolution='answered'
            r.last_checked_at=now
            if r.review_created_at and r.review_created_at <= r.last_seen_unanswered_at <= now:
                low=(r.last_seen_unanswered_at-r.review_created_at).total_seconds()/60
                high=(now-r.review_created_at).total_seconds()/60
                r.response_lower_minutes=low
                r.response_upper_minutes=high
                r.response_estimate_minutes=(low+high)/2
            answered+=1
        state.last_poll_at=now
        state.last_current_count=len(current)
        db.commit()
        return dict(baseline=False,current_unanswered=len(current),new_tracked=new_count,answered_finalized=answered,verification_failed=errors)
