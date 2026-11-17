"""Sign rule for WB detail fields stored as positive magnitudes.

When document type is present, it is authoritative; older rows fall back to
seller operation. Field names and aliases must be static application strings.
"""


def sign_condition(alias: str = '') -> str:
    prefix = f'{alias}.' if alias else ''
    doc = f"lower(btrim(coalesce({prefix}doc_type, '')))"
    operation = f"lower(btrim(coalesce({prefix}operation, '')))"
    return f"(CASE WHEN {doc} <> '' THEN {doc} = 'возврат' ELSE {operation} = 'возврат' END)"


def signed(field: str, alias: str = '') -> str:
    if field not in ('retail', 'for_pay'):
        raise ValueError('Unsupported WB financial field')
    qualified = f'{alias}.{field}' if alias else field
    return f'(CASE WHEN {sign_condition(alias)} THEN -{qualified} ELSE {qualified} END)'


def ensure_wb_finance_doc_type_schema():
    """Add source document type once; never touch existing amounts or rows."""
    from sqlalchemy import text
    from backend.database import engine
    with engine.begin() as connection:
        for table in ('wb_finance_daily_entries', 'wb_finance_entries'):
            # IF EXISTS lets startup proceed for databases without legacy weekly tables.
            connection.execute(text(f'ALTER TABLE IF EXISTS {table} ADD COLUMN IF NOT EXISTS doc_type varchar(100)'))
