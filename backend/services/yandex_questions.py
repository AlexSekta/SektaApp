import base64
import json
from datetime import datetime

from fastapi import APIRouter, Depends, Query
from sqlalchemy import func
from sqlalchemy.orm import Session

from backend.dependencies import get_db
from backend.models.yandex_question import (
    YandexQuestion,
    YandexQuestionAnswer,
    YandexQuestionAnswerComment,
)
from backend.marketplaces.yandex.client import YandexAPIError, YandexClient
from backend.services.marketplace_clients import get_yandex_client, get_yandex_business_id
from backend.services.yandex_question_sync import (
    ensure_yandex_question_tables,
    sync_yandex_questions,
)

router = APIRouter(prefix="/yandex")


def _resolve_business_id(client: YandexClient, business_id: int | None, db: Session) -> int:
    if business_id is not None:
        return int(business_id)
    return get_yandex_business_id(db, client)


def _encode_page(offset: int) -> str:
    raw = json.dumps({"offset": int(offset)}, separators=(",", ":")).encode()
    return base64.urlsafe_b64encode(raw).decode().rstrip("=")


def _decode_page(token: str | None) -> int:
    if not token:
        return 0
    try:
        padding = "=" * (-len(token) % 4)
        raw = base64.urlsafe_b64decode((token + padding).encode())
        value = json.loads(raw.decode()).get("offset", 0)
        return max(0, int(value))
    except Exception:
        return 0


def _format_datetime(value):
    if not value:
        return None
    if isinstance(value, datetime):
        return value.isoformat()
    return str(value)


def _load_answers(db: Session, business_id: int, question_ids: list[int]) -> dict[int, list[dict]]:
    if not question_ids:
        return {}

    rows = (
        db.query(YandexQuestionAnswer)
        .filter(
            YandexQuestionAnswer.business_id == business_id,
            YandexQuestionAnswer.question_id.in_(question_ids),
        )
        .order_by(YandexQuestionAnswer.created_at.asc(), YandexQuestionAnswer.id.asc())
        .all()
    )

    comments = (
        db.query(YandexQuestionAnswerComment)
        .filter(
            YandexQuestionAnswerComment.business_id == business_id,
            YandexQuestionAnswerComment.question_id.in_(question_ids),
        )
        .order_by(YandexQuestionAnswerComment.id.asc())
        .all()
    )

    comments_by_answer: dict[int, list[dict]] = {}
    for comment in comments:
        comments_by_answer.setdefault(comment.answer_id or 0, []).append(
            {
                "id": comment.comment_id,
                "text": comment.text,
                "author": comment.author or "",
                "author_type": comment.author_type,
                "status": comment.status,
                "can_modify": bool(comment.can_modify),
                "parent_id": comment.parent_id,
            }
        )

    result: dict[int, list[dict]] = {}
    for answer in rows:
        result.setdefault(answer.question_id, []).append(
            {
                "id": answer.answer_id,
                "text": answer.text,
                "author": answer.author or "",
                "author_type": answer.author_type,
                "status": answer.status,
                "created_at": _format_datetime(answer.created_at),
                "can_modify": bool(answer.can_modify),
                "comments": comments_by_answer.get(answer.answer_id, []),
            }
        )

    return result


@router.get(
    "/questions",
    tags=["Яндекс — Вопросы"],
    summary="Получить вопросы Яндекс Маркета",
    description=(
        "Синхронизирует текущие вопросы Яндекс Маркета с локальной БД "
        "и возвращает их из БД. Ответ продавца определяется по author.type=BUSINESS."
    ),
)
def yandex_questions(
    status: str = Query(
        "all",
        pattern="^(all|unanswered)$",
        description="all — все сохранённые вопросы; unanswered — вопросы, которые сам Яндекс помечает как ожидающие ответа продавца",
    ),
    limit: int = Query(50, ge=1, le=50),
    page_token: str | None = Query(None),
    business_id: int | None = Query(None, ge=1),
    db: Session = Depends(get_db),
):
    try:
        ensure_yandex_question_tables()

        client = get_yandex_client(db)
        resolved_business_id = _resolve_business_id(client, business_id, db)

        sync_yandex_questions(db, resolved_business_id, force_full=False)

        query = db.query(YandexQuestion).filter(
            YandexQuestion.business_id == resolved_business_id
        )
        if status == "unanswered":
            # Важно: needAnswer — это официальный признак Яндекса, что вопрос
            # сейчас ожидает ответа продавца. Отсутствие seller_has_answer
            # не равно "Без ответа": на вопрос мог ответить другой участник
            # (USER/VENDOR/BRAND), либо ответ продавца мог быть удалён/недоступен.
            query = query.filter(
                YandexQuestion.yandex_need_answer.is_(True),
            )

        total_count = query.count()
        offset = _decode_page(page_token)
        questions = (
            query.order_by(
                YandexQuestion.created_at.desc(),
                YandexQuestion.question_id.desc(),
            )
            .offset(offset)
            .limit(limit)
            .all()
        )

        question_ids = [int(question.question_id) for question in questions]
        answers_by_question = _load_answers(db, resolved_business_id, question_ids)

        items = []
        for question in questions:
            answers = answers_by_question.get(int(question.question_id), [])
            seller_answers = [
                answer for answer in answers
                if answer.get("author_type") == "BUSINESS"
                or bool(answer.get("can_modify"))
            ]
            items.append(
                {
                    "id": str(question.question_id),
                    "created_at": _format_datetime(question.created_at),
                    "author": question.author or "Покупатель",
                    "author_type": question.author_type,
                    "offer_id": question.offer_id,
                    "product_name": question.product_name,
                    "category_id": question.category_id,
                    "text": question.text,
                    "likes": question.likes,
                    "dislikes": question.dislikes,
                    "need_answer": bool(question.yandex_need_answer),
                    "yandex_need_answer": bool(question.yandex_need_answer),
                    "seller_has_answer": bool(question.seller_has_answer),
                    "answers": answers,
                    "seller_answers": seller_answers,
                    "answers_count": question.answers_count,
                    "seller_answers_count": question.seller_answers_count,
                    "other_answers_count": question.other_answers_count,
                }
            )

        next_offset = offset + len(questions)
        next_page_token = _encode_page(next_offset) if next_offset < total_count else None

        return {
            "status": "ok",
            "business_id": resolved_business_id,
            "filter": status,
            "questions": items,
            "total_count": total_count,
            "next_page_token": next_page_token,
        }

    except YandexAPIError as error:
        db.rollback()
        return {
            "status": "error",
            "code": error.status_code,
            "message": error.message,
            "details": error.response_data,
        }
    except Exception as error:
        db.rollback()
        return {
            "status": "error",
            "code": 500,
            "message": "Внутренняя ошибка при синхронизации вопросов Яндекс Маркета.",
            "details": str(error),
        }


@router.get(
    "/questions/count",
    tags=["Яндекс — Вопросы"],
    summary="Получить количество вопросов без ответа продавца",
)
def yandex_questions_count(
    business_id: int | None = Query(None, ge=1),
    db: Session = Depends(get_db),
):
    try:
        ensure_yandex_question_tables()
        client = get_yandex_client(db)
        resolved_business_id = _resolve_business_id(client, business_id, db)
        sync_yandex_questions(db, resolved_business_id, force_full=False)

        count = (
            db.query(func.count(YandexQuestion.id))
            .filter(
                YandexQuestion.business_id == resolved_business_id,
                YandexQuestion.yandex_need_answer.is_(True),
            )
            .scalar()
            or 0
        )

        return {
            "status": "ok",
            "business_id": resolved_business_id,
            "count_unanswered": int(count),
            "count_seller_has_answer": int(
                db.query(func.count(YandexQuestion.id))
                .filter(
                    YandexQuestion.business_id == resolved_business_id,
                    YandexQuestion.seller_has_answer.is_(True),
                )
                .scalar()
                or 0
            ),
        }

    except YandexAPIError as error:
        db.rollback()
        return {
            "status": "error",
            "code": error.status_code,
            "message": error.message,
            "details": error.response_data,
        }
    except Exception as error:
        db.rollback()
        return {
            "status": "error",
            "code": 500,
            "message": "Внутренняя ошибка при синхронизации счётчика вопросов Яндекс Маркета.",
            "details": str(error),
        }


@router.post(
    "/questions/sync",
    tags=["Яндекс — Вопросы"],
    summary="Синхронизировать вопросы Яндекс Маркета с БД",
)
def yandex_questions_sync(
    force_full: bool = Query(False, description="Полностью пересобрать актуальную историю вопросов."),
    business_id: int | None = Query(None, ge=1),
    db: Session = Depends(get_db),
):
    try:
        ensure_yandex_question_tables()
        client = get_yandex_client(db)
        resolved_business_id = _resolve_business_id(client, business_id, db)
        result = sync_yandex_questions(db, resolved_business_id, force_full=force_full)
        return {"status": "ok", **result}

    except YandexAPIError as error:
        db.rollback()
        return {
            "status": "error",
            "code": error.status_code,
            "message": error.message,
            "details": error.response_data,
        }
    except Exception as error:
        db.rollback()
        return {
            "status": "error",
            "code": 500,
            "message": "Внутренняя ошибка при синхронизации вопросов Яндекс Маркета.",
            "details": str(error),
        }
