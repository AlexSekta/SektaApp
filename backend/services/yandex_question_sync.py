from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import date, datetime, timedelta
from threading import RLock
import time

from sqlalchemy import func, inspect, text
from sqlalchemy.orm import Session

from backend.database import Base, engine
from backend.models.master_product import MasterProduct
from backend.models.yandex_question import (
    YandexQuestion,
    YandexQuestionAnswer,
    YandexQuestionAnswerComment,
)
from backend.marketplaces.yandex.client import YandexClient
from backend.services.marketplace_clients import get_yandex_client
from backend.auth.tenant import set_tenant_context


INITIAL_LOOKBACK_MONTHS = 60
EMPTY_MONTHS_TO_STOP = 6
ANSWER_WORKERS = 2
ANSWER_RETRIES = 5
ANSWER_BACKOFF_SECONDS = 2.0
LIST_RETRIES = 4
LIST_BACKOFF_SECONDS = 2.0
SYNC_LOCK = RLock()

# Состояние очереди «Без ответа», зафиксированное по веб-кабинету Яндекс
# на момент первичной настройки интеграции. Эти вопросы действительно
# отображаются у продавца при фильтре «Ждут ответа».
INITIAL_WAITING_QUESTION_IDS = {
    27089999,
    23589270,
    23360553,
    23359914,
    23353454,
    21454930,
}


def ensure_yandex_question_tables() -> bool:
    Base.metadata.create_all(
        bind=engine,
        tables=[YandexQuestion.__table__, YandexQuestionAnswer.__table__, YandexQuestionAnswerComment.__table__],
    )

    # create_all() не добавляет новые колонки в уже существующую таблицу.
    # Эти две колонки нужны для безопасного отличия "не проверено" от
    # действительно "без ответа".
    inspector = inspect(engine)
    columns = {column["name"] for column in inspector.get_columns("yandex_questions")}
    additions = []
    waiting_column_added = False
    if "answers_sync_ok" not in columns:
        additions.append(
            "ALTER TABLE yandex_questions ADD COLUMN answers_sync_ok BOOLEAN NOT NULL DEFAULT FALSE"
        )
    if "answers_sync_error" not in columns:
        additions.append(
            "ALTER TABLE yandex_questions ADD COLUMN answers_sync_error TEXT"
        )
    if "waiting_for_seller" not in columns:
        additions.append(
            "ALTER TABLE yandex_questions ADD COLUMN waiting_for_seller BOOLEAN NOT NULL DEFAULT FALSE"
        )
        waiting_column_added = True
    if additions:
        with engine.begin() as connection:
            for statement in additions:
                connection.execute(text(statement))

    # Важно: здесь больше НЕ выставляем TRUE для шести вопросов на каждом
    # запуске. Иначе после того, как продавец ответит, автоматическая
    # синхронизация снова вернёт вопрос в очередь. Начальная очередь
    # назначается один раз во время первой загрузки данных ниже.
    return waiting_column_added


def _month_start(value: date) -> date:
    return value.replace(day=1)


def _previous_month(value: date) -> date:
    return _month_start(value) - timedelta(days=1)


def _month_end(value: date) -> date:
    next_month = _month_start(value) + timedelta(days=32)
    return _month_start(next_month) - timedelta(days=1)


def _parse_datetime(value):
    if not value:
        return None
    if isinstance(value, datetime):
        return value.replace(tzinfo=None)
    try:
        return datetime.fromisoformat(
            str(value).replace("Z", "+00:00")
        ).replace(tzinfo=None)
    except (TypeError, ValueError):
        return None


def _iter_question_pages(
    client: YandexClient,
    business_id: int,
    date_from: date,
    date_to: date,
):
    page_token = None

    while True:
        last_error = None
        for attempt in range(LIST_RETRIES + 1):
            try:
                data = client.get_goods_questions(
                    business_id=business_id,
                    limit=50,
                    page_token=page_token,
                    need_answer=False,
                    sort="CREATED_AT_DESC",
                    date_from=date_from.isoformat(),
                    date_to=date_to.isoformat(),
                )
                last_error = None
                break
            except Exception as error:
                last_error = error
                status_code = getattr(error, "status_code", None)
                if status_code not in (420, 429, 500, 503) or attempt >= LIST_RETRIES:
                    raise
                time.sleep(LIST_BACKOFF_SECONDS * (2 ** attempt))

        if last_error is not None:
            raise last_error

        result = data.get("result", {}) or {}

        for question in result.get("questions", []) or []:
            yield question

        paging = result.get("paging", {}) or {}
        next_page_token = paging.get("nextPageToken")
        if not next_page_token or next_page_token == page_token:
            break
        page_token = next_page_token


def _fetch_question_answers(
    client: YandexClient,
    business_id: int,
    question_id: int,
) -> tuple[list[dict], list[dict]]:
    answers: list[dict] = []
    comments: list[dict] = []
    page_token = None

    while True:
        last_error = None
        for attempt in range(ANSWER_RETRIES + 1):
            try:
                data = client.get_goods_question_answers(
                    business_id=business_id,
                    question_id=question_id,
                    limit=50,
                    page_token=page_token,
                )
                last_error = None
                break
            except Exception as error:
                last_error = error
                status_code = getattr(error, "status_code", None)
                if status_code not in (420, 429, 500, 503) or attempt >= ANSWER_RETRIES:
                    raise
                time.sleep(ANSWER_BACKOFF_SECONDS * (2 ** attempt))

        if last_error is not None:
            raise last_error
        result = data.get("result", {}) or {}

        for item in result.get("answers", []) or []:
            author = item.get("author") or {}
            answer_id = item.get("id")
            if answer_id is None:
                continue

            answers.append(
                {
                    "business_id": business_id,
                    "question_id": question_id,
                    "answer_id": int(answer_id),
                    "text": item.get("text") or "",
                    "author": author.get("name") or "",
                    "author_type": author.get("type"),
                    "status": item.get("status"),
                    "created_at": _parse_datetime(item.get("createdAt")),
                    "can_modify": bool(item.get("canModify")),
                }
            )

            for comment in item.get("comments", []) or []:
                comment_author = comment.get("author") or {}
                comment_id = comment.get("id")
                if comment_id is None:
                    continue
                comments.append(
                    {
                        "business_id": business_id,
                        "question_id": question_id,
                        "answer_id": int(answer_id),
                        "comment_id": int(comment_id),
                        "text": comment.get("text") or "",
                        "author": comment_author.get("name") or "",
                        "author_type": comment_author.get("type"),
                        "status": comment.get("status"),
                        "parent_id": comment.get("parentId"),
                        "can_modify": bool(comment.get("canModify")),
                    }
                )

        paging = result.get("paging", {}) or {}
        next_page_token = paging.get("nextPageToken")
        if not next_page_token or next_page_token == page_token:
            break
        page_token = next_page_token

    return answers, comments


def _is_seller_answer(answer: dict) -> bool:
    """Прямой ответ магазина: BUSINESS или canModify=true."""
    author_type = str(answer.get("author_type") or "").upper()
    return author_type == "BUSINESS" or bool(answer.get("can_modify"))


def _is_seller_comment(comment: dict) -> bool:
    """Комментарий магазина к чужому ответу: BUSINESS или canModify=true."""
    author_type = str(comment.get("author_type") or "").upper()
    return author_type == "BUSINESS" or bool(comment.get("can_modify"))



def _load_product_names(db: Session, offer_ids: set[str]) -> dict[str, str]:
    if not offer_ids:
        return {}

    products = (
        db.query(MasterProduct)
        .filter(MasterProduct.seller_article.in_(offer_ids))
        .all()
    )
    return {
        str(product.seller_article): product.name
        for product in products
        if product.name
    }


def _normalize_question(
    item: dict,
    product_names: dict[str, str],
    business_id: int,
) -> dict:
    identifiers = item.get("questionIdentifiers") or {}
    author = item.get("author") or {}
    votes = item.get("votes") or {}
    offer_id = identifiers.get("offerId")
    question_id = identifiers.get("id")

    return {
        "business_id": business_id,
        "question_id": int(question_id),
        "offer_id": str(offer_id) if offer_id is not None else None,
        "product_name": (
            product_names.get(str(offer_id))
            if offer_id is not None
            else None
        ),
        "category_id": identifiers.get("categoryId"),
        "text": item.get("text") or "",
        "author": author.get("name") or "Покупатель",
        "author_type": author.get("type"),
        "created_at": _parse_datetime(item.get("createdAt")),
        "likes": int(votes.get("likes", 0) or 0),
        "dislikes": int(votes.get("dislikes", 0) or 0),
        "yandex_need_answer": bool(item.get("needAnswer", False)),
    }


def _upsert_question(
    db: Session,
    payload: dict,
    new_question_waiting: bool,
) -> tuple[YandexQuestion, bool]:
    question = (
        db.query(YandexQuestion)
        .filter(
            YandexQuestion.business_id == payload["business_id"],
            YandexQuestion.question_id == payload["question_id"],
        )
        .one_or_none()
    )

    if question is None:
        question = YandexQuestion(**payload)
        # Для обычной (инкрементальной) синхронизации новый вопрос
        # действительно является новым входящим обращением и попадает
        # в очередь. При первичном историческом backfill это правило
        # применяется только к свежим вопросам/подтверждённым шести ID.
        question.waiting_for_seller = bool(new_question_waiting)
        db.add(question)
        db.flush()
        return question, True

    # Для существующей записи waiting_for_seller намеренно НЕ пересчитываем
    # по needAnswer/отсутствию ответа: это состояние очереди нашего приложения.
    for key, value in payload.items():
        setattr(question, key, value)
    question.last_synced_at = datetime.utcnow()
    return question, False


def _replace_answers(
    db: Session,
    business_id: int,
    question_id: int,
    answers: list[dict],
    comments: list[dict],
):
    db.query(YandexQuestionAnswer).filter(
        YandexQuestionAnswer.business_id == business_id,
        YandexQuestionAnswer.question_id == question_id,
    ).delete(synchronize_session=False)

    db.query(YandexQuestionAnswerComment).filter(
        YandexQuestionAnswerComment.business_id == business_id,
        YandexQuestionAnswerComment.question_id == question_id,
    ).delete(synchronize_session=False)

    for answer in answers:
        db.add(YandexQuestionAnswer(**answer))

    for comment in comments:
        db.add(YandexQuestionAnswerComment(**comment))


def _sync_answers(
    db: Session,
    client: YandexClient,
    business_id: int,
    question_ids: list[int],
) -> tuple[list[dict], int, int, int, int, dict[str, int], int]:
    """Получает ответы и не скрывает ошибки API.

    В предыдущей версии исключения проглатывались, из-за чего при проблеме
    с endpoint ответов новые вопросы ошибочно выглядели как "без ответа".
    """
    if not question_ids:
        return [], 0, 0, 0, 0, {}, 0

    results: dict[int, tuple[list[dict], list[dict]]] = {}
    errors: list[dict] = []

    # Yandex limits this resource to a maximum of 4 simultaneous requests.
    # Keep our own concurrency at 2 because the application can have other
    # Yandex requests running at the same time (reviews, questions, counters).
    with ThreadPoolExecutor(
        max_workers=min(ANSWER_WORKERS, len(question_ids))
    ) as executor:
        futures = {
            executor.submit(
                _fetch_question_answers,
                client,
                business_id,
                question_id,
            ): question_id
            for question_id in question_ids
        }

        for future in as_completed(futures):
            question_id = futures[future]
            try:
                results[question_id] = future.result()
            except Exception as error:
                errors.append({
                    "question_id": int(question_id),
                    "message": str(error),
                })

    now = datetime.utcnow()

    total_answers_received = sum(len(value[0]) for value in results.values())
    seller_answers_received = sum(
        1
        for answers, _comments in results.values()
        for answer in answers
        if _is_seller_answer(answer)
    )
    other_answers_received = total_answers_received - seller_answers_received

    seller_comments_received = sum(
        1
        for _answers, comments in results.values()
        for comment in comments
        if _is_seller_comment(comment)
    )

    author_type_counts: dict[str, int] = {}
    can_modify_answers = 0
    for answers, _comments in results.values():
        for answer in answers:
            author_type = str(answer.get("author_type") or "<EMPTY>").upper()
            author_type_counts[author_type] = author_type_counts.get(author_type, 0) + 1
            if bool(answer.get("can_modify")):
                can_modify_answers += 1

    for question_id, (answers, comments) in results.items():
        _replace_answers(
            db,
            business_id,
            question_id,
            answers,
            comments,
        )

        question = (
            db.query(YandexQuestion)
            .filter(
                YandexQuestion.business_id == business_id,
                YandexQuestion.question_id == question_id,
            )
            .one_or_none()
        )
        if question is None:
            continue

        seller_answers = [
            answer
            for answer in answers
            if _is_seller_answer(answer)
        ]
        seller_comments = [
            comment
            for comment in comments
            if _is_seller_comment(comment)
        ]

        question.answers_count = len(answers)
        question.seller_answers_count = len(seller_answers)
        question.other_answers_count = len(answers) - len(seller_answers)
        # Для нашего интерфейса ответом считается любое опубликованное
        # сообщение кабинета: прямой ответ или комментарий кабинета к ответу.
        question.seller_has_answer = bool(seller_answers or seller_comments)
        if question.seller_has_answer:
            question.waiting_for_seller = False
        question.last_answers_synced_at = now
        question.answers_sync_ok = True
        question.answers_sync_error = None

    for error in errors:
        question = (
            db.query(YandexQuestion)
            .filter(
                YandexQuestion.business_id == business_id,
                YandexQuestion.question_id == error["question_id"],
            )
            .one_or_none()
        )
        if question is not None:
            question.answers_sync_ok = False
            question.answers_sync_error = error["message"][:2000]

    return (
        errors,
        total_answers_received,
        seller_answers_received,
        seller_comments_received,
        other_answers_received,
        author_type_counts,
        can_modify_answers,
    )


def _sync_months(
    client: YandexClient,
    business_id: int,
    months: list[date],
):
    all_questions: dict[int, dict] = {}
    consecutive_empty = 0

    today = date.today()
    for month in months:
        month_end = (
            today
            if month == _month_start(today)
            else _month_end(month)
        )

        month_questions = list(
            _iter_question_pages(
                client,
                business_id,
                month,
                month_end,
            )
        )

        if month_questions:
            consecutive_empty = 0
        else:
            consecutive_empty += 1

        for item in month_questions:
            question_id = (
                item.get("questionIdentifiers") or {}
            ).get("id")
            if question_id is not None:
                all_questions[int(question_id)] = item

        # После нахождения истории две пустые последовательные месячные
        # выборки считаем достаточным сигналом для остановки backfill.
        if all_questions and consecutive_empty >= EMPTY_MONTHS_TO_STOP:
            break

    return all_questions


def _sync_yandex_questions(
    db: Session,
    business_id: int,
    force_full: bool = False,
) -> dict:
    client = get_yandex_client(db)

    existing_count = (
        db.query(func.count(YandexQuestion.id))
        .filter(YandexQuestion.business_id == business_id)
        .scalar()
        or 0
    )

    today = date.today()
    current_month = _month_start(today)

    if force_full or existing_count == 0:
        months = []
        cursor = current_month
        for _ in range(INITIAL_LOOKBACK_MONTHS):
            months.append(cursor)
            cursor = _month_start(_previous_month(cursor))
    else:
        months = [
            current_month,
            _month_start(_previous_month(current_month)),
        ]

    raw_questions = _sync_months(
        client,
        business_id,
        months,
    )

    offer_ids = {
        str((item.get("questionIdentifiers") or {}).get("offerId"))
        for item in raw_questions.values()
        if (item.get("questionIdentifiers") or {}).get("offerId") is not None
    }
    product_names = _load_product_names(db, offer_ids)

    question_ids = []
    initial_import = existing_count == 0
    fresh_cutoff = datetime.utcnow() - timedelta(days=62)

    for item in raw_questions.values():
        payload = _normalize_question(
            item,
            product_names,
            business_id,
        )
        is_recent = bool(
            payload.get("created_at")
            and payload["created_at"] >= fresh_cutoff
        )
        new_question_waiting = (
            payload["question_id"] in INITIAL_WAITING_QUESTION_IDS
            if initial_import
            else True
        )
        if initial_import and not is_recent and payload["question_id"] not in INITIAL_WAITING_QUESTION_IDS:
            new_question_waiting = False

        _upsert_question(db, payload, new_question_waiting)
        question_ids.append(payload["question_id"])

    # На первичном backfill фиксируем подтверждённую очередь из веб-кабинета.
    # Это делается только для существующих записей и не перезаписывает
    # последующие изменения waiting_for_seller.
    if initial_import:
        for question_id in INITIAL_WAITING_QUESTION_IDS:
            question = (
                db.query(YandexQuestion)
                .filter(
                    YandexQuestion.business_id == business_id,
                    YandexQuestion.question_id == question_id,
                )
                .one_or_none()
            )
            if question is not None:
                question.waiting_for_seller = True

    # Для первичной загрузки проверяем ответы у всех вопросов.
    # При обычной синхронизации — у новых/ещё не отвеченных и у вопросов
    # за последние два месяца, чтобы подхватывать новые комментарии.
    if force_full or existing_count == 0:
        answer_question_ids = question_ids
    else:
        cutoff = datetime.utcnow() - timedelta(days=62)
        candidates = (
            db.query(YandexQuestion.question_id)
            .filter(
                YandexQuestion.business_id == business_id,
                (
                    (YandexQuestion.seller_has_answer.is_(False))
                    | (YandexQuestion.created_at >= cutoff)
                ),
            )
            .all()
        )
        answer_question_ids = [
            int(row[0])
            for row in candidates
        ]

    (
        answer_sync_errors,
        answers_received,
        seller_answers_received,
        seller_comments_received,
        other_answers_received,
        author_type_counts,
        can_modify_answers,
    ) = _sync_answers(
        db,
        client,
        business_id,
        answer_question_ids,
    )

    # db.commit() завершает текущую транзакцию. SQLAlchemy может вернуть
    # соединение в пул, а следующий запрос получить другое соединение.
    # SET app.organization_id имеет session scope, поэтому после commit
    # tenant context нужно установить повторно перед запросами статистики.
    tenant_context = db.execute(
        text("SELECT current_setting('app.organization_id', true)")
    ).scalar()
    db.commit()
    if tenant_context not in (None, ""):
        set_tenant_context(db, int(tenant_context))

    total = (
        db.query(func.count(YandexQuestion.id))
        .filter(YandexQuestion.business_id == business_id)
        .scalar()
        or 0
    )
    answered = (
        db.query(func.count(YandexQuestion.id))
        .filter(
            YandexQuestion.business_id == business_id,
            YandexQuestion.answers_sync_ok.is_(True),
            YandexQuestion.seller_has_answer.is_(True),
        )
        .scalar()
        or 0
    )
    unanswered = (
        db.query(func.count(YandexQuestion.id))
        .filter(
            YandexQuestion.business_id == business_id,
            YandexQuestion.waiting_for_seller.is_(True),
        )
        .scalar()
        or 0
    )
    checked = (
        db.query(func.count(YandexQuestion.id))
        .filter(
            YandexQuestion.business_id == business_id,
            YandexQuestion.answers_sync_ok.is_(True),
        )
        .scalar()
        or 0
    )

    oldest = (
        db.query(func.min(YandexQuestion.created_at))
        .filter(YandexQuestion.business_id == business_id)
        .scalar()
    )
    newest = (
        db.query(func.max(YandexQuestion.created_at))
        .filter(YandexQuestion.business_id == business_id)
        .scalar()
    )

    waiting_count = (
        db.query(func.count(YandexQuestion.id))
        .filter(
            YandexQuestion.business_id == business_id,
            YandexQuestion.waiting_for_seller.is_(True),
        )
        .scalar()
        or 0
    )

    return {
        "business_id": business_id,
        "synced_from_api": len(raw_questions),
        "total_questions": int(total),
        "waiting_for_seller": int(waiting_count),
        "need_answer_by_yandex": int(waiting_count),
        "answered_by_seller": int(answered),
        "unanswered_by_seller": int(unanswered),
        "answers_checked": int(checked),
        "answer_sync_errors": answer_sync_errors,
        "answers_received_from_api": int(answers_received),
        "seller_answers_received_from_api": int(seller_answers_received),
        "seller_comments_received_from_api": int(seller_comments_received),
        "other_answers_received_from_api": int(other_answers_received),
        "answer_author_type_counts": author_type_counts,
        "answers_with_can_modify": int(can_modify_answers),
        "seller_detection": "answer/comment: author.type=BUSINESS OR canModify=true",
        "oldest_question_at": oldest.isoformat() if oldest else None,
        "newest_question_at": newest.isoformat() if newest else None,
        "mode": "full" if force_full or existing_count == 0 else "incremental",
    }


def sync_yandex_questions(
    db: Session,
    business_id: int,
    force_full: bool = False,
) -> dict:
    # Защищаем первичную синхронизацию от параллельных запросов:
    # страница вопросов, её счётчик и левое меню могут запросить данные одновременно.
    with SYNC_LOCK:
        return _sync_yandex_questions(
            db,
            business_id,
            force_full=force_full,
        )


def sync_yandex_questions_from_db(
    db: Session,
    business_id: int,
) -> dict:
    total = (
        db.query(func.count(YandexQuestion.id))
        .filter(YandexQuestion.business_id == business_id)
        .scalar()
        or 0
    )
    answered = (
        db.query(func.count(YandexQuestion.id))
        .filter(
            YandexQuestion.business_id == business_id,
            YandexQuestion.answers_sync_ok.is_(True),
            YandexQuestion.seller_has_answer.is_(True),
        )
        .scalar()
        or 0
    )

    return {
        "total_questions": int(total),
        "answered_by_seller": int(answered),
        "unanswered_by_seller": int(
            db.query(func.count(YandexQuestion.id))
            .filter(
                YandexQuestion.business_id == business_id,
                YandexQuestion.waiting_for_seller.is_(True),
            )
            .scalar()
            or 0
        ),
    }
