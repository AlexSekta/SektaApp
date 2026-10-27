from datetime import date, datetime, time, timedelta

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from backend.dependencies import get_db
from backend.services.auto_stock_service import calculate_auto_stock
from backend.services.out_of_stock_service import calculate_out_of_stock
from backend.services.marketplace_clients import get_ozon_client
from backend.models.auto_stock_history import AutoStockHistory
from backend.models.wb_review import WBReview
from backend.models.wb_review_response_tracking import WBReviewResponseTracking
from backend.models.ozon_sales_daily import OzonSalesDaily
from backend.models.yandex_sales_order import YandexSalesOrderLine, YandexSalesSyncDay
from sqlalchemy import func, case

router = APIRouter(
    prefix="/analytics",
    tags=["Аналитика"],
)


@router.post("/autostock/calculate")
def calculate(
    db: Session = Depends(get_db),
):

    return calculate_auto_stock(db)


@router.get("/autostock/history")
def history(
    db: Session = Depends(get_db),
):

    return [
        {
            "date": item.date,
            "marketplace": item.marketplace,
            "total_products": item.total_products,
            "zero_products": item.zero_products,
            "percent": item.autostock_percent,
        }
        for item in (
            db.query(AutoStockHistory).order_by(AutoStockHistory.date.desc()).all()
        )
    ]


@router.get("/out-of-stock")
def out_of_stock(
    db: Session = Depends(get_db),
):
    return calculate_out_of_stock(db)


def _human_minutes(value):
    if value is None:
        return None
    total = int(round(float(value)))
    days, remainder = divmod(total, 24 * 60)
    hours, minutes = divmod(remainder, 60)
    if days:
        return f"{days} д {hours} ч"
    if hours:
        return f"{hours} ч {minutes} мин"
    return f"{minutes} мин"


@router.get("/wb-review-response-time")
def wb_review_response_time(
    date_from: date | None = Query(None),
    date_to: date | None = Query(None),
    granularity: str = Query("month", pattern="^(day|month)$"),
    db: Session = Depends(get_db),
):
    query = db.query(
        WBReviewResponseTracking.review_created_at,
        WBReviewResponseTracking.response_estimate_minutes,
    ).filter(
        WBReviewResponseTracking.resolution == "answered",
        WBReviewResponseTracking.baseline.is_(False),
        WBReviewResponseTracking.review_created_at.is_not(None),
        WBReviewResponseTracking.response_estimate_minutes.is_not(None),
    )

    if date_from is not None:
        query = query.filter(
            WBReviewResponseTracking.review_created_at
            >= datetime.combine(date_from, time.min)
        )
    if date_to is not None:
        query = query.filter(
            WBReviewResponseTracking.review_created_at
            < datetime.combine(date_to + timedelta(days=1), time.min)
        )

    rows = query.all()
    durations = [
        (created_at, float(minutes))
        for created_at, minutes in rows
        if minutes is not None and minutes >= 0
    ]
    values = sorted(minutes for _, minutes in durations)
    n = len(values)

    if n:
        average = sum(values) / n
        middle = n // 2
        median = (
            values[middle]
            if n % 2
            else (values[middle - 1] + values[middle]) / 2
        )
    else:
        average = median = None

    def percent(limit):
        return (
            round(sum(v <= limit for v in values) / n * 100, 1)
            if n else 0
        )

    distribution = [
        {"key": "under_1h", "label": "До 1 часа", "count": sum(v < 60 for v in values)},
        {"key": "1_4h", "label": "1–4 часа", "count": sum(60 <= v < 240 for v in values)},
        {"key": "4_24h", "label": "4–24 часа", "count": sum(240 <= v < 1440 for v in values)},
        {"key": "24_48h", "label": "24–48 часов", "count": sum(1440 <= v < 2880 for v in values)},
        {"key": "over_48h", "label": "Более 48 часов", "count": sum(v >= 2880 for v in values)},
    ]

    buckets = {}
    for created_at, minutes in durations:
        key = (
            created_at.date().isoformat()
            if granularity == "day"
            else created_at.strftime("%Y-%m")
        )
        buckets.setdefault(key, []).append(minutes)

    trend = []
    for key in sorted(buckets):
        bucket = sorted(buckets[key])
        m = len(bucket)
        mid = m // 2
        bucket_median = (
            bucket[mid]
            if m % 2
            else (bucket[mid - 1] + bucket[mid]) / 2
        )
        label = (
            datetime.strptime(key, "%Y-%m-%d").strftime("%d.%m")
            if granularity == "day"
            else datetime.strptime(key, "%Y-%m").strftime("%m.%Y")
        )
        trend.append({
            "period": key,
            "label": label,
            "answered": m,
            "average_minutes": round(sum(bucket) / m, 1),
            "median_minutes": round(bucket_median, 1),
        })

    return {
        "status": "ok",
        "marketplace": "WB",
        "calculation_mode": "estimated_by_queue_observation",
        "poll_interval_minutes": 2,
        "accuracy_window_minutes": 2,
        "answered_reviews": n,
        "valid_response_times": n,
        "invalid_response_times": 0,
        "average_minutes": round(average, 1) if average is not None else None,
        "median_minutes": round(median, 1) if median is not None else None,
        "average_human": _human_minutes(average),
        "median_human": _human_minutes(median),
        "within_1h_percent": percent(60),
        "within_4h_percent": percent(240),
        "within_24h_percent": percent(1440),
        "within_48h_percent": percent(2880),
        "distribution": distribution,
        "trend": trend,
    }


def _ozon_number(value):
    """Convert Ozon numeric fields and money objects to float."""
    if value is None:
        return 0.0
    if isinstance(value, dict):
        value = value.get("amount")
    try:
        return float(value or 0)
    except (TypeError, ValueError):
        return 0.0


def _ozon_postings_from_raw(raw):
    body = raw.get("body") if isinstance(raw, dict) else None
    if not isinstance(body, dict):
        return [], False, ""
    postings = body.get("postings") or []
    return postings, bool(body.get("has_next")), str(body.get("cursor") or "")


def _ozon_fetch_all_postings(client, kind, since, to, max_pages=1000):
    """Fetch all pages from one Ozon postings endpoint."""
    cursor = ""
    all_postings = []
    pages = 0
    http_statuses = []
    seen_cursors = set()

    while True:
        pages += 1
        if pages > max_pages:
            return {
                "postings": all_postings,
                "pages": pages - 1,
                "truncated": True,
                "error": f"Превышен лимит страниц: {max_pages}",
                "http_statuses": http_statuses,
            }

        if kind == "fbo":
            raw = client.list_fbo_postings_raw(
                since=since, to=to, cursor=cursor, limit=100
            )
        else:
            raw = client.list_fbs_postings_raw(
                since=since, to=to, cursor=cursor, limit=100
            )

        status_code = raw.get("status_code") if isinstance(raw, dict) else None
        http_statuses.append(status_code)
        if status_code != 200:
            return {
                "postings": all_postings,
                "pages": pages,
                "truncated": False,
                "error": "Ozon API вернул ошибку",
                "http_statuses": http_statuses,
                "last_response": raw.get("body") if isinstance(raw, dict) else raw,
            }

        postings, has_next, next_cursor = _ozon_postings_from_raw(raw)
        all_postings.extend(postings)

        if not has_next:
            return {
                "postings": all_postings,
                "pages": pages,
                "truncated": False,
                "error": None,
                "http_statuses": http_statuses,
            }

        if not next_cursor or next_cursor in seen_cursors:
            return {
                "postings": all_postings,
                "pages": pages,
                "truncated": True,
                "error": "Ozon вернул повторяющийся/пустой cursor при has_next=true",
                "http_statuses": http_statuses,
            }

        seen_cursors.add(next_cursor)
        cursor = next_cursor


def _ozon_summarize_postings(postings):
    posting_count = len(postings)
    product_lines = 0
    units = 0.0
    seller_price_sum = 0.0
    product_price_sum = 0.0
    old_price_sum = 0.0
    customer_price_sum = 0.0
    customer_price_lines = 0
    payout_sum = 0.0
    unique_order_numbers = set()
    unique_order_ids = set()
    status_counts = {}
    child_postings = 0
    parent_postings = 0
    sample = []

    for posting in postings:
        order_number = posting.get("order_number")
        order_id = posting.get("order_id")
        if order_number:
            unique_order_numbers.add(str(order_number))
        if order_id is not None:
            unique_order_ids.add(str(order_id))

        status = str(posting.get("status") or "")
        status_counts[status] = status_counts.get(status, 0) + 1

        if posting.get("parent_posting_number"):
            child_postings += 1
        else:
            parent_postings += 1

        financial_products = (posting.get("financial_data") or {}).get("products") or []
        product_lines += len(financial_products)

        for fp in financial_products:
            quantity = _ozon_number(fp.get("quantity"))
            units += quantity
            seller_price_sum += _ozon_number(fp.get("price")) * quantity
            old_price_sum += _ozon_number(fp.get("old_price")) * quantity
            payout_sum += _ozon_number(fp.get("payout"))

            product = next(
                (x for x in (posting.get("products") or [])
                 if str(x.get("sku")) == str(fp.get("product_id"))),
                None,
            )
            if product:
                product_price_sum += _ozon_number(product.get("price")) * quantity

            if fp.get("customer_price") is not None:
                customer_price_sum += _ozon_number(fp.get("customer_price")) * quantity
                customer_price_lines += 1

            if len(sample) < 20:
                sample.append({
                    "posting_number": posting.get("posting_number"),
                    "order_number": order_number,
                    "order_id": order_id,
                    "parent_posting_number": posting.get("parent_posting_number"),
                    "status": status,
                    "offer_id": product.get("offer_id") if product else None,
                    "product_id": fp.get("product_id"),
                    "quantity": fp.get("quantity"),
                    "old_price": fp.get("old_price"),
                    "price": fp.get("price"),
                    "customer_price": fp.get("customer_price"),
                    "total_discount_value": fp.get("total_discount_value"),
                    "payout": fp.get("payout"),
                })

    return {
        "posting_count": posting_count,
        "unique_order_count": len(unique_order_numbers or unique_order_ids),
        "product_lines": product_lines,
        "units": round(units, 3),
        "seller_financial_price_times_quantity": round(seller_price_sum, 2),
        "product_price_times_quantity": round(product_price_sum, 2),
        "old_price_times_quantity": round(old_price_sum, 2),
        "customer_price_times_quantity": round(customer_price_sum, 2),
        "customer_price_lines": customer_price_lines,
        "customer_price_missing_lines": max(0, product_lines - customer_price_lines),
        "payout_sum": round(payout_sum, 2),
        "status_counts": status_counts,
        "parent_postings": parent_postings,
        "child_postings": child_postings,
        "sample_financial_products": sample,
    }


@router.get("/ozon-order-prices-diagnostic")
def ozon_order_prices_diagnostic(
    date_from: date = Query(..., description="Дата начала, YYYY-MM-DD"),
    date_to: date = Query(..., description="Дата окончания, YYYY-MM-DD"),
    db: Session = Depends(get_db),
):
    """
    Полная диагностика FBO/FBS Ozon за период с автоматической пагинацией.

    Ничего не записывает в БД. Нужна для сопоставления полей Ozon с
    показателями «Цена реализации», «Предельная цена» и «Заказано».
    """
    if date_to < date_from:
        raise ValueError("date_to не может быть раньше date_from")

    client = get_ozon_client(db)
    since = f"{date_from.isoformat()}T00:00:00Z"
    to = f"{date_to.isoformat()}T23:59:59Z"

    fbo_result = _ozon_fetch_all_postings(client, "fbo", since, to)
    fbs_result = _ozon_fetch_all_postings(client, "fbs", since, to)

    fbo_summary = _ozon_summarize_postings(fbo_result["postings"])
    fbs_summary = _ozon_summarize_postings(fbs_result["postings"])

    combined = _ozon_summarize_postings(
        fbo_result["postings"] + fbs_result["postings"]
    )

    return {
        "status": "ok" if not fbo_result["error"] and not fbs_result["error"] else "partial",
        "source": "Ozon FBO v3 + FBS v4 postings, full pagination",
        "date_from": date_from.isoformat(),
        "date_to": date_to.isoformat(),
        "period": {"since": since, "to": to},
        "fbo": {
            "pages": fbo_result["pages"],
            "truncated": fbo_result["truncated"],
            "error": fbo_result["error"],
            "http_statuses": fbo_result["http_statuses"],
            "summary": fbo_summary,
            **({"last_response": fbo_result["last_response"]} if "last_response" in fbo_result else {}),
        },
        "fbs": {
            "pages": fbs_result["pages"],
            "truncated": fbs_result["truncated"],
            "error": fbs_result["error"],
            "http_statuses": fbs_result["http_statuses"],
            "summary": fbs_summary,
            **({"last_response": fbs_result["last_response"]} if "last_response" in fbs_result else {}),
        },
        "combined": combined,
        "comparison_candidates": {
            "customer_price_times_quantity": combined["customer_price_times_quantity"],
            "seller_financial_price_times_quantity": combined["seller_financial_price_times_quantity"],
            "product_price_times_quantity": combined["product_price_times_quantity"],
            "old_price_times_quantity": combined["old_price_times_quantity"],
            "payout_sum": combined["payout_sum"],
            "ordered_units_candidate": combined["units"],
        },
    }




def _ozon_reconcile_postings(postings):
    """Diagnostic only: do not invent missing FBO quantities or customer prices."""
    from collections import defaultdict
    from decimal import Decimal, InvalidOperation

    def amount(value):
        if isinstance(value, dict):
            value = value.get("amount")
        if value is None or value == "":
            return None
        try:
            return Decimal(str(value))
        except (InvalidOperation, ValueError, TypeError):
            return None

    groups = defaultdict(lambda: {
        "postings": 0, "financial_lines": 0, "resolved_lines": 0,
        "unresolved_lines": 0, "units": 0, "price_sum": Decimal(0),
        "customer_price_sum": Decimal(0), "customer_price_covered": 0,
        "created_at_missing": 0, "created_dates": defaultdict(int),
    })
    reasons = defaultdict(int)
    examples = []
    for posting in postings:
        kind = "cancelled" if str(posting.get("status") or "").lower() in ("cancelled", "canceled") else "not_cancelled"
        scheme = "fbo" if posting.get("_diag_scheme") == "fbo" else "fbs"
        bucket = groups[(scheme,kind)]
        bucket["postings"] += 1
        created_at = str(posting.get("created_at") or "")
        if not created_at:
            bucket["created_at_missing"] += 1
        else:
            bucket["created_dates"][created_at[:10]] += 1
        financial = (posting.get("financial_data") or {}).get("products") or []
        products = posting.get("products") or []
        bucket["financial_lines"] += len(financial)
        for fp in financial:
            q = amount(fp.get("quantity"))
            match = None
            if q is None:
                # Match financial product_id against SKU; only one unambiguous match is safe.
                matches = [x for x in products if str(x.get("sku")) == str(fp.get("product_id"))]
                if len(matches) == 1:
                    match = matches[0]
                elif len(products) == 1 and len(financial) == 1:
                    match = products[0]
                if match is not None:
                    q = amount(match.get("quantity"))
            if q is None or q <= 0 or q != q.to_integral_value():
                bucket["unresolved_lines"] += 1
                reasons[(scheme,"quantity_unresolved")] += 1
                if len(examples) < 5:
                    examples.append({"scheme":scheme,"status":kind,"financial_product_id":str(fp.get("product_id")),"product_skus":[str(x.get("sku")) for x in products],"product_quantities":[x.get("quantity") for x in products]})
                continue
            bucket["resolved_lines"] += 1
            bucket["units"] += int(q)
            price = amount(fp.get("price"))
            if price is not None:
                bucket["price_sum"] += price*q
            cp = amount(fp.get("customer_price"))
            if cp is not None:
                bucket["customer_price_sum"] += cp*q
                bucket["customer_price_covered"] += 1
    result = {}
    for (scheme,kind), v in sorted(groups.items()):
        result[f"{scheme}_{kind}"] = {
            **{k:val for k,val in v.items() if k not in ("price_sum","customer_price_sum","created_dates")},
            "price_sum": str(v["price_sum"]),
            "customer_price_sum": str(v["customer_price_sum"]),
            "created_dates": dict(sorted(v["created_dates"].items())),
        }
    return {"by_scheme_and_status":result,
            "unresolved_reasons":{f"{k[0]}:{k[1]}":v for k,v in reasons.items()},
            "unresolved_examples_without_order_ids":examples,
            "note":"FBO customer_price cannot be reconstructed from seller price; created_at may differ from Ozon chart attribution."}


@router.get("/ozon-order-prices-reconcile-diagnostic")
def ozon_order_prices_reconcile_diagnostic(
    date_from: date = Query(...),
    date_to: date = Query(...),
    db: Session = Depends(get_db),
):
    """Read-only FBO/FBS check with quantity recovery and cancelled separation."""
    if date_to < date_from:
        raise ValueError("date_to не может быть раньше date_from")
    client = get_ozon_client(db)
    since = f"{date_from.isoformat()}T00:00:00Z"
    to = f"{date_to.isoformat()}T23:59:59Z"
    fbo = _ozon_fetch_all_postings(client,"fbo",since,to)
    fbs = _ozon_fetch_all_postings(client,"fbs",since,to)
    rows = [{**p,"_diag_scheme":"fbo"} for p in fbo["postings"]] + [{**p,"_diag_scheme":"fbs"} for p in fbs["postings"]]
    data = _ozon_reconcile_postings(rows)
    return {"status":"ok" if not (fbo["error"] or fbs["error"] or fbo["truncated"] or fbs["truncated"]) else "partial",
            "date_from":str(date_from),"date_to":str(date_to),
            "sources":{"fbo":{"pages":fbo["pages"],"error":fbo["error"],"truncated":fbo["truncated"]},"fbs":{"pages":fbs["pages"],"error":fbs["error"],"truncated":fbs["truncated"]}},
            **data}


def _ozon_date_field_diagnostic(postings, scheme, requested_day):
    """Read-only: expose date-field coverage and prices grouped by their own dates.

    No attempt to equate shipment processing date with order creation date.
    """
    from collections import defaultdict
    from datetime import datetime, timezone, timedelta
    from decimal import Decimal, InvalidOperation

    moscow = timezone(timedelta(hours=3))
    coverage = defaultdict(lambda: {"present": 0, "missing": 0, "invalid": 0,
                                  "utc_dates": defaultdict(int), "moscow_dates": defaultdict(int)})
    aggregates = defaultdict(lambda: {"postings": 0, "units": 0, "price_sum": Decimal(0),
                                  "customer_price_sum": Decimal(0), "customer_price_lines": 0,
                                  "missing_quantity": 0})
    fields = ("created_at", "in_process_at", "shipment_date", "delivering_date")

    def parse_date(value):
        if not isinstance(value, str) or not value.strip():
            return None
        try:
            dt = datetime.fromisoformat(value.strip().replace('Z', '+00:00'))
            return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)
        except ValueError:
            return None

    def money(value):
        if isinstance(value, dict):
            value = value.get('amount')
        try:
            return Decimal(str(value)) if value not in (None, '') else None
        except (ValueError, TypeError, InvalidOperation):
            return None

    for posting in postings:
        status = str(posting.get('status') or '').lower()
        status_group = 'cancelled' if status in ('cancelled', 'canceled') else 'not_cancelled'
        financial = (posting.get('financial_data') or {}).get('products') or []
        products = posting.get('products') or []
        for field in fields:
            val = posting.get(field)
            if val in (None, ''):
                coverage[field]['missing'] += 1
                continue
            dt = parse_date(val)
            if dt is None:
                coverage[field]['invalid'] += 1
                continue
            coverage[field]['present'] += 1
            utc_day = dt.astimezone(timezone.utc).date().isoformat()
            ms_day = dt.astimezone(moscow).date().isoformat()
            coverage[field]['utc_dates'][utc_day] += 1
            coverage[field]['moscow_dates'][ms_day] += 1
            a = aggregates[(field, ms_day, status_group)]
            a['postings'] += 1
            for fp in financial:
                q = money(fp.get('quantity'))
                if q is None:
                    matches = [x for x in products if str(x.get('sku')) == str(fp.get('product_id'))]
                    if len(matches) == 1:
                        q = money(matches[0].get('quantity'))
                    elif len(products) == 1 and len(financial) == 1:
                        q = money(products[0].get('quantity'))
                if q is None or q <= 0 or q != q.to_integral_value():
                    a['missing_quantity'] += 1
                    continue
                a['units'] += int(q)
                price = money(fp.get('price'))
                cp = money(fp.get('customer_price'))
                if price is not None:
                    a['price_sum'] += price*q
                if cp is not None:
                    a['customer_price_sum'] += cp*q
                    a['customer_price_lines'] += 1

    summarized = {}
    for key, a in sorted(aggregates.items()):
        field, day, status = key
        # Keep the response small: requested day and adjacent dates only.
        if abs((datetime.fromisoformat(day).date() - requested_day).days) > 1:
            continue
        summarized[f'{field}|{day}|{status}'] = {
            **{k:v for k,v in a.items() if k not in ('price_sum','customer_price_sum')},
            'price_sum': str(a['price_sum']),
            'customer_price_sum': str(a['customer_price_sum']),
        }
    return {
        'scheme': scheme,
        'posting_count': len(postings),
        'date_field_coverage': {
            k: {**{t:v for t,v in d.items() if t not in ('utc_dates','moscow_dates')},
                'utc_dates': dict(sorted(d['utc_dates'].items())),
                'moscow_dates': dict(sorted(d['moscow_dates'].items()))}
            for k,d in coverage.items()
        },
        'by_date_and_status': summarized,
        'caution': 'in_process_at is processing-start time, NOT order-created time; FBO customer_price is absent.',
    }


@router.get('/ozon-order-date-fields-diagnostic')
def ozon_order_date_fields_diagnostic(
    date_from: date = Query(...),
    date_to: date = Query(...),
    db: Session = Depends(get_db),
):
    """Non-mutating FBO/FBS date and price breakdown, never stores orders."""
    if date_to < date_from:
        raise ValueError('date_to не может быть раньше date_from')
    client = get_ozon_client(db)
    # Separate query interval from the classification of timestamps inside postings.
    since = f'{date_from.isoformat()}T00:00:00Z'
    to = f'{date_to.isoformat()}T23:59:59Z'
    fbo = _ozon_fetch_all_postings(client, 'fbo', since, to)
    fbs = _ozon_fetch_all_postings(client, 'fbs', since, to)
    return {
        'status': 'ok' if not (fbo['error'] or fbs['error'] or fbo['truncated'] or fbs['truncated']) else 'partial',
        'date_from': str(date_from), 'date_to': str(date_to),
        'query_interval_utc': {'since': since, 'to': to},
        'reference_sold_revenue': '1512469' if date_from == date_to == date(2026,10,12) else None,
        'sources': {
            'fbo': {'pages':fbo['pages'], 'error':fbo['error'], 'truncated':fbo['truncated']},
            'fbs': {'pages':fbs['pages'], 'error':fbs['error'], 'truncated':fbs['truncated']},
        },
        'fbo': _ozon_date_field_diagnostic(fbo['postings'],'fbo',date_from),
        'fbs': _ozon_date_field_diagnostic(fbs['postings'],'fbs',date_from),
        'note': 'Dates in posting list filters do not necessarily identify order-creation date; no API fields are inferred.',
    }




@router.get('/yandex-sales')
def yandex_sales(
    date_from: date = Query(..., description='Начало периода'),
    date_to: date = Query(..., description='Конец периода'),
    db: Session = Depends(get_db),
):
    """Сумма заказанных товаров по проверенному правилу сопоставления с Excel.

    Это показатель «Заказано», не доставленные товары и не финансовая выручка.
    """
    from fastapi import HTTPException
    if date_to < date_from or (date_to - date_from).days > 366:
        raise HTTPException(status_code=422, detail='Период должен быть от 1 до 367 дней.')

    excluded = (
        (YandexSalesOrderLine.order_status == 'CANCELLED') &
        (YandexSalesOrderLine.order_substatus.in_([
            'USER_NOT_PAID', 'USER_WANTED_ANOTHER_PAYMENT_METHOD'
        ]))
    )
    amount = (YandexSalesOrderLine.payment + YandexSalesOrderLine.cashback + YandexSalesOrderLine.subsidy)
    sales = (db.query(
        YandexSalesOrderLine.sale_date.label('date'),
        func.sum(YandexSalesOrderLine.quantity).label('units'),
        func.sum(amount).label('revenue'),
    ).filter(
        YandexSalesOrderLine.sale_date >= date_from,
        YandexSalesOrderLine.sale_date <= date_to,
        ~excluded,
    ).group_by(YandexSalesOrderLine.sale_date).all())
    by_date = {day.isoformat(): {'date': day.isoformat(), 'revenue': round(float(revenue or 0), 2), 'ordered_units': int(units or 0)}
               for day, units, revenue in sales}
    checkpoints = (db.query(YandexSalesSyncDay.sale_date)
                   .filter(YandexSalesSyncDay.sale_date >= date_from,
                           YandexSalesSyncDay.sale_date <= date_to).all())
    loaded_dates = {item[0].isoformat() for item in checkpoints}
    rows = []
    current = date_from
    while current <= date_to:
        key = current.isoformat()
        rows.append({**by_date.get(key, {'date': key, 'revenue': 0, 'ordered_units': 0}),
                     'loaded': key in loaded_dates})
        current += timedelta(days=1)
    return {
        'status': 'ok', 'source': 'DB', 'metric': 'ordered',
        'date_from': date_from.isoformat(), 'date_to': date_to.isoformat(),
        'rows': rows,
        'totals': {'revenue': round(sum(r['revenue'] for r in rows), 2),
                   'ordered_units': sum(r['ordered_units'] for r in rows)},
        'coverage': {'loaded_days': len(loaded_dates), 'period_days': len(rows),
                     'complete': len(loaded_dates) == len(rows)},
        'note': 'Эмпирическое правило исключения неоплаченных отмен, сверено с Excel за 12, 13, 14 и 20.10.2026.'
    }

@router.get("/ozon-sales")
def ozon_sales(
    date_from: date = Query(..., description="Дата начала периода, YYYY-MM-DD"),
    date_to: date = Query(..., description="Дата конца периода, YYYY-MM-DD"),
    db: Session = Depends(get_db),
):
    """Продажи Ozon из локальной БД, без обращения к Ozon API."""
    if date_to < date_from:
        raise ValueError("date_to не может быть раньше date_from")

    rows = (
        db.query(OzonSalesDaily)
        .filter(
            OzonSalesDaily.sale_date >= date_from,
            OzonSalesDaily.sale_date <= date_to,
        )
        .order_by(OzonSalesDaily.sale_date.asc())
        .all()
    )

    return {
        "status": "ok",
        "source": "DB",
        "date_from": date_from.isoformat(),
        "date_to": date_to.isoformat(),
        "rows": [
            {
                "date": item.sale_date.isoformat(),
                "revenue": float(item.revenue or 0),
                "ordered_units": int(item.ordered_units or 0),
                "last_synced_at": (
                    item.last_synced_at.isoformat()
                    if item.last_synced_at
                    else None
                ),
            }
            for item in rows
        ],
        "totals": {
            "revenue": round(
                sum(float(item.revenue or 0) for item in rows),
                2,
            ),
            "ordered_units": sum(
                int(item.ordered_units or 0)
                for item in rows
            ),
        },
    }


@router.get('/ozon-realization-by-day-diagnostic')
def ozon_realization_by_day_diagnostic(
    day: date = Query(..., description='Дата отчёта, YYYY-MM-DD'),
    db: Session = Depends(get_db),
):
    """Проверка официального ежедневного отчёта без изменения данных.

    ВАЖНО: это отчёт о реализации (доставленных товарах), а не
    подтверждённый эквивалент аналитического soldRevenue по дате заказа.
    """
    from decimal import Decimal, InvalidOperation

    from fastapi import HTTPException

    if day > date.today() or (date.today() - day).days > 32:
        raise HTTPException(
            status_code=422,
            detail='Метод поддерживает даты не старше 32 дней и не в будущем.',
        )

    client = get_ozon_client(db)
    result = client.post_raw(
        '/v1/finance/realization/by-day',
        {'day': day.day, 'month': day.month, 'year': day.year},
    )
    status = result.get('status_code')
    body = result.get('body')

    # Намеренно не возвращаем сырые строки отчёта, персональные данные,
    # реквизиты, токены и произвольные диагностические HTTP-сообщения.
    if status != 200:
        return {
            'status': 'unavailable',
            'date': day.isoformat(),
            'http_status': status,
            'possible_reasons': (
                ['Требуется Premium Plus/Pro либо нет доступа к методу']
                if status == 403 else
                ['Проверить доступность метода и дату в документации Ozon']
            ),
            'source': '/v1/finance/realization/by-day',
        }

    fields = set()
    candidates = {}
    node_count = 0

    def inspect(value, path='', depth=0):
        nonlocal node_count
        node_count += 1
        if depth > 9 or node_count > 15000:
            return
        if isinstance(value, dict):
            for k, v in value.items():
                key = str(k)
                # Не выводить произвольные ключи/значения от Ozon.
                if len(key) > 70 or not all(c.isalnum() or c == '_' for c in key):
                    continue
                p = f'{path}.{key}' if path else key
                if isinstance(v, (dict, list)):
                    inspect(v, p, depth + 1)
                elif isinstance(v, (int, float)) and not isinstance(v, bool):
                    fields.add(p)
                    if any(word in key.lower() for word in
                           ('amount', 'price', 'sum', 'total', 'revenue', 'sale', 'realiz')):
                        try:
                            candidates[p] = str(Decimal(str(v)))
                        except InvalidOperation:
                            pass
                elif isinstance(v, str) and any(word in key.lower() for word in
                                            ('amount', 'price', 'sum', 'total', 'revenue')):
                    try:
                        candidates[p] = str(Decimal(v))
                        fields.add(p)
                    except InvalidOperation:
                        pass
        elif isinstance(value, list):
            for item in value[:2000]:
                # Однотипные строки агрегируем по имени поля, а не индексу.
                inspect(item, f'{path}[]', depth + 1)

    inspect(body)
    return {
        'status': 'ok',
        'date': day.isoformat(),
        'http_status': status,
        'source': '/v1/finance/realization/by-day',
        'top_level_fields': sorted(body.keys()) if isinstance(body, dict) else [],
        'numeric_field_paths': sorted(fields)[:150],
        'sample_money_values': dict(list(candidates.items())[:40]),
        'inspection_truncated': node_count > 15000,
        'warning': 'Данные реализации не равнозначны заказам по дате создания.',
    }

@router.get('/ozon-realization-by-day-totals')
def ozon_realization_by_day_totals(
    day: date = Query(..., description='Дата отчёта, YYYY-MM-DD'),
    db: Session = Depends(get_db),
):
    """Диагностика агрегатов; null в отдельных полях не обнуляет целую строку.

    В ответе только агрегаты и статистика заполненности, без строк отчёта.
    """
    from collections import Counter
    from decimal import Decimal, InvalidOperation
    from fastapi import HTTPException

    if day > date.today() or (date.today() - day).days > 32:
        raise HTTPException(status_code=422, detail='Дата должна быть в пределах последних 32 дней.')

    raw = get_ozon_client(db).post_raw(
        '/v1/finance/realization/by-day',
        {'day': day.day, 'month': day.month, 'year': day.year},
    )
    if raw.get('status_code') != 200:
        return {'status': 'unavailable', 'http_status': raw.get('status_code'), 'date': day.isoformat()}
    body = raw.get('body')
    if not isinstance(body, dict) or not isinstance(body.get('rows'), list):
        return {'status': 'invalid_response', 'date': day.isoformat()}

    def parse_decimal(value):
        if value is None or value == '':
            return None
        try:
            result = Decimal(str(value).replace(' ', '').replace(',', '.'))
            return result if result.is_finite() else None
        except (InvalidOperation, TypeError, ValueError):
            return None

    # Каждый показатель считается независимо: пустой return_commission
    # не исключает корректные данные из delivery_commission.
    paths = (
        'seller_price_per_instance',
        'delivery_commission.quantity', 'delivery_commission.price_per_instance',
        'delivery_commission.amount', 'delivery_commission.total',
        'return_commission.quantity', 'return_commission.price_per_instance',
        'return_commission.amount', 'return_commission.total',
    )
    non_null = Counter()
    missing = Counter()
    invalid = Counter()
    field_sums = {name: Decimal(0) for name in paths}
    weighted_sums = {
        'delivered_seller_price': Decimal(0),
        'returned_seller_price': Decimal(0),
        'delivered_report_price': Decimal(0),
        'returned_report_price': Decimal(0),
    }
    weighted_coverage = Counter()
    non_object_rows = 0

    for row in body['rows']:
        if not isinstance(row, dict):
            non_object_rows += 1
            continue
        parsed = {}
        for path in paths:
            parent, dot, child = path.partition('.')
            source = row.get(parent)
            value = (source.get(child) if isinstance(source, dict) else None) if dot else source
            number = parse_decimal(value)
            parsed[path] = number
            if number is None:
                (missing if value is None or value == '' else invalid)[path] += 1
            else:
                non_null[path] += 1
                field_sums[path] += number

        for label, prefix in [('delivered', 'delivery_commission'), ('returned', 'return_commission')]:
            q = parsed[prefix + '.quantity']
            seller = parsed['seller_price_per_instance']
            report = parsed[prefix + '.price_per_instance']
            if q is not None and seller is not None:
                weighted_sums[label + '_seller_price'] += q * seller
                weighted_coverage[label + '_seller_price'] += 1
            if q is not None and report is not None:
                weighted_sums[label + '_report_price'] += q * report
                weighted_coverage[label + '_report_price'] += 1

    reference = Decimal('1512469') if day.isoformat() == '2026-10-12' else None
    # При неполном покрытии не представлять агрегат как подтверждённый итог.
    result = {
        'status': 'diagnostic',
        'date': day.isoformat(),
        'source': '/v1/finance/realization/by-day',
        'row_count': len(body['rows']),
        'non_object_rows': non_object_rows,
        'field_coverage': {
            path: {'valid': non_null[path], 'missing_or_null': missing[path], 'invalid': invalid[path]}
            for path in paths
        },
        'field_sums': {path: str(value) for path, value in field_sums.items()},
        'weighted_sums': {path: str(value) for path, value in weighted_sums.items()},
        'weighted_coverage': dict(weighted_coverage),
        'reference_sold_revenue': str(reference) if reference is not None else None,
        'warning': 'Частичные суммы при отсутствующих полях не являются итогами продаж. Отчёт по дате реализации не равен метрике по дате заказа.',
    }
    if reference is not None:
        result['differences_from_reference'] = {
            path: str(value - reference)
            for path, value in weighted_sums.items()
        }
    return result


@router.get('/ozon-day-window-diagnostic')
def ozon_day_window_diagnostic(
    day: date = Query(..., description='Календарный день в Москве, YYYY-MM-DD'),
    db: Session = Depends(get_db),
):
    """Read-only comparison of UTC and Moscow day windows; no DB writes.

    Warning: API posting-list filter semantics may differ from order creation.
    Neither customer_price nor price is certified to equal UI soldRevenue.
    """
    from datetime import datetime, time, timedelta, timezone
    from decimal import Decimal, InvalidOperation
    from collections import defaultdict
    from fastapi import HTTPException

    def dec(value):
        if isinstance(value, dict):
            value = value.get('amount')
        if value in (None, ''):
            return None
        try:
            return Decimal(str(value))
        except (TypeError, ValueError, InvalidOperation):
            return None

    def summarize(postings):
        groups = defaultdict(lambda: {'postings': 0, 'units': 0, 'price_sum': Decimal(0),
                                     'customer_price_sum': Decimal(0), 'customer_price_units': 0,
                                     'missing_price_units': 0, 'missing_customer_price_units': 0,
                                     'unresolved_quantity_lines': 0})
        for posting in postings:
            status = str(posting.get('status') or '').lower()
            label = 'cancelled' if status in ('cancelled','canceled') else 'not_cancelled'
            group = groups[label]
            group['postings'] += 1
            financial = (posting.get('financial_data') or {}).get('products') or []
            products = posting.get('products') or []
            for fp in financial:
                qty = dec(fp.get('quantity'))
                if qty is None:
                    matches = [x for x in products if str(x.get('sku')) == str(fp.get('product_id'))]
                    if len(matches) == 1:
                        qty = dec(matches[0].get('quantity'))
                    elif len(products) == 1 and len(financial) == 1:
                        qty = dec(products[0].get('quantity'))
                if qty is None or qty <= 0 or qty != qty.to_integral_value():
                    group['unresolved_quantity_lines'] += 1
                    continue
                group['units'] += int(qty)
                price = dec(fp.get('price'))
                cp = dec(fp.get('customer_price'))
                if price is not None:
                    group['price_sum'] += qty * price
                else:
                    group['missing_price_units'] += int(qty)
                if cp is not None:
                    group['customer_price_sum'] += qty * cp
                    group['customer_price_units'] += int(qty)
                else:
                    group['missing_customer_price_units'] += int(qty)
        return {k: {field: str(v) if isinstance(v, Decimal) else v for field,v in stats.items()}
                for k,stats in sorted(groups.items())}

    tz_msk = timezone(timedelta(hours=3))
    base_utc = datetime.combine(day, time.min, tzinfo=timezone.utc)
    base_msk = datetime.combine(day, time.min, tzinfo=tz_msk).astimezone(timezone.utc)
    windows = [('utc',base_utc), ('moscow',base_msk)]
    client = get_ozon_client(db)
    output = {}
    for name, start in windows:
        # Exclusive 24h bound converted to inclusive final microsecond for API.
        end = start + timedelta(days=1) - timedelta(milliseconds=1)
        since = start.isoformat(timespec='milliseconds').replace('+00:00','Z')
        to = end.isoformat(timespec='milliseconds').replace('+00:00','Z')
        by_scheme = {}
        for scheme in ('fbo','fbs'):
            result = _ozon_fetch_all_postings(client,scheme,since,to)
            by_scheme[scheme] = {
                'pages': result['pages'],
                'truncated': result['truncated'],
                'error': result['error'],
                'postings_count': len(result['postings']),
                'by_status': summarize(result['postings']),
            }
        output[name] = {'since': since, 'to': to, 'schemes': by_scheme}
    return {
        'date': str(day),
        'status': 'ok' if all(not d['error'] and not d['truncated'] for w in output.values() for d in w['schemes'].values()) else 'partial',
        'reference_sold_revenue': '1512469' if day == date(2026,10,12) else None,
        'windows': output,
        'warning': 'Posting-list filters and processing dates are not guaranteed to be order-creation dates. FBO customer_price may be absent. No resulting sum is certified as Ozon soldRevenue.',
    }

@router.get('/ozon-realization-posting-beta-probe')
def ozon_realization_posting_beta_probe(
    year: int = Query(2026, ge=2023, le=2100),
    month: int = Query(10, ge=1, le=12),
    db: Session = Depends(get_db),
):
    """One-shot, read-only probe of the July 2026 report-generation beta endpoint.

    Request shape (month/year) is a HYPOTHESIS based on the legacy posting
    realization API, not a verified schema for the new report method.
    May create a report-generation job on Ozon; no local database writes.
    Never return auth headers or raw report contents.
    """
    from fastapi import HTTPException

    raw = get_ozon_client(db).post_raw(
        '/v1/report/realization/posting/create',
        {'month': month, 'year': year},
    )
    status = raw.get('status_code')
    data = raw.get('body')
    result = data.get('result') if isinstance(data, dict) else None
    report_code = result.get('code') if isinstance(result, dict) else None
    if status == 200:
        return {
            'status': 'accepted' if report_code else 'response_needs_review',
            'http_status': status,
            'source': '/v1/report/realization/posting/create',
            'request_shape_verified': False,
            'report_code': report_code,
            'top_level_fields': list(data.keys()) if isinstance(data, dict) else [],
            'next': 'If report_code exists, inspect /v1/report/info using that code. No sales sum is confirmed.',
        }
    # Only expose allowlisted Ozon validation errors; never echo raw HTML/body.
    safe_error = {}
    if isinstance(data, dict):
        for key in ('code', 'message', 'error'):
            value = data.get(key)
            if isinstance(value, (str, int, float)):
                safe_error[key] = str(value)[:600]
    return {
        'status': 'unavailable_or_invalid_request',
        'http_status': status,
        'source': '/v1/report/realization/posting/create',
        'request_shape_verified': False,
        'request': {'month': month, 'year': year},
        'ozon_error': safe_error,
        'note': 'The beta endpoint is confirmed to exist, but month/year parameters have not been confirmed for it.',
    }


@router.get('/ozon-graph-report-api-key-probe')
def ozon_graph_report_api_key_probe(
    day: date = Query(date(2026, 10, 12)),
    db: Session = Depends(get_db),
):
    """Test public Seller credentials against Ozon's internal graph report API.

    No cookies, no redirects, no DB updates or downloads. A successful request
    may create a report job on Ozon. Only allowlisted response fields shown.
    """
    import requests
    from urllib.parse import urljoin, urlsplit, parse_qsl
    client = get_ozon_client(db)
    request_json = {
        'dimension': 'sku',
        'filters': {'desc_type_ids': [], 'category_3_ids': [], 'category_2_ids': []},
        'metrics': [
            'sold_revenue','revenue','sold_revenue_share','search_position','total_views',
            'conv_views_to_order','search_views','conv_search_views_to_cart','hits_search_to_cart',
            'conv_search_views_to_pdp','pdp_views','conv_pdp_views_to_cart','hits_pdp_to_cart',
            'conv_total_views_to_cart','total_hits_to_cart','conv_hits_to_cart_to_order',
            'ordered_units','delivered_units','conv_order_to_purchase','purchased_units',
            'cancelled_units_by_order_date','returned_units_by_order_date','avg_sold_price',
            'discount_share_of_median_price','price_index','days_in_promo','drr',
            'days_in_trafarets','last_stock','stockout_days','reviews_count','rating',
            'recommended_supply','sold_revenue_dynamics','revenue_dynamics',
            'sold_revenue_share_dynamics','search_position_dynamics','total_views_dynamics',
            'conv_views_to_order_dynamics','search_views_dynamics',
            'conv_search_views_to_cart_dynamics','hits_search_to_cart_dynamics',
            'conv_search_views_to_pdp_dynamics','pdp_views_dynamics',
            'conv_pdp_views_to_cart_dynamics','hits_pdp_to_cart_dynamics',
            'conv_total_views_to_cart_dynamics','total_hits_to_cart_dynamics',
            'conv_hits_to_cart_to_order_dynamics','ordered_units_dynamics',
            'delivered_units_dynamics','conv_order_to_purchase_dynamics',
            'purchased_units_dynamics','cancelled_units_by_order_date_dynamics',
            'returned_units_by_order_date_dynamics','avg_sold_price_dynamics',
            'discount_share_of_median_price_dynamics','drr_dynamics',
        ],
        'need_abc': True,
        'period': {'date_from': day.isoformat(), 'date_to': day.isoformat()},
        'previous_period': {
            'date_from': (day - timedelta(days=1)).isoformat(),
            'date_to': (day - timedelta(days=1)).isoformat(),
        },
        'sort': {'key': 'sold_revenue_sort', 'order': 'desc'},
    }
    # Use only the two official Ozon hostnames. Do not follow redirects,
    # which might forward credentials to another host.
    hosts = ['https://seller.ozon.ru', 'https://api-seller.ozon.ru']
    results = []
    for host in hosts:
        endpoint = host + '/api/v1/report/graph_v3' if 'seller.ozon.ru' in host and 'api-seller' not in host else host + '/api/v1/report/graph_v3'
        headers = {
            'Client-Id': client.client_id,
            'Api-Key': client.api_key,
            'Accept': 'application/json',
            'Content-Type': 'application/json',
            'x-o3-app-name': 'seller-ui',
            'x-o3-company-id': client.client_id,
            'x-o3-language': 'ru',
            'x-o3-page-type': 'analytics_graph',
        }
        try:
            response = requests.post(endpoint, headers=headers, json=request_json,
                                     timeout=20, allow_redirects=False)
        except requests.Timeout:
            results.append({'host':host,'status':'timeout'}); continue
        except requests.RequestException:
            results.append({'host':host,'status':'connection_error'}); continue
        try:
            body = response.json()
        except ValueError:
            body = None
        safe = {'host': host, 'http_status': response.status_code,
                'content_type': response.headers.get('content-type', '').split(';')[0],
                'redirected': False,
                'body_is_json': isinstance(body,dict)}
        if 300 <= response.status_code < 400:
            location = response.headers.get('Location', '')
            if location:
                try:
                    target = urlsplit(urljoin(endpoint, location))
                    origin = urlsplit(endpoint)
                    safe['redirect_target'] = {
                        'scheme': target.scheme,
                        'host': target.hostname,
                        'path': target.path[:250],
                        'same_origin': (
                            target.scheme == origin.scheme
                            and target.netloc == origin.netloc
                        ),
                        'query_present': bool(target.query),
                        'query_parameter_names': sorted(set(k[:60] for k, _ in parse_qsl(target.query, keep_blank_values=True)))[:20],
                    }
                except ValueError:
                    safe['redirect_target'] = {'parse_error': True}
            safe['note'] = 'Redirect not followed; credentials were not forwarded.'
        if isinstance(body, dict):
            safe['response_keys'] = sorted([str(k)[:80] for k in body.keys()])[:30]
            if response.status_code in (200,201,202):
                safe['report_code_present'] = isinstance(body.get('code'), str)
                safe['report_code'] = body.get('code') if isinstance(body.get('code'), str) and len(body.get('code')) <= 80 else None
            else:
                safe['error_code'] = body.get('error_code') if isinstance(body.get('error_code'),(int,float)) else None
                safe['error_kind'] = str(body.get('code'))[:80] if isinstance(body.get('code'),(str,int)) else None
        results.append(safe)
    return {
        'status': 'diagnostic',
        'date': day.isoformat(),
        'method': 'POST',
        'path': '/api/v1/report/graph_v3',
        'credentials': 'Existing Seller API Client-Id / Api-Key only; no browser cookies',
        'results': results,
        'note': 'HTTP 200 with report code confirms job creation; 401/403 means this auth method was rejected for this request. Do not interpret 404 as proof the service does not exist.',
    }

@router.get('/ozon-posting-price-details')
def ozon_posting_price_details(
    scheme: str = Query(..., pattern='^(fbo|fbs)$'),
    posting_number: str = Query(..., min_length=3, max_length=100),
    db: Session = Depends(get_db),
):
    """Read-only inspect price fields of an individual posting (no personal data)."""
    from backend.services.ozon_order_details import get_posting_details, redact_prices
    client = get_ozon_client(db)
    return redact_prices(get_posting_details(client, scheme, posting_number), scheme)


@router.get('/ozon-posting-price-compare')
def ozon_posting_price_compare(
    fbo_posting_number: str = Query(..., min_length=3, max_length=100),
    fbs_posting_number: str = Query(..., min_length=3, max_length=100),
    db: Session = Depends(get_db),
):
    """Compare one FBO and one FBS posting, no persistence or buyer personal data."""
    from backend.services.ozon_order_details import get_posting_details, redact_prices
    client = get_ozon_client(db)
    return {
        'fbo': redact_prices(get_posting_details(client, 'fbo', fbo_posting_number), 'fbo'),
        'fbs': redact_prices(get_posting_details(client, 'fbs', fbs_posting_number), 'fbs'),
    }


@router.get("/ozon-order-estimate")
def ozon_order_estimate(
    date_from: date = Query(...),
    date_to: date = Query(...),
    db: Session = Depends(get_db),
):
    """Persisted CBR conversion of FBO/FBS customer prices; NOT Ozon soldRevenue."""
    from fastapi import HTTPException
    from backend.services.ozon_order_sync import daily_totals
    if date_to < date_from or (date_to - date_from).days > 90:
        raise HTTPException(status_code=422, detail="Недопустимый диапазон дат")
    return daily_totals(db, date_from, date_to)


@router.get("/ozon-events")
def ozon_events(date_from: date = Query(...), date_to: date = Query(...), db: Session = Depends(get_db)):
    """Observed dated events from Ozon API; include coverage caveats."""
    from fastapi import HTTPException
    from backend.services.ozon_event_sync import event_totals
    if date_to < date_from or (date_to-date_from).days > 90:
        raise HTTPException(status_code=422, detail="Недопустимый диапазон дат")
    return event_totals(db,date_from,date_to)


@router.get("/response-monitoring")
def response_monitoring(
    marketplace: str = Query("all", pattern="^(all|wb|yandex)$"),
    kind: str = Query("reviews", pattern="^(reviews|questions)$"),
    granularity: str = Query("month", pattern="^(day|month)$"),
    date_from: date | None = Query(None),
    date_to: date | None = Query(None),
    limit: int = Query(100, ge=1, le=500),
    offset: int = Query(0, ge=0),
    db: Session = Depends(get_db),
):
    """Tenant-scoped, weighted monitoring analytics with auditable review/question IDs.

    Period filters refer to the original creation date.
    Operational KPIs include confirmed answers and ongoing unanswered timers.
    Completion is an observed confirmation, not necessarily the exact answer timestamp.
    """
    from collections import defaultdict
    from statistics import median
    from fastapi import HTTPException
    from backend.models.wb_question_response_tracking import WBQuestionResponseTracking
    from backend.models.yandex_review_response_tracking import YandexReviewResponseTracking
    from backend.models.yandex_question_response_tracking import YandexQuestionResponseTracking
    from backend.models.yandex_review import YandexReview

    if date_from and date_to and date_from > date_to:
        raise HTTPException(status_code=422, detail="date_from must not exceed date_to")
    if date_from and date_to and (date_to - date_from).days > 366:
        raise HTTPException(status_code=422, detail="Period exceeds 366 days")

    sources = []
    if marketplace in ("all", "wb"):
        model = WBReviewResponseTracking if kind == "reviews" else WBQuestionResponseTracking
        sources.append(("wb", model, "feedback_id" if kind == "reviews" else "question_id",
                        "review_created_at" if kind == "reviews" else "question_created_at"))
    if marketplace in ("all", "yandex"):
        model = YandexReviewResponseTracking if kind == "reviews" else YandexQuestionResponseTracking
        sources.append(("yandex", model, "feedback_id" if kind == "reviews" else "question_id",
                        "review_created_at" if kind == "reviews" else "question_created_at"))

    def _duration_minutes(start_dt, end_dt):
        if start_dt is None or end_dt is None:
            return None
        minutes = (end_dt - start_dt).total_seconds() / 60.0
        if minutes < 0 or minutes > 365 * 24 * 60:
            return None
        return round(float(minutes), 2)

    records = []
    for platform, model, id_field, time_field in sources:
        # Do not materialize other tenants: get_db applies PostgreSQL tenant RLS.
        q = db.query(model)
        created_column = getattr(model, time_field)
        if date_from:
            q = q.filter(created_column >= datetime.combine(date_from, time.min))
        if date_to:
            q = q.filter(created_column < datetime.combine(date_to + timedelta(days=1), time.min))
        rows = q.all()
        valid_ids = None
        if platform == "yandex" and kind == "reviews" and rows:
            # Only substantive reviews: text / advantages / disadvantages / media / tags.
            keys = [(r.business_id, str(r.feedback_id)) for r in rows]
            valid_ids = set()
            for i in range(0, len(keys), 300):
                part = keys[i:i+300]
                from sqlalchemy import tuple_
                matching = db.query(YandexReview).filter(
                    tuple_(YandexReview.business_id, YandexReview.feedback_id).in_(part)
                ).all()
                for review in matching:
                    raw = review.raw_data if isinstance(review.raw_data, dict) else {}
                    desc = raw.get("description") or {}
                    media = raw.get("media") or {}
                    substantive = any(str(v or "").strip() for v in (
                        review.comment, review.advantages, review.disadvantages,
                        desc.get("tags"), desc.get("pros"), desc.get("cons"),
                    )) or bool(review.photos or review.videos or media.get("photos") or media.get("videos"))
                    if substantive:
                        valid_ids.add((review.business_id, str(review.feedback_id)))
        for r in rows:
            if valid_ids is not None and (r.business_id, str(r.feedback_id)) not in valid_ids:
                continue
            created = getattr(r, time_field)
            first_seen = r.first_seen_unanswered_at
            left_unanswered = r.left_unanswered_at
            monitor_minutes = _duration_minutes(first_seen, left_unanswered)
            active_now = (left_unanswered is None and r.resolution in (None, "", "pending"))
            active_minutes = _duration_minutes(first_seen, datetime.utcnow()) if active_now else None
            valid_answer = (
                r.resolution == "answered"
                and not r.baseline
                and first_seen is not None
                and left_unanswered is not None
                and monitor_minutes is not None
            )
            records.append({
                "marketplace": platform,
                "kind": kind,
                "id": str(getattr(r, id_field)),
                "business_id": getattr(r, "business_id", None),
                "created_at": created.isoformat() if created else None,
                "monitored_from_at": first_seen.isoformat() if first_seen else None,
                "answered_detected_at": left_unanswered.isoformat() if left_unanswered else None,
                "_created": created,
                "_entered": first_seen,
                "_left": left_unanswered,
                "resolution": r.resolution,
                "baseline": bool(r.baseline),
                "last_seen_unanswered_at": r.last_seen_unanswered_at.isoformat() if r.last_seen_unanswered_at else None,
                "left_unanswered_at": left_unanswered.isoformat() if left_unanswered else None,
                "response_minutes": monitor_minutes if valid_answer else None,
                # Dashboard combined elapsed timer: completed answers + live unanswered.
                # An unresolved exit (pending verification) has no running timer.
                "monitor_elapsed_minutes": monitor_minutes if valid_answer else active_minutes,
                "_valid": valid_answer,
            })

    # Active WB reviews/questions use NULL resolution while they remain in the queue.
    # Include old "pending" values only when still active, for compatibility.
    def is_active(row):
        return (row["_left"] is None and row["resolution"] in (None, "", "pending"))

    def is_verifying(row):
        return (row["_left"] is not None and row["resolution"] == "pending")

    # Current queue age changes while the item remains unanswered. We measure it
    # from the moment the review/question entered monitoring, not from its
    # original marketplace creation timestamp.
    now_utc = datetime.utcnow()
    active_records = [r for r in records if is_active(r)]
    queue_ages = []
    for r in active_records:
        start = r["_entered"]
        if start is not None:
            queue_ages.append(max(0.0, (now_utc - start).total_seconds() / 60.0))
    queue_ranges = ((0, 720), (720, 1440), (1440, 2880), (2880, float("inf")))
    queue_distribution = [
        {"label": label, "count": sum(lo <= v < hi for v in queue_ages)}
        for (lo, hi), label in zip(queue_ranges, ("0–12 ч", "12–24 ч", "24–48 ч", "48 ч и более"))
    ]

    measured = [r for r in records if r["_valid"]]
    values = [r["response_minutes"] for r in measured]
    # Unified operational KPI: one observation per item. A completed response
    # freezes its timer; an active unanswered item continues accumulating time.
    # Exclude completed baseline items because their original starting point
    # predates monitoring. Active baseline items remain part of today's queue.
    included = [r for r in records if r["monitor_elapsed_minutes"] is not None]
    live_values = [r["monitor_elapsed_minutes"] for r in included]
    buckets = defaultdict(list)
    for r in included:
        bucket_dt = r["_entered"] or r["_created"]
        if bucket_dt is None:
            continue
        key = (bucket_dt.strftime("%Y-%m-%d") if granularity == "day"
               else bucket_dt.strftime("%Y-%m"))
        buckets[key].append(r)
    trend = [
        {"period": k,
         "answered": sum(x["_valid"] for x in v),
         "active": sum(is_active(x) for x in v),
         "timers": len(v),
         "average_minutes": round(sum(x["monitor_elapsed_minutes"] for x in v) / len(v), 1),
         "median_minutes": round(median(x["monitor_elapsed_minutes"] for x in v), 1)}
        for k, v in sorted(buckets.items())
    ]
    # Historical completed responses form a separate, stable series. Do not
    # mix them into current waiting times or their denominator.
    completed_buckets = defaultdict(list)
    for r in measured:
        bucket_dt = r["_entered"] or r["_created"]
        if bucket_dt is None:
            continue
        key = (bucket_dt.strftime("%Y-%m-%d") if granularity == "day"
               else bucket_dt.strftime("%Y-%m"))
        completed_buckets[key].append(r["response_minutes"])
    completed_trend = [
        {"period": k, "answered": len(v), "active": 0, "timers": len(v),
         "average_minutes": round(sum(v) / len(v), 1),
         "median_minutes": round(median(v), 1)}
        for k, v in sorted(completed_buckets.items())
    ]
    # Count statuses before removing internal keys from paginated records.
    # `page` contains references to the same dicts as `records`.
    pending_verification_count = sum(is_verifying(r) for r in records)
    pending_tracked_count = sum(is_active(r) or is_verifying(r) for r in records)

    records.sort(key=lambda r: (r["_entered"] or r["_created"] or datetime.min, r["marketplace"], r["id"]), reverse=True)
    page = records[offset:offset+limit]
    for r in page:
        r.pop("_created", None)
        r.pop("_entered", None)
        r.pop("_left", None)
        r.pop("_valid", None)

    return {
        "status": "ok", "marketplace": marketplace, "kind": kind,
        "granularity": granularity, "date_from": date_from, "date_to": date_to,
        "calculation_mode": "entered_monitor_to_first_confirmed_answer",
        "period_basis": "entered_monitoring_at",
        "average_minutes": round(sum(values)/len(values), 1) if values else None,
        "average_human": _human_minutes(sum(values)/len(values)) if values else None,
        "median_minutes": round(median(values), 1) if values else None,
        "answered_with_timing": len(measured),
        "timers_measured": len(live_values),
        "timers_mode": "completed_and_active_unanswered",
        "timers_average_minutes": round(sum(live_values)/len(live_values), 1) if live_values else None,
        "timers_median_minutes": round(median(live_values), 1) if live_values else None,
        "active_unanswered": len(active_records),
        "queue_age_median_minutes": round(median(queue_ages), 1) if queue_ages else None,
        "queue_age_average_minutes": round(sum(queue_ages)/len(queue_ages), 1) if queue_ages else None,
        "queue_age_max_minutes": round(max(queue_ages), 1) if queue_ages else None,
        "queue_age_measured": len(queue_ages),
        "queue_age_distribution": queue_distribution,
        "pending_verification": pending_verification_count,
        "pending_tracked": pending_tracked_count,
        "answered_observed": sum(r["resolution"] == "answered" for r in records),
        "baseline_records": sum(r["baseline"] for r in records),
        "tracked_total": len(records), "trend": trend, "completed_trend": completed_trend,
        "items": page, "items_total": len(records), "limit": limit, "offset": offset,
        "notes": [
            "The chart and progress bars combine confirmed completed timers and currently unanswered running timers; each item has one weight.",
            "Completed response times are measured from the moment an item entered monitoring until the first confirmed answer.",
            "Trends are grouped by the date the item entered monitoring (fallback: original creation date).",
            "Only substantive Yandex reviews are included; rating-only reviews are excluded.",
            "active_unanswered includes active WB records with NULL resolution; pending_verification counts records waiting for final confirmation.",
            "Queue ages are calculated from the moment an item entered monitoring until this API request, including baseline items.",
            "Tracked unanswered counts can differ from the marketplace-wide queue if monitoring coverage differs.",
        ],
    }
