import time
from datetime import datetime
from threading import RLock

from sqlalchemy import and_, cast, func, not_, or_, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Session

from backend.database import Base, engine
from backend.logging_config import get_logger
from backend.marketplaces.wb.client import WBClient
from backend.services.marketplace_clients import get_wb_client
from backend.auth.tenant import set_tenant_context
from backend.models.wb_review import WBReview

logger = get_logger("wb_reviews_sync")
SYNC_LOCK = RLock()
INCREMENTAL_TAKE = 5000
FULL_TAKE = 5000
MAX_RETRIES = 4
RETRY_BACKOFF = 2.0
UNANSWERED_FROM = datetime(2026, 1, 1)


def ensure_wb_review_tables() -> None:
    Base.metadata.create_all(bind=engine, tables=[WBReview.__table__])

    # Existing installations may have been created with BIGINT feedback_id/answer_id.
    # WB feedback IDs can be alphanumeric, so migrate those columns to VARCHAR
    # without deleting the existing table/data.
    with engine.begin() as conn:
        columns = conn.exec_driver_sql(
            """
            SELECT column_name, data_type
            FROM information_schema.columns
            WHERE table_schema = current_schema()
              AND table_name = 'wb_reviews'
              AND column_name IN ('feedback_id', 'answer_id')
            """
        ).fetchall()

        types = {row[0]: row[1] for row in columns}

        if types.get("feedback_id") != "character varying":
            conn.exec_driver_sql(
                """
                ALTER TABLE wb_reviews
                ALTER COLUMN feedback_id TYPE VARCHAR(128)
                USING feedback_id::text
                """
            )

        if types.get("answer_id") and types.get("answer_id") != "character varying":
            conn.exec_driver_sql(
                """
                ALTER TABLE wb_reviews
                ALTER COLUMN answer_id TYPE VARCHAR(128)
                USING answer_id::text
                """
            )


def _fetch_page(client: WBClient, is_answered: bool, skip: int, take: int):
    last_error = None
    for attempt in range(MAX_RETRIES + 1):
        try:
            return client.get_feedbacks(is_answered=is_answered, take=take, skip=skip, order="dateDesc")
        except Exception as error:
            last_error = error
            status_code = getattr(error, "status_code", None)
            if status_code not in (429, 500, 502, 503, 504) or attempt >= MAX_RETRIES:
                raise
            time.sleep(RETRY_BACKOFF * (2 ** attempt))
    raise last_error


def _iter_all_feedbacks(client: WBClient, is_answered: bool):
    skip = 0
    while True:
        response = _fetch_page(client, is_answered, skip, FULL_TAKE)
        items = (response.get("data") or {}).get("feedbacks") or []
        yield from items
        if len(items) < FULL_TAKE:
            break
        skip += len(items)


def _iter_incremental_feedbacks(client: WBClient, is_answered: bool):
    response = _fetch_page(client, is_answered, 0, INCREMENTAL_TAKE)
    yield from ((response.get("data") or {}).get("feedbacks") or [])


def _parse_datetime(value):
    if not value:
        return None
    if isinstance(value, datetime):
        return value.replace(tzinfo=None)
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00")).replace(tzinfo=None)
    except (TypeError, ValueError):
        return None


def _normalize(item: dict) -> dict:
    product = item.get("productDetails") or {}
    answer = item.get("answer")
    answer_id = (answer.get("id") or answer.get("answerId")) if answer else None
    return {
        "feedback_id": str(item["id"]),
        "text": item.get("text") or "",
        "pros": item.get("pros") or "",
        "cons": item.get("cons") or "",
        "rating": item.get("productValuation"),
        "created_at": _parse_datetime(item.get("createdDate")),
        "updated_at": _parse_datetime(item.get("updatedDate")),
        "buyer_name": item.get("userName") or "",
        "article": product.get("supplierArticle"),
        "nm_id": product.get("nmId"),
        "product_name": product.get("productName"),
        "brand_name": product.get("brandName"),
        "subject_name": product.get("subjectName"),
        "color": item.get("color"),
        "photo_links": item.get("photoLinks") or [],
        "bables": item.get("bables") or [],
        "was_viewed": bool(item.get("wasViewed")),
        "state": item.get("state"),
        "seller_has_answer": answer is not None,
        "answer_id": str(answer_id) if answer_id is not None else None,
        "answer_text": (answer.get("text") or "") if answer else None,
        "answer_state": answer.get("state") if answer else None,
        "answer_editable": bool(answer.get("editable")) if answer else False,
        "answer_created_at": _parse_datetime((answer.get("createDate") or answer.get("createdDate")) if answer else None),
        "raw_data": item,
    }


def _upsert(db: Session, payload: dict) -> bool:
    row = db.query(WBReview).filter(WBReview.feedback_id == payload["feedback_id"]).one_or_none()
    is_new = row is None
    if row is None:
        row = WBReview(**payload)
        db.add(row)
    else:
        for key, value in payload.items():
            setattr(row, key, value)
    row.last_synced_at = datetime.utcnow()
    return is_new


def _sync_items(db: Session, items):
    new_count = updated_count = 0
    for item in items:
        if not item.get("id"):
            continue
        if _upsert(db, _normalize(item)):
            new_count += 1
        else:
            updated_count += 1
    return new_count, updated_count


def _has_review_content():
    photo_json = cast(WBReview.photo_links, JSONB)
    return or_(
        func.length(func.btrim(func.coalesce(WBReview.text, ""))) > 0,
        func.length(func.btrim(func.coalesce(WBReview.pros, ""))) > 0,
        func.length(func.btrim(func.coalesce(WBReview.cons, ""))) > 0,
        func.jsonb_array_length(photo_json) > 0,
    )


def _db_counts(db: Session):
    total = int(db.query(func.count(WBReview.id)).scalar() or 0)
    answered = int(
        db.query(func.count(WBReview.id))
        .filter(WBReview.seller_has_answer.is_(True))
        .scalar()
        or 0
    )
    unanswered = int(
        db.query(func.count(WBReview.id))
        .filter(
            WBReview.seller_has_answer.is_(False),
            _has_review_content(),
            WBReview.created_at >= UNANSWERED_FROM,
        )
        .scalar()
        or 0
    )
    rating_only = int(
        db.query(func.count(WBReview.id))
        .filter(
            WBReview.seller_has_answer.is_(False),
            WBReview.rating.is_not(None),
            not_(_has_review_content()),
        )
        .scalar()
        or 0
    )
    return total, answered, unanswered, rating_only


def sync_wb_reviews(db: Session, force_full: bool = False) -> dict:
    ensure_wb_review_tables()
    with SYNC_LOCK:
        client = get_wb_client(db)
        existing_count = int(db.query(func.count(WBReview.id)).scalar() or 0)
        started_at = datetime.utcnow()
        seen: set[str] = set()
        items = []
        iterator = _iter_all_feedbacks if (force_full or existing_count == 0) else _iter_incremental_feedbacks
        mode = "full" if (force_full or existing_count == 0) else "incremental"

        for is_answered in (False, True):
            for item in iterator(client, is_answered):
                feedback_id = item.get("id")
                if feedback_id is None:
                    continue
                feedback_id = str(feedback_id)
                if feedback_id in seen:
                    continue
                seen.add(feedback_id)
                items.append(item)

        new_count, updated_count = _sync_items(db, items)

        # SQLAlchemy may return the DB connection to the pool after commit().
        # The PostgreSQL tenant GUC is connection-local, so restore it before
        # running the post-sync aggregate queries. This prevents RLS from
        # evaluating current_setting('app.organization_id', true) as ''.
        tenant_value = db.execute(
            text("SELECT current_setting('app.organization_id', true)")
        ).scalar()
        tenant_id = None
        if tenant_value not in (None, ""):
            try:
                tenant_id = int(tenant_value)
            except (TypeError, ValueError):
                tenant_id = None

        db.commit()

        if tenant_id is not None:
            set_tenant_context(db, tenant_id)

        total, answered, unanswered, rating_only = _db_counts(db)
        last_sync = db.query(func.max(WBReview.last_synced_at)).scalar()
        result = {
            "status": "ok",
            "mode": mode,
            "synced_from_api": len(items),
            "new_reviews": new_count,
            "updated_reviews": updated_count,
            "total_reviews": total,
            "answered": answered,
            "unanswered": unanswered,
            "rating_only": rating_only,
            "started_at": started_at.isoformat(),
            "finished_at": datetime.utcnow().isoformat(),
            "last_sync": last_sync.isoformat() if last_sync else None,
        }
        logger.info("WB_REVIEWS_SYNC_OK | mode=%s new=%s updated=%s total=%s answered=%s unanswered=%s rating_only=%s", mode, new_count, updated_count, total, answered, unanswered, rating_only)
        return result
