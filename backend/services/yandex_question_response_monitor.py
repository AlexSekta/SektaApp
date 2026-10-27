from datetime import datetime
from threading import RLock
from sqlalchemy.orm import Session
from sqlalchemy import text
from backend.marketplaces.yandex.client import YandexAPIError
from backend.database import Base, engine
from backend.logging_config import get_logger
from backend.auth.tenant import set_tenant_context
from backend.services.marketplace_clients import get_yandex_client, get_yandex_business_id
from backend.services.yandex_question_sync import (_fetch_question_answers, _is_seller_answer,
    _is_seller_comment, _replace_answers)
from backend.models.yandex_question import YandexQuestion
from backend.models.yandex_question_response_tracking import (
    YandexQuestionResponseTracking as Tracking, YandexQuestionResponseMonitorState as State)

logger = get_logger('yandex_question_response_monitor')
LOCK = RLock()


def ensure_yandex_question_response_schema():
    Base.metadata.create_all(bind=engine, tables=[Tracking.__table__, State.__table__])
    with engine.begin() as conn:
        # create_all does not add columns to pre-existing tables.
        conn.exec_driver_sql("""ALTER TABLE yandex_question_response_tracking
            ADD COLUMN IF NOT EXISTS consecutive_not_found INTEGER NOT NULL DEFAULT 0""")
        conn.exec_driver_sql("""ALTER TABLE yandex_question_response_tracking
            ADD COLUMN IF NOT EXISTS last_not_found_at TIMESTAMP""")
        conn.exec_driver_sql("""ALTER TABLE yandex_question_response_tracking
            ADD COLUMN IF NOT EXISTS unavailable_at TIMESTAMP""")
        for table in ('yandex_question_response_tracking', 'yandex_question_response_monitor_state'):
            conn.exec_driver_sql(f'GRANT SELECT, INSERT, UPDATE, DELETE ON {table} TO marketplace_app')
            conn.exec_driver_sql(f'ALTER TABLE {table} ENABLE ROW LEVEL SECURITY')
            conn.exec_driver_sql(f'ALTER TABLE {table} FORCE ROW LEVEL SECURITY')
            conn.exec_driver_sql(f'DROP POLICY IF EXISTS tenant_isolation ON {table}')
            conn.exec_driver_sql(f"""CREATE POLICY tenant_isolation ON {table}
                USING (organization_id = current_setting('app.organization_id', true)::integer)
                WITH CHECK (organization_id = current_setting('app.organization_id', true)::integer)""")


def monitor_yandex_question_responses(db: Session, organization_id: int):
    with LOCK:
        set_tenant_context(db, organization_id)
        client = get_yandex_client(db)
        business_id = int(get_yandex_business_id(db, client))
        # Existing sync discovers new questions every 15 minutes. This monitor independently
        # verifies answers through the questions/answers API every two minutes.
        questions = db.query(YandexQuestion).filter_by(
            organization_id=organization_id, business_id=business_id).all()
        now = datetime.utcnow()
        state = db.query(State).filter_by(organization_id=organization_id, business_id=business_id).one_or_none()
        candidates = [q for q in questions if q.waiting_for_seller and not q.seller_has_answer]
        if state is None:
            for q in candidates:
                db.add(Tracking(organization_id=organization_id,business_id=business_id,
                    question_id=q.question_id,question_created_at=q.created_at,
                    first_seen_unanswered_at=now,last_seen_unanswered_at=now,
                    baseline=True,last_checked_at=now))
            db.add(State(organization_id=organization_id,business_id=business_id,
                initialized_at=now,last_poll_at=now,last_current_count=len(candidates)))
            db.commit()
            return dict(baseline=True,current_unanswered=len(candidates),new_tracked=0,
                        answered_finalized=0,verification_failed=0)

        existing = {r.question_id:r for r in db.query(Tracking).filter_by(
            organization_id=organization_id,business_id=business_id).all()}
        new_count = answered = errors = unavailable = 0
        for q in candidates:
            r = existing.get(q.question_id)
            # Verify BEFORE registering an unanswered observation; an old DB status
            # is not proof that the question is still unanswered.
            try:
                answers, comments = _fetch_question_answers(client,business_id,int(q.question_id))
            except YandexAPIError as error:
                if error.status_code == 404:
                    # A single 404 is not enough to declare a question unavailable.
                    if r is not None and r.resolution == 'pending':
                        r.consecutive_not_found = (r.consecutive_not_found or 0) + 1
                        r.last_not_found_at = now
                        r.last_checked_at = now
                        if r.consecutive_not_found >= 3:
                            r.resolution = 'unavailable'
                            r.unavailable_at = now
                            # Do NOT infer that the seller answered.
                            q.waiting_for_seller = False
                            unavailable += 1
                            logger.warning('YANDEX_QUESTION_UNAVAILABLE question_id=%s checks=%s',
                                           q.question_id, r.consecutive_not_found)
                        else:
                            logger.warning('YANDEX_QUESTION_NOT_FOUND question_id=%s checks=%s/3',
                                           q.question_id, r.consecutive_not_found)
                    else:
                        logger.warning('YANDEX_QUESTION_NOT_FOUND untracked_question_id=%s', q.question_id)
                    continue
                errors += 1
                logger.exception('YANDEX_QUESTION_REPLY_VERIFY_FAILED question_id=%s',q.question_id)
                continue
            except Exception:
                errors += 1
                logger.exception('YANDEX_QUESTION_REPLY_VERIFY_FAILED question_id=%s',q.question_id)
                continue
            # Successful fetch resets the 404 streak; a reappeared question may be tracked again.
            if r is not None:
                r.consecutive_not_found = 0
                r.last_not_found_at = None
                if r.resolution == 'unavailable':
                    r.resolution = 'pending'
                    r.unavailable_at = None
            seller_answers = [a for a in answers if _is_seller_answer(a)]
            seller_comments = [c for c in comments if _is_seller_comment(c)]
            if seller_answers or seller_comments:
                _replace_answers(db,business_id,q.question_id,answers,comments)
                q.seller_has_answer = True
                q.waiting_for_seller = False
                q.answers_count = len(answers)
                q.seller_answers_count = len(seller_answers)
                q.other_answers_count = len(answers) - len(seller_answers)
                q.last_answers_synced_at = now
                q.answers_sync_ok = True
                q.answers_sync_error = None
                if r is not None and r.resolution == 'pending':
                    r.left_unanswered_at = now
                    r.resolution = 'answered'
                    r.last_checked_at = now
                    if r.question_created_at and r.question_created_at <= r.last_seen_unanswered_at <= now:
                        low = (r.last_seen_unanswered_at-r.question_created_at).total_seconds()/60
                        high = (now-r.question_created_at).total_seconds()/60
                        r.response_lower_minutes = low
                        r.response_upper_minutes = high
                        r.response_estimate_minutes = (low+high)/2
                    answered += 1
                continue
            if r is None:
                db.add(Tracking(organization_id=organization_id,business_id=business_id,
                    question_id=q.question_id,question_created_at=q.created_at,
                    first_seen_unanswered_at=now,last_seen_unanswered_at=now,
                    baseline=False,last_checked_at=now))
                new_count += 1
            elif r.resolution == 'pending':
                r.last_seen_unanswered_at = now
                r.last_checked_at = now
                if r.question_created_at is None:
                    r.question_created_at = q.created_at

        # Questions answered by the separate 15-minute sync can be finalized only
        # after a fresh, successful API verification (never from a stale DB flag).
        for q in questions:
            r = existing.get(q.question_id)
            if not r or r.resolution != 'pending' or q in candidates or not q.seller_has_answer:
                continue
            try:
                answers, comments = _fetch_question_answers(client,business_id,int(q.question_id))
            except Exception:
                errors += 1
                continue
            if not (any(_is_seller_answer(a) for a in answers) or
                    any(_is_seller_comment(c) for c in comments)):
                continue
            r.left_unanswered_at = now
            r.resolution = 'answered'
            r.last_checked_at = now
            if r.question_created_at and r.question_created_at <= r.last_seen_unanswered_at <= now:
                low = (r.last_seen_unanswered_at-r.question_created_at).total_seconds()/60
                high = (now-r.question_created_at).total_seconds()/60
                r.response_lower_minutes = low
                r.response_upper_minutes = high
                r.response_estimate_minutes = (low+high)/2
            answered += 1
        state.last_poll_at = now
        state.last_current_count = sum(1 for q in candidates if not q.seller_has_answer
                                       and (existing.get(q.question_id) is None or
                                            existing[q.question_id].resolution == 'pending'))
        # SQLAlchemy expires ORM fields on commit. Capture the count before commit,
        # otherwise accessing state.last_current_count can trigger a SELECT on a new
        # pooled connection with no tenant GUC, failing the RLS ::integer cast.
        current_unanswered_count = state.last_current_count
        db.commit()
        return dict(baseline=False,current_unanswered=current_unanswered_count,
                    new_tracked=new_count,answered_finalized=answered,verification_failed=errors,
                    unavailable_marked=unavailable)
