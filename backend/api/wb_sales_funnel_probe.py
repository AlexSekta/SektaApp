"""Read-only WB sales funnel v3 diagnostic; no database writes or token exposure."""
from datetime import date, timedelta

import requests
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from backend.dependencies import get_db
from backend.services.marketplace_clients import get_wb_client
from backend.services.marketplace_credentials import MarketplaceNotConfiguredError

router = APIRouter(prefix="/analytics", tags=["Аналитика"])
URL = "https://seller-analytics-api.wildberries.ru/api/analytics/v3/sales-funnel/products"


def _numbers(products):
    # Preserve distinction between missing metrics and zero-valued metrics.
    result = {}
    for item in products:
        if not isinstance(item, dict):
            continue
        candidates = [item]
        statistics = item.get("statistic")
        if isinstance(statistics, dict):
            selected = statistics.get("selected")
            if isinstance(selected, dict):
                candidates.insert(0, selected)
        for source in candidates:
            for key, value in source.items():
                if key in ("orderCount", "orderSum", "buyoutCount", "buyoutSum", "cancelCount", "cancelSum") and isinstance(value, (int, float)) and not isinstance(value, bool):
                    metric = result.setdefault(key, {"sum": 0, "present": 0})
                    metric["sum"] += value
                    metric["present"] += 1
    return result


@router.get("/wb-sales-funnel-probe")
def probe_wb_sales_funnel(
    day: date = Query(..., description="День в формате YYYY-MM-DD"),
    offset: int = Query(0, ge=0, description="Смещение карточек WB"),
    limit: int = Query(1000, ge=1, le=1000),
    db: Session = Depends(get_db),
):
    """Compare one day's funnel metrics with Seller portal Excel, one page per call."""
    if day > date.today() or day < date.today() - timedelta(days=364):
        raise HTTPException(400, "Дата должна быть в пределах последних 365 дней")
    try:
        wb = get_wb_client(db)
    except (MarketplaceNotConfiguredError, RuntimeError):
        raise HTTPException(400, "Подключение WB не настроено") from None
    payload = {
        "selectedPeriod": {"start": day.isoformat(), "end": day.isoformat()},
        "nmIds": [], "brandNames": [], "subjectIds": [], "tagIds": [],
        "skipDeletedNm": False,
        "limit": limit, "offset": offset,
    }
    try:
        response = requests.post(URL, headers=wb.headers, json=payload, timeout=90)
    except requests.RequestException:
        raise HTTPException(502, "Нет ответа от WB Analytics API") from None
    if response.status_code in (401, 403):
        raise HTTPException(403, "WB не разрешил доступ к категории API «Аналитика»")
    if response.status_code == 402:
        raise HTTPException(402, "WB требует доступ/подписку для этого отчёта")
    if response.status_code == 429:
        raise HTTPException(429, "Лимит запросов WB. Повторите позже")
    if response.status_code != 200:
        raise HTTPException(502, f"WB Analytics API вернул HTTP {response.status_code}")
    try:
        body = response.json()
    except ValueError:
        raise HTTPException(502, "Некорректный JSON от WB") from None
    if not isinstance(body, dict):
        raise HTTPException(502, "Неожиданная структура WB: нет объекта ответа")
    data = body.get("data", body)
    if not isinstance(data, dict):
        raise HTTPException(502, "Неожиданная структура WB: нет data")
    products = data.get("products")
    if not isinstance(products, list):
        raise HTTPException(502, "Неожиданная структура WB: нет массива products")
    first = next((p for p in products if isinstance(p, dict)), {})
    selected = (first.get("statistic") or {}).get("selected") if isinstance(first.get("statistic"), dict) else {}
    return {
        "status": "ok", "source": "WB Analytics Sales Funnel v3", "day": day.isoformat(),
        "page": {"offset": offset, "limit": limit, "returned": len(products), "may_have_more": len(products) == limit, "next_offset": offset + len(products) if len(products) == limit else None},
        "currency": data.get("currency"),
        "metrics": _numbers(products),
        "sample_product_fields": sorted(first),
        "sample_selected_fields": sorted(selected) if isinstance(selected, dict) else [],
        "note": "Суммы относятся только к этой странице. При наличии следующей страницы повторите запрос через >=20 секунд. Ничего не записывается в БД.",
    }
