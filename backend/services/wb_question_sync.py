import time
from datetime import datetime
from threading import RLock

from sqlalchemy import func
from sqlalchemy.orm import Session

from backend.database import Base, engine
from backend.logging_config import get_logger
from backend.marketplaces.wb.client import WBClient
from backend.services.marketplace_clients import get_wb_client
from backend.models.wb_question import WBQuestion

logger = get_logger("wb_questions_sync")
SYNC_LOCK = RLock()
INCREMENTAL_TAKE = 5000
FULL_TAKE = 5000
MAX_RETRIES = 4
RETRY_BACKOFF = 2.0


def ensure_wb_question_tables() -> None:
    Base.metadata.create_all(bind=engine, tables=[WBQuestion.__table__])


def _fetch_page(client: WBClient, is_answered: bool, skip: int, take: int):
    last_error = None
    for attempt in range(MAX_RETRIES + 1):
        try:
            return client.get_questions(
                is_answered=is_answered,
                take=take,
                skip=skip,
                order="dateDesc",
            )
        except Exception as error:
            last_error = error
            status_code = getattr(error, "status_code", None)
            if status_code not in (429, 500, 502, 503, 504) or attempt >= MAX_RETRIES:
                raise
            time.sleep(RETRY_BACKOFF * (2 ** attempt))
    raise last_error


def _iter_all_questions(client: WBClient, is_answered: bool):
    skip = 0
    while True:
        response = _fetch_page(client, is_answered, skip, FULL_TAKE)
        items = (response.get("data") or {}).get("questions") or []
        yield from items
        if len(items) < FULL_TAKE:
            break
        skip += len(items)


def _iter_incremental_questions(client: WBClient, is_answered: bool):
    response = _fetch_page(client, is_answered, 0, INCREMENTAL_TAKE)
    yield from ((response.get("data") or {}).get("questions") or [])


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
    question_id = item.get("id")
    return {
        "question_id": str(question_id),
        "text": item.get("text") or "",
        "created_at": _parse_datetime(item.get("createdDate")),
        "updated_at": _parse_datetime(item.get("updatedDate")),
        "article": product.get("supplierArticle"),
        "nm_id": product.get("nmId"),
        "product_name": product.get("productName"),
        "brand_name": product.get("brandName"),
        "was_viewed": bool(item.get("wasViewed")),
        "is_warned": bool(item.get("isWarned")),
        "state": item.get("state"),
        "seller_has_answer": answer is not None,
        "answer_id": str(answer_id) if answer_id is not None else None,
        "answer_text": (answer.get("text") or "") if answer else None,
        "answer_state": answer.get("state") if answer else None,
        "answer_editable": bool(answer.get("editable")) if answer else False,
        "answer_created_at": _parse_datetime(
            (answer.get("createDate") or answer.get("createdDate")) if answer else None
        ),
        "raw_data": item,
    }


def _upsert(db: Session, payload: dict) -> bool:
    row = (
        db.query(WBQuestion)
        .filter(WBQuestion.question_id == payload["question_id"])
        .one_or_none()
    )
    is_new = row is None
    if row is None:
        row = WBQuestion(**payload)
        db.add(row)
    else:
        for key, value in payload.items():
            setattr(row, key, value)
    row.last_synced_at = datetime.utcnow()
    return is_new


def _sync_items(db: Session, items):
    new_count = updated_count = 0
    for item in items:
        if item.get("id") is None:
            continue
        if _upsert(db, _normalize(item)):
            new_count += 1
        else:
            updated_count += 1
    return new_count, updated_count


def _db_counts(db: Session):
    total = int(db.query(func.count(WBQuestion.id)).scalar() or 0)
    unanswered = int(
        db.query(func.count(WBQuestion.id))
        .filter(WBQuestion.seller_has_answer.is_(False))
        .scalar()
        or 0
    )
    return total, total - unanswered, unanswered


def sync_wb_questions(db: Session, force_full: bool = False) -> dict:
    ensure_wb_question_tables()
    with SYNC_LOCK:
        client = get_wb_client(db)
        existing_count = int(db.query(func.count(WBQuestion.id)).scalar() or 0)
        started_at = datetime.utcnow()
        seen: set[str] = set()
        items = []
        iterator = _iter_all_questions if (force_full or existing_count == 0) else _iter_incremental_questions
        mode = "full" if (force_full or existing_count == 0) else "incremental"

        for is_answered in (False, True):
            for item in iterator(client, is_answered):
                question_id = item.get("id")
                if question_id is None:
                    continue
                question_id = str(question_id)
                if question_id in seen:
                    continue
                seen.add(question_id)
                items.append(item)

        new_count, updated_count = _sync_items(db, items)
        db.commit()
        total, answered, unanswered = _db_counts(db)
        last_sync = db.query(func.max(WBQuestion.last_synced_at)).scalar()
        result = {
            "status": "ok",
            "mode": mode,
            "synced_from_api": len(items),
            "new_questions": new_count,
            "updated_questions": updated_count,
            "total_questions": total,
            "answered": answered,
            "unanswered": unanswered,
            "started_at": started_at.isoformat(),
            "finished_at": datetime.utcnow().isoformat(),
            "last_sync": last_sync.isoformat() if last_sync else None,
        }
        logger.info(
            "WB_QUESTIONS_SYNC_OK | mode=%s new=%s updated=%s total=%s unanswered=%s",
            mode,
            new_count,
            updated_count,
            total,
            unanswered,
        )
        return result
