from sqlalchemy import text

from backend.database import engine


def ensure_stock_history_warehouse_id_schema() -> None:
    """
    Приводит stock_history.warehouse_id к текстовому типу.

    В текущей БД колонка исторически создана как integer, но приложение
    уже использует строковые идентификаторы складов. Ozon FBO формирует
    технический идентификатор вида OZON_FBO_<warehouse_name>, поэтому
    integer здесь принципиально недостаточен.
    """
    with engine.begin() as conn:
        conn.execute(
            text(
                """
                ALTER TABLE stock_history
                ALTER COLUMN warehouse_id TYPE VARCHAR(255)
                USING warehouse_id::text
                """
            )
        )
