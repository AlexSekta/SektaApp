"""Read-only WB statistics probe. Never persists API response or exposes credentials."""
from datetime import date, timedelta
import requests
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session
from backend.dependencies import get_db
from backend.services.marketplace_clients import get_wb_client

router = APIRouter(prefix="/analytics", tags=["Аналитика"])
BASE_URL = "https://statistics-api.wildberries.ru"

@router.get("/wb-sales-probe")
def wb_sales_probe(
    day: date = Query(..., description="Дата по московскому времени, YYYY-MM-DD"),
    kind: str = Query("orders", pattern="^(orders|sales)$"),
    db: Session = Depends(get_db),
):
    """One-day read-only diagnostic. Call orders/sales separately due to WB rate limits."""
    if day > date.today() or day < date.today() - timedelta(days=89):
        raise HTTPException(400, "Выберите дату в пределах последних 90 дней, не в будущем")
    try:
        client = get_wb_client(db)
        response = requests.get(
            f"{BASE_URL}/api/v1/supplier/{kind}",
            headers=client.headers,
            params={"dateFrom": day.isoformat(), "flag": 1},
            timeout=60,
        )
    except requests.RequestException:
        raise HTTPException(502, "Ошибка соединения с API статистики WB") from None
    except RuntimeError as exc:
        raise HTTPException(400, str(exc)) from None
    if response.status_code in (401, 403):
        raise HTTPException(403, "WB не разрешил доступ. Проверьте категорию API-ключа «Статистика»")
    if response.status_code == 429:
        raise HTTPException(429, "Превышен лимит WB. Не повторяйте запрос сразу")
    if response.status_code != 200:
        raise HTTPException(502, f"API статистики WB вернул HTTP {response.status_code}")
    try:
        rows = response.json()
    except ValueError:
        raise HTTPException(502, "WB вернул некорректный JSON") from None
    if not isinstance(rows, list):
        raise HTTPException(502, "WB вернул неожиданный формат ответа")
    def number(value):
        try: return float(value) if value is not None else 0.0
        except (TypeError, ValueError): return 0.0
    # Diagnostic sums are NOT a validated dashboard revenue formula.
    return {
        "status": "ok", "source": "WB Statistics API", "kind": kind,
        "day": day.isoformat(), "rows_count": len(rows),
        "canceled_count": sum(bool(r.get("isCancel")) for r in rows if isinstance(r, dict)),
        "return_count": sum(str(r.get("saleID") or "").startswith("R") for r in rows if isinstance(r, dict)),
        "sample_fields": sorted(rows[0].keys()) if rows and isinstance(rows[0], dict) else [],
        "diagnostic_sums": {
            "totalPrice": round(sum(number(r.get("totalPrice")) for r in rows if isinstance(r, dict)), 2),
            "finishedPrice": round(sum(number(r.get("finishedPrice")) for r in rows if isinstance(r, dict)), 2),
            "priceWithDisc": round(sum(number(r.get("priceWithDisc")) for r in rows if isinstance(r, dict)), 2),
            "forPay": round(sum(number(r.get("forPay")) for r in rows if isinstance(r, dict)), 2),
        },
        "note": "Диагностика без записи в БД. Суммы предварительные, не используйте их как продажи до сверки с Excel WB.",
    }
