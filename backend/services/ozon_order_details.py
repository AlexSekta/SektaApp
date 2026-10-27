"""Reusable read-only Ozon posting detail fetcher and redacted price comparator."""
from decimal import Decimal, InvalidOperation


DETAIL_PATHS = {"fbo": "/v2/posting/fbo/get", "fbs": "/v3/posting/fbs/get"}


def get_posting_details(client, scheme: str, posting_number: str) -> dict:
    """Fetch an individual posting; never return buyer personal data to callers."""
    if scheme not in DETAIL_PATHS:
        raise ValueError("scheme must be fbo or fbs")
    number = str(posting_number).strip()
    if not number or len(number) > 100:
        raise ValueError("invalid posting_number")
    payload = {"posting_number": number, "with": {"analytics_data": False, "financial_data": True}}
    return client.post_raw(DETAIL_PATHS[scheme], payload)


def decimal_or_none(value):
    if isinstance(value, dict):
        value = value.get("amount")
    if value is None or value == "":
        return None
    try:
        return Decimal(str(value))
    except (TypeError, InvalidOperation):
        return None


def str_money(value):
    return str(value) if value is not None else None


def redact_prices(raw: dict, scheme: str) -> dict:
    status_code = raw.get("status_code")
    body = raw.get("body")
    if status_code != 200 or not isinstance(body, dict):
        return {"http_status": status_code, "status": "error", "error_kind": (
            (body.get("code") if isinstance(body, dict) else None) or "API error"),
            "note": "Response body omitted to avoid personal data leakage"}
    posting = body.get("result") if isinstance(body.get("result"), dict) else body
    financial = (posting.get("financial_data") or {}).get("products") or []
    products = posting.get("products") or []
    rows = []
    for idx, fp in enumerate(financial):
        if not isinstance(fp, dict):
            continue
        customer = decimal_or_none(fp.get("customer_price"))
        seller = decimal_or_none(fp.get("price"))
        old = decimal_or_none(fp.get("old_price"))
        unit = next((p for p in products if str(p.get("sku")) == str(fp.get("sku")) and fp.get("sku") is not None), None)
        unit = unit or (products[idx] if idx < len(products) and isinstance(products[idx], dict) else {})
        quantity = decimal_or_none(fp.get("quantity"))
        if quantity is None:
            quantity = decimal_or_none(unit.get("quantity"))
        discount_pct = (Decimal(100) * (seller - customer) / seller).quantize(Decimal("0.01")) if seller and customer is not None else None
        rows.append({
            "sku": fp.get("sku") or unit.get("sku"),
            "offer_id": fp.get("offer_id") or unit.get("offer_id"),
            "quantity": str_money(quantity),
            "old_price": str_money(old),
            "price": str_money(seller),
            "customer_price": str_money(customer),
            "total_discount_value": str_money(decimal_or_none(fp.get("total_discount_value"))),
            "payout": str_money(decimal_or_none(fp.get("payout"))),
            "customer_price_to_price_pct": str_money((customer / seller * 100).quantize(Decimal("0.01"))) if seller and customer is not None else None,
            "price_minus_customer_price_pct": str_money(discount_pct),
            "present_financial_fields": sorted(fp.keys()),
        })
    return {
        "status": "ok", "http_status": status_code, "scheme": scheme,
        "posting_number": posting.get("posting_number"),
        "status_name": posting.get("status"),
        "created_at": posting.get("created_at"),
        "in_process_at": posting.get("in_process_at"),
        "products": rows,
        "financial_rows": len(rows),
        "note": "customer_price is not necessarily the chart soldRevenue price; comparison does not prove SPP source or rate"
    }
