from datetime import date, datetime, timedelta
from threading import RLock

from sqlalchemy import func
from sqlalchemy.orm import Session

from backend.database import Base, engine
from backend.logging_config import get_logger
from backend.models.ozon_sales_daily import OzonSalesDaily
from backend.services.marketplace_clients import get_ozon_client

logger = get_logger("ozon_sales_sync")

SYNC_LOCK = RLock()
DEFAULT_HISTORY_DAYS = 90


def ensure_ozon_sales_tables() -> None:
    Base.metadata.create_all(
        bind=engine,
        tables=[OzonSalesDaily.__table__],
    )

    # This runs during backend startup before the scheduler switches to
    # marketplace_app. It makes the new table tenant-safe and readable by
    # the application role without changing the existing tenant migration.
    with engine.begin() as conn:
        conn.exec_driver_sql(
            "GRANT SELECT, INSERT, UPDATE, DELETE "
            "ON TABLE ozon_sales_daily TO marketplace_app"
        )
        conn.exec_driver_sql(
            "GRANT USAGE, SELECT, UPDATE "
            "ON SEQUENCE ozon_sales_daily_id_seq TO marketplace_app"
        )
        conn.exec_driver_sql(
            "ALTER TABLE ozon_sales_daily ENABLE ROW LEVEL SECURITY"
        )
        conn.exec_driver_sql(
            "ALTER TABLE ozon_sales_daily FORCE ROW LEVEL SECURITY"
        )
        # Новые аналитические метрики Ozon добавляются безопасно к уже
        # существующей таблице: create_all() сам существующие колонки не
        # мигрирует. Для старых строк NULL означает, что метрика ещё не
        # была получена/недоступна для API-ключа.
        conn.exec_driver_sql(
            "ALTER TABLE ozon_sales_daily "
            "ADD COLUMN IF NOT EXISTS delivered_units INTEGER"
        )
        conn.exec_driver_sql(
            "ALTER TABLE ozon_sales_daily "
            "ADD COLUMN IF NOT EXISTS returns INTEGER"
        )
        conn.exec_driver_sql(
            "ALTER TABLE ozon_sales_daily "
            "ADD COLUMN IF NOT EXISTS cancellations INTEGER"
        )
        conn.exec_driver_sql(
            "DROP POLICY IF EXISTS tenant_isolation ON ozon_sales_daily"
        )
        conn.exec_driver_sql(
            """
            CREATE POLICY tenant_isolation
            ON ozon_sales_daily
            USING (
                organization_id =
                current_setting('app.organization_id', true)::integer
            )
            WITH CHECK (
                organization_id =
                current_setting('app.organization_id', true)::integer
            )
            """
        )


def _dimension_date(row: dict):
    for item in row.get("dimensions") or []:
        value = item.get("id")
        if not value:
            continue
        try:
            return date.fromisoformat(str(value)[:10])
        except ValueError:
            continue
    return None


def sync_ozon_sales(
    db: Session,
    organization_id: int,
    history_days: int = DEFAULT_HISTORY_DAYS,
    *,
    date_from_override: date | None = None,
    date_to_override: date | None = None,
) -> dict:
    history_days = max(1, min(int(history_days), 90))
    if (date_from_override is None) != (date_to_override is None):
        raise ValueError("Both override dates are required")
    date_to = date_to_override if date_to_override is not None else date.today()
    date_from = date_from_override if date_from_override is not None else date_to - timedelta(days=history_days - 1)
    if date_to < date_from or (date_to - date_from).days >= 90:
        raise ValueError("Ozon analytics period must contain 1 to 90 days")

    with SYNC_LOCK:
        started_at = datetime.utcnow()
        client = get_ozon_client(db)

        core_metrics = ["revenue", "ordered_units"]
        advanced_metrics = ["delivered_units", "returns", "cancellations"]
        requested_metrics = core_metrics + advanced_metrics
        metrics_used = list(requested_metrics)
        advanced_metrics_available = True

        try:
            result = client.get_analytics_data(
                date_from=date_from.isoformat(),
                date_to=date_to.isoformat(),
                metrics=requested_metrics,
                dimensions=["day"],
                filters=[],
                sort=[{"key": "revenue", "order": "DESC"}],
                limit=1000,
                offset=0,
            )
        except Exception as error:
            # returns/cancellations/delivered_units могут требовать Premium Plus.
            # Не ломаем уже работающую синхронизацию базовых продаж: при отказе
            # Ozon повторяем запрос только с двумя базовыми метриками.
            status_code = getattr(error, "status_code", None)
            if status_code not in (400, 403):
                raise

            advanced_metrics_available = False
            metrics_used = list(core_metrics)
            logger.warning(
                "OZON_SALES_ADVANCED_METRICS_UNAVAILABLE | "
                "organization_id=%s status_code=%s error=%s",
                organization_id,
                status_code,
                getattr(error, "message", str(error)),
            )
            result = client.get_analytics_data(
                date_from=date_from.isoformat(),
                date_to=date_to.isoformat(),
                metrics=core_metrics,
                dimensions=["day"],
                filters=[],
                sort=[{"key": "revenue", "order": "DESC"}],
                limit=1000,
                offset=0,
            )

        analytics_result = result.get("result") or {}
        rows = analytics_result.get("data") or []

        saved = 0
        for row in rows:
            sale_date = _dimension_date(row)
            metric_values = row.get("metrics") or []
            if sale_date is None or len(metric_values) < len(metrics_used):
                continue

            revenue = float(metric_values[0] or 0)
            ordered_units = int(round(float(metric_values[1] or 0)))

            delivered_units = None
            returns = None
            cancellations = None
            if advanced_metrics_available and len(metric_values) >= 5:
                delivered_units = int(round(float(metric_values[2] or 0)))
                returns = int(round(float(metric_values[3] or 0)))
                cancellations = int(round(float(metric_values[4] or 0)))

            item = (
                db.query(OzonSalesDaily)
                .filter(
                    OzonSalesDaily.organization_id == organization_id,
                    OzonSalesDaily.sale_date == sale_date,
                )
                .one_or_none()
            )

            if item is None:
                item = OzonSalesDaily(
                    organization_id=organization_id,
                    sale_date=sale_date,
                    revenue=revenue,
                    ordered_units=ordered_units,
                    delivered_units=delivered_units,
                    returns=returns,
                    cancellations=cancellations,
                    raw_data=row,
                )
                db.add(item)
            else:
                item.revenue = revenue
                item.ordered_units = ordered_units
                item.delivered_units = delivered_units
                item.returns = returns
                item.cancellations = cancellations
                item.raw_data = row
                item.last_synced_at = datetime.utcnow()

            saved += 1

        db.commit()

        total_days = int(
            db.query(func.count(OzonSalesDaily.id))
            .filter(OzonSalesDaily.organization_id == organization_id)
            .scalar()
            or 0
        )

        logger.info(
            "OZON_SALES_SYNC_OK | organization_id=%s date_from=%s "
            "date_to=%s rows_received=%s rows_saved=%s total_days=%s "
            "metrics=%s advanced_available=%s",
            organization_id,
            date_from,
            date_to,
            len(rows),
            saved,
            total_days,
            metrics_used,
            advanced_metrics_available,
        )

        return {
            "status": "ok",
            "date_from": date_from.isoformat(),
            "date_to": date_to.isoformat(),
            "history_days": history_days,
            "rows_received": len(rows),
            "rows_saved": saved,
            "total_days": total_days,
            "metrics_requested": requested_metrics,
            "metrics_used": metrics_used,
            "advanced_metrics_available": advanced_metrics_available,
            "timestamp": result.get("timestamp"),
            "started_at": started_at.isoformat(),
            "finished_at": datetime.utcnow().isoformat(),
        }
