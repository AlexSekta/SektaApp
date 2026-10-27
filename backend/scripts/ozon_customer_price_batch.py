"""Read-only batch reconciliation of Ozon posting customer_price in Europe/Moscow day.

Run from repository root: python -m backend.scripts.ozon_customer_price_batch --day 2026-10-12
No PII or raw API responses are written. Resumes from per-posting safe checkpoints.
"""

import argparse
import json
import sys
import time
from collections import defaultdict
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation
from pathlib import Path
from zoneinfo import ZoneInfo

from backend.database import SessionLocal
from backend.models.auth import Organization
from backend.services.marketplace_clients import get_ozon_client
from backend.services.ozon_order_details import get_posting_details, redact_prices

MOSCOW = ZoneInfo("Europe/Moscow")
REFERENCE = {"2026-10-12": Decimal("1512469"), "2026-10-11": Decimal("1626270")}


def number(value):
    try:
        return Decimal(str(value)) if value is not None and value != "" else None
    except (InvalidOperation, ValueError, TypeError):
        return None


def money(value):
    return str(value.quantize(Decimal("0.01")))


def stamp(value):
    if not value:
        return None
    try:
        return (
            datetime.fromisoformat(str(value).replace("Z", "+00:00"))
            .astimezone(MOSCOW)
            .date()
            .isoformat()
        )
    except (ValueError, TypeError):
        return None


def listing(client, scheme, since, until):
    cursor = ""
    pages = 0
    found = []
    seen = set()
    while True:
        pages += 1
        if pages > 100:
            raise RuntimeError("Safety page limit exceeded")
        call = (
            client.list_fbo_postings_raw
            if scheme == "fbo"
            else client.list_fbs_postings_raw
        )
        raw = call(since=since, to=until, cursor=cursor, limit=100)
        if raw.get("status_code") != 200:
            raise RuntimeError(f'{scheme} list HTTP {raw.get("status_code")}')
        body = raw.get("body") or {}
        items = body.get("postings") or []
        found.extend(items)
        if not body.get("has_next"):
            return found, pages
        next_cursor = body.get("cursor") or ""
        if not next_cursor or next_cursor in seen:
            raise RuntimeError("Cursor pagination failed")
        seen.add(next_cursor)
        cursor = next_cursor


def aggregate(cache, requested_date):
    total = {
        "fbo": defaultdict(
            lambda: {
                "postings": 0,
                "units": Decimal(0),
                "customer_sum": Decimal(0),
                "seller_sum": Decimal(0),
                "missing_customer_units": 0,
                "missing_quantity": 0,
            }
        ),
        "fbs": defaultdict(
            lambda: {
                "postings": 0,
                "units": Decimal(0),
                "customer_sum": Decimal(0),
                "seller_sum": Decimal(0),
                "missing_customer_units": 0,
                "missing_quantity": 0,
            }
        ),
    }
    date_coverage = defaultdict(int)
    failed = []
    for key, p in cache.items():
        if p.get("status") != "ok":
            failed.append(
                {"scheme": p.get("scheme"), "http_status": p.get("http_status")}
            )
            continue
        scheme = p["scheme"]
        dt = stamp(p.get("created_at") if scheme == "fbo" else p.get("in_process_at"))
        date_coverage[f'{scheme}:{dt or "unknown"}'] += 1
        # FBS in_process_at is NOT proven to be customer order creation time.
        if dt != requested_date:
            continue
        status = (
            "cancelled"
            if (p.get("status_name") or "").lower() in ("cancelled", "canceled")
            else "not_cancelled"
        )
        group = total[scheme][status]
        group["postings"] += 1
        for item in p.get("products") or []:
            qty = number(item.get("quantity"))
            if qty is None or qty <= 0:
                group["missing_quantity"] += 1
                continue
            group["units"] += qty
            cp, sp = number(item.get("customer_price")), number(item.get("price"))
            if cp is None:
                group["missing_customer_units"] += int(qty)
            else:
                group["customer_sum"] += cp * qty
            if sp is not None:
                group["seller_sum"] += sp * qty
    result = {}
    for scheme, groups in total.items():
        result[scheme] = {
            status: {
                k: (money(v) if isinstance(v, Decimal) else v) for k, v in d.items()
            }
            for status, d in groups.items()
        }
    both = sum(
        (
            groups.get("not_cancelled", {}).get("customer_sum", Decimal(0))
            for groups in total.values()
        ),
        Decimal(0),
    )
    all_statuses = sum(
        (g["customer_sum"] for groups in total.values() for g in groups.values()),
        Decimal(0),
    )
    ref = REFERENCE.get(requested_date)
    return {
        "by_scheme_and_status": result,
        "customer_price_not_cancelled": money(both),
        "customer_price_all_statuses": money(all_statuses),
        "reference_soldRevenue": money(ref) if ref else None,
        "difference_not_cancelled": money(both - ref) if ref is not None else None,
        "difference_all_statuses": (
            money(all_statuses - ref) if ref is not None else None
        ),
        "date_field_used": {
            "fbo": "created_at",
            "fbs": "in_process_at (NOT verified order creation date)",
        },
        "dates_seen": dict(sorted(date_coverage.items())),
        "detail_failures_count": len(failed),
        "detail_failure_http_statuses": sorted(
            set(str(x["http_status"]) for x in failed)
        ),
        "note": "Figures are diagnostic, not certified soldRevenue; FBS date proxy and missing prices can affect comparison.",
    }


def atomic_save(path, data):
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(path)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--day", type=date.fromisoformat, default=date(2026, 10, 12))
    parser.add_argument(
        "--delay", type=float, default=0.3, help="Delay seconds between detail requests"
    )
    parser.add_argument(
        "--max-items", type=int, default=0, help="For initial smoke test; 0 means all"
    )
    args = parser.parse_args()
    start_local = datetime.combine(args.day, datetime.min.time(), tzinfo=MOSCOW)
    end_local = start_local + timedelta(days=1)
    since = (
        start_local.astimezone(timezone.utc)
        .isoformat(timespec="milliseconds")
        .replace("+00:00", "Z")
    )
    until = (
        (end_local - timedelta(milliseconds=1))
        .astimezone(timezone.utc)
        .isoformat(timespec="milliseconds")
        .replace("+00:00", "Z")
    )
    print(f"Moscow day: {args.day}, UTC request: {since} .. {until}", flush=True)
    out = Path("ozon_price_diagnostic")
    out.mkdir(exist_ok=True)
    checkpoint = out / f"checkpoint_{args.day.isoformat()}.json"
    cache = (
        json.loads(checkpoint.read_text(encoding="utf-8"))
        if checkpoint.exists()
        else {}
    )
    db = SessionLocal()
    try:
        client = get_ozon_client(db)
        posts = []
        counts = {}
        for scheme in ("fbo", "fbs"):
            found, pages = listing(client, scheme, since, until)
            counts[scheme] = {"postings": len(found), "pages": pages}
            posts.extend(
                (scheme, p["posting_number"])
                for p in found
                if isinstance(p, dict) and p.get("posting_number")
            )
        posts = list(dict.fromkeys(posts))
        print(f"Lists: {counts}; unique postings to inspect: {len(posts)}", flush=True)
        processed = 0
        for scheme, posting in posts:
            key = f"{scheme}:{posting}"
            if key in cache and cache[key].get("status") == "ok":
                continue
            if args.max_items and processed >= args.max_items:
                break
            result = None
            for attempt in range(3):
                try:
                    result = redact_prices(
                        get_posting_details(client, scheme, posting), scheme
                    )
                    break
                except Exception as exc:
                    if attempt == 2:
                        result = {"status": "error", "error_kind": type(exc).__name__}
                    else:
                        time.sleep(2 * (attempt + 1))
            # Only allowlisted, redacted data; never store the raw Ozon API response.
            cache[key] = {"scheme": scheme, **result}
            processed += 1
            if processed % 20 == 0:
                atomic_save(checkpoint, cache)
                print(
                    f"Fetched new details: {processed}; cached: {len(cache)} / {len(posts)}",
                    flush=True,
                )
            time.sleep(max(args.delay, 0.1))
        atomic_save(checkpoint, cache)
        summary = {
            "date": args.day.isoformat(),
            "timezone": "Europe/Moscow",
            "utc_interval": {"since_inclusive": since, "until_inclusive": until},
            "listing": counts,
            "expected_unique_postings": len(posts),
            "details_cached": len(cache),
            "complete": all(
                f"{s}:{n}" in cache and cache[f"{s}:{n}"].get("status") == "ok"
                for s, n in posts
            ),
            **aggregate(
                {
                    f"{s}:{n}": cache[f"{s}:{n}"]
                    for s, n in posts
                    if f"{s}:{n}" in cache
                },
                args.day.isoformat(),
            ),
        }
        summary_path = out / f"summary_{args.day.isoformat()}.json"
        atomic_save(summary_path, summary)
        print(json.dumps(summary, ensure_ascii=False, indent=2), flush=True)
        print(f"Summary file: {summary_path.resolve()}", flush=True)
    finally:
        db.close()


if __name__ == "__main__":
    main()
