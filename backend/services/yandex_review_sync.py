import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timedelta, timezone
from threading import RLock

from sqlalchemy import func, inspect, text
from sqlalchemy.orm import Session

from backend.database import Base, engine
from backend.logging_config import get_logger
from backend.marketplaces.yandex.client import YandexAPIError, YandexClient
from backend.services.marketplace_clients import get_yandex_client, get_yandex_business_id
from backend.models.master_product import MasterProduct
from backend.models.yandex_review import YandexReview
from backend.models.yandex_review_comment import YandexReviewComment

logger = get_logger("yandex_reviews_sync")
SYNC_LOCK = RLock()
PAGE_SIZE = 50
WINDOW_DAYS = 180
INCREMENTAL_DAYS = 31
MAX_EMPTY_WINDOWS = 2
COMMENT_WORKERS = 4
MAX_RETRIES = 4
RETRY_BACKOFF = 1.5
STALE_RECHECK_WINDOW_DAYS = 7


def ensure_yandex_review_tables():
    Base.metadata.create_all(bind=engine, tables=[YandexReview.__table__, YandexReviewComment.__table__])

    # Yandex feedbackId is a string (it may contain letters).
    # create_all() does not alter existing PostgreSQL columns, so migrate
    # legacy BIGINT columns in-place without dropping any data.
    inspector = inspect(engine)

    def _column_type(table_name, column_name):
        columns = inspector.get_columns(table_name)
        for column in columns:
            if column["name"] == column_name:
                return column["type"]
        return None

    with engine.begin() as conn:
        review_feedback_type = _column_type("yandex_reviews", "feedback_id")
        if review_feedback_type is not None and "CHAR" not in str(review_feedback_type).upper() and "TEXT" not in str(review_feedback_type).upper():
            conn.execute(text(
                "ALTER TABLE yandex_reviews "
                "ALTER COLUMN feedback_id TYPE VARCHAR(128) "
                "USING feedback_id::text"
            ))

        comment_feedback_type = _column_type("yandex_review_comments", "feedback_id")
        if comment_feedback_type is not None and "CHAR" not in str(comment_feedback_type).upper() and "TEXT" not in str(comment_feedback_type).upper():
            conn.execute(text(
                "ALTER TABLE yandex_review_comments "
                "ALTER COLUMN feedback_id TYPE VARCHAR(128) "
                "USING feedback_id::text"
            ))


def _parse_datetime(value):
    if not value:
        return None
    if isinstance(value, datetime):
        return value.replace(tzinfo=None)
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00")).replace(tzinfo=None)
    except (TypeError, ValueError):
        return None


def _iso_utc(value: datetime) -> str:
    return value.replace(tzinfo=timezone.utc).isoformat().replace("+00:00", "Z")


def _resolve_business_id(client, business_id, db):
    if business_id is not None:
        return int(business_id)
    return get_yandex_business_id(db, client)


def _request_feedback_page(client, business_id, page_token, date_from, date_to, reaction_status):
    for attempt in range(MAX_RETRIES + 1):
        try:
            return client.get_goods_feedbacks(
                business_id=business_id,
                limit=PAGE_SIZE,
                page_token=page_token,
                reaction_status=reaction_status,
                date_time_from=_iso_utc(date_from) if date_from else None,
                date_time_to=_iso_utc(date_to) if date_to else None,
            )
        except YandexAPIError as error:
            if error.status_code not in (420, 429, 500, 502, 503, 504) or attempt >= MAX_RETRIES:
                raise
            time.sleep(RETRY_BACKOFF * (2 ** attempt))
    raise RuntimeError("Не удалось получить страницу отзывов Яндекс Маркета.")


def _iter_feedbacks(client, business_id, date_from, date_to, reaction_status="ALL"):
    page_token = None
    while True:
        data = _request_feedback_page(client, business_id, page_token, date_from, date_to, reaction_status)
        result = data.get("result", {}) or {}
        yield from (result.get("feedbacks", []) or [])
        paging = result.get("paging", {}) or {}
        next_token = paging.get("nextPageToken")
        if not next_token or next_token == page_token:
            break
        page_token = next_token


def _normalize_review(item, business_id, product_names):
    identifiers = item.get("identifiers") or {}
    description = item.get("description") or {}
    media = item.get("media") or {}
    statistics = item.get("statistics") or {}
    feedback_id = str(item["feedbackId"])
    offer_id = identifiers.get("offerId")
    return {
        "business_id": int(business_id),
        "feedback_id": feedback_id,
        "created_at": _parse_datetime(item.get("createdAt")),
        "author": item.get("author") or "Покупатель",
        "offer_id": offer_id,
        "order_id": identifiers.get("orderId"),
        "product_name": product_names.get(str(offer_id)) if offer_id else None,
        "advantages": description.get("advantages") or "",
        "disadvantages": description.get("disadvantages") or "",
        "comment": description.get("comment") or "",
        "rating": statistics.get("rating"),
        "recommended": statistics.get("recommended"),
        "paid_amount": statistics.get("paidAmount"),
        "photos": media.get("photos") or [],
        "videos": media.get("videos") or [],
        "comments_count": int(statistics.get("commentsCount", 0) or 0),
        "waiting_for_seller": bool(item.get("needReaction")),
        "raw_data": item,
    }


def _upsert_review(db, payload):
    row = db.query(YandexReview).filter(
        YandexReview.business_id == payload["business_id"],
        YandexReview.feedback_id == payload["feedback_id"],
    ).one_or_none()

    if row is None:
        row = YandexReview(**payload)
        db.add(row)
        db.flush()
        return row, True, True

    changed = False
    for key, value in payload.items():
        if getattr(row, key) != value:
            setattr(row, key, value)
            changed = True

    row.last_synced_at = datetime.utcnow()
    return row, False, changed

def _load_comments(client, business_id, feedback_id):
    comments = []
    page_token = None
    for _ in range(100):
        for attempt in range(MAX_RETRIES + 1):
            try:
                data = client.get_goods_feedback_comments(
                    business_id=business_id,
                    feedback_id=feedback_id,
                    limit=50,
                    page_token=page_token,
                )
                break
            except YandexAPIError as error:
                if error.status_code not in (420, 429, 500, 502, 503, 504) or attempt >= MAX_RETRIES:
                    raise
                time.sleep(RETRY_BACKOFF * (2 ** attempt))
        result = data.get("result", {}) or {}
        for item in result.get("comments", []) or []:
            author = item.get("author") or {}
            comments.append({
                "business_id": int(business_id),
                "feedback_id": str(feedback_id),
                "comment_id": int(item["id"]),
                "parent_id": item.get("parentId"),
                "text": item.get("text") or "",
                "author": author.get("name") or "",
                "author_type": author.get("type"),
                "status": item.get("status"),
                "can_modify": bool(item.get("canModify")),
                "created_at": _parse_datetime(item.get("createdAt")),
            })
        paging = result.get("paging", {}) or {}
        next_token = paging.get("nextPageToken")
        if not next_token or next_token == page_token:
            break
        page_token = next_token
    return comments


def _sync_comments(db, client, business_id, review_rows, previously_unanswered=None):
    previously_unanswered = previously_unanswered or set()
    # The marketplace may not include an updated commentsCount in a feedback
    # snapshot. Always verify a previously pending review after needReaction drops.
    targets = [
        r for r in review_rows
        if int(r.comments_count or 0) > 0
        or (str(r.feedback_id) in previously_unanswered and not r.waiting_for_seller)
    ]
    if not targets:
        return 0, 0, 0, []
    new_count = updated_count = 0
    seller_review_ids = set()
    errors = []

    def load(review):
        return review, _load_comments(client, business_id, review.feedback_id)

    with ThreadPoolExecutor(max_workers=min(COMMENT_WORKERS, len(targets))) as executor:
        futures = [executor.submit(load, review) for review in targets]
        for future in as_completed(futures):
            review = None
            try:
                review, comments = future.result()
            except Exception as error:
                if review is not None:
                    errors.append({"feedback_id": str(review.feedback_id), "message": str(error)})
                continue

            seller_count = 0
            for payload in comments:
                row = db.query(YandexReviewComment).filter(
                    YandexReviewComment.business_id == payload["business_id"],
                    YandexReviewComment.feedback_id == payload["feedback_id"],
                    YandexReviewComment.comment_id == payload["comment_id"],
                ).one_or_none()
                if row is None:
                    db.add(YandexReviewComment(**payload))
                    new_count += 1
                else:
                    for key, value in payload.items():
                        setattr(row, key, value)
                    row.last_synced_at = datetime.utcnow()
                    updated_count += 1
                if payload["author_type"] == "BUSINESS" or payload["can_modify"]:
                    seller_count += 1

            review.seller_comments_count = seller_count
            review.seller_has_answer = seller_count > 0
            review.last_synced_at = datetime.utcnow()
            if seller_count > 0:
                seller_review_ids.add(str(review.feedback_id))
                review.waiting_for_seller = False

    return new_count, updated_count, len(seller_review_ids), errors


def _counts(db, business_id):
    base = db.query(YandexReview).filter(YandexReview.business_id == business_id)
    total = int(base.with_entities(func.count(YandexReview.id)).scalar() or 0)
    answered = int(base.filter(YandexReview.seller_has_answer.is_(True)).with_entities(func.count(YandexReview.id)).scalar() or 0)
    unanswered = int(base.filter(YandexReview.waiting_for_seller.is_(True)).with_entities(func.count(YandexReview.id)).scalar() or 0)
    return total, answered, unanswered


def _iter_stale_pending_feedbacks(db, client, business_id, start, now, seen):
    """Revisit old pending reviews that disappeared from NEED_REACTION.

    Query narrow creation-date windows with reaction_status=ALL, rather than
    retrieving the entire six-month archive on each scheduled run.
    """
    pending = db.query(YandexReview.feedback_id, YandexReview.created_at).filter(
        YandexReview.business_id == business_id,
        YandexReview.waiting_for_seller.is_(True),
        YandexReview.created_at.isnot(None),
        YandexReview.created_at < start,
    ).all()
    targets = {str(feedback_id) for feedback_id, _ in pending}
    oldest_supported = now - timedelta(days=WINDOW_DAYS)
    buckets = set()
    for _, created_at in pending:
        if created_at < oldest_supported:
            continue
        # Group into fixed seven-day windows, with a safety margin for the
        # timezone conversion of timestamps in the legacy database.
        buckets.add((created_at.date().toordinal() // STALE_RECHECK_WINDOW_DAYS))

    fetched = 0
    for bucket in sorted(buckets):
        start_date = datetime.fromordinal(bucket * STALE_RECHECK_WINDOW_DAYS) - timedelta(days=1)
        end_date = start_date + timedelta(days=STALE_RECHECK_WINDOW_DAYS + 2)
        for item in _iter_feedbacks(client, business_id, start_date, min(end_date, now), "ALL"):
            fid = item.get("feedbackId")
            if fid is None or str(fid) not in targets or str(fid) in seen:
                continue
            seen.add(str(fid))
            fetched += 1
            yield item
    missed = len(targets - seen)
    if missed:
        logger.warning("YANDEX_REVIEW_STALE_NOT_FOUND business_id=%s count=%s", business_id, missed)
    logger.info("YANDEX_REVIEW_STALE_RECHECK business_id=%s pending=%s fetched=%s windows=%s",
                business_id, len(targets), fetched, len(buckets))


def sync_yandex_reviews(db, business_id=None, force_full=False):
    ensure_yandex_review_tables()
    with SYNC_LOCK:
        client = get_yandex_client(db)
        business_id = _resolve_business_id(client, business_id, db)
        existing = int(db.query(func.count(YandexReview.id)).filter(YandexReview.business_id == business_id).scalar() or 0)
        mode = "full" if force_full or existing == 0 else "incremental"
        now = datetime.utcnow()
        seen = set()
        previously_unanswered = {str(fid) for (fid,) in db.query(YandexReview.feedback_id).filter(
            YandexReview.business_id == business_id,
            YandexReview.waiting_for_seller.is_(True),
        ).all()}
        items = []
        windows = 0

        if mode == "full":
            cursor = now
            empty_windows = 0
            while empty_windows < MAX_EMPTY_WINDOWS:
                start = cursor - timedelta(days=WINDOW_DAYS)
                batch = []
                for item in _iter_feedbacks(client, business_id, start, cursor, "ALL"):
                    fid = item.get("feedbackId")
                    if fid is None or str(fid) in seen:
                        continue
                    seen.add(str(fid))
                    batch.append(item)
                items.extend(batch)
                windows += 1
                empty_windows = 0 if batch else empty_windows + 1
                cursor = start
        else:
            last_sync = db.query(func.max(YandexReview.last_synced_at)).filter(YandexReview.business_id == business_id).scalar()
            start = (last_sync or (now - timedelta(days=INCREMENTAL_DAYS))) - timedelta(days=3)
            start = max(start, now - timedelta(days=WINDOW_DAYS))
            for item in _iter_feedbacks(client, business_id, start, now, "ALL"):
                fid = item.get("feedbackId")
                if fid is None or str(fid) in seen:
                    continue
                seen.add(str(fid))
                items.append(item)
            for item in _iter_feedbacks(client, business_id, now - timedelta(days=WINDOW_DAYS), now, "NEED_REACTION"):
                fid = item.get("feedbackId")
                if fid is None or str(fid) in seen:
                    continue
                seen.add(str(fid))
                items.append(item)
            # Old unanswered feedback can disappear from NEED_REACTION as soon
            # as a seller replies, so it needs a targeted ALL recheck.
            items.extend(_iter_stale_pending_feedbacks(db, client, business_id, start, now, seen))

        offer_ids = {str((i.get("identifiers") or {}).get("offerId")) for i in items if (i.get("identifiers") or {}).get("offerId")}
        products = db.query(MasterProduct).filter(MasterProduct.seller_article.in_(offer_ids)).all() if offer_ids else []
        product_names = {str(p.seller_article): p.name for p in products if p.name}

        new_count = updated_count = 0
        review_rows = []
        for item in items:
            payload = _normalize_review(item, business_id, product_names)
            row, is_new, changed = _upsert_review(db, payload)
            new_count += int(is_new)
            updated_count += int((not is_new) and changed)
            review_rows.append(row)

        # Сохраняем отзывы до синхронизации комментариев, но не завершаем
        # транзакцию: после commit() SQLAlchemy может получить другое
        # соединение из пула, на котором app.organization_id ещё не установлен.
        # Это приводило к RLS-ошибке при ленивой загрузке review_rows.
        db.flush()

        new_comments, updated_comments, seller_answered, comment_errors = _sync_comments(
            db, client, business_id, review_rows, previously_unanswered
        )
        db.commit()

        total, answered, unanswered = _counts(db, business_id)
        last_sync = db.query(func.max(YandexReview.last_synced_at)).filter(
            YandexReview.business_id == business_id
        ).scalar()

        result = {
            "status": "ok",
            "business_id": business_id,
            "mode": mode,
            "windows_scanned": windows,
            "synced_from_api": len(items),
            "new_reviews": new_count,
            "updated_reviews": updated_count,
            "new_comments": new_comments,
            "updated_comments": updated_comments,
            "seller_answered_in_synced_reviews": seller_answered,
            "comment_sync_errors": comment_errors,
            "total_reviews": total,
            "answered": answered,
            "unanswered": unanswered,
            "last_sync": last_sync.isoformat() if last_sync else None,
        }
        logger.info(
            "YANDEX_REVIEWS_SYNC_OK | mode=%s new=%s updated=%s comments_new=%s total=%s unanswered=%s errors=%s",
            mode, new_count, updated_count, new_comments, total, unanswered, len(comment_errors),
        )
        return result
