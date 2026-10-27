from sqlalchemy import text
from backend.database import Base, engine
from backend.models.wb_sales_daily import WBSalesDaily

def ensure_wb_sales_table():
    Base.metadata.create_all(bind=engine, tables=[WBSalesDaily.__table__])
    with engine.begin() as conn:
        conn.execute(text('GRANT SELECT, INSERT, UPDATE, DELETE ON wb_sales_daily TO marketplace_app'))
        conn.execute(text('GRANT USAGE, SELECT, UPDATE ON SEQUENCE wb_sales_daily_id_seq TO marketplace_app'))
        conn.execute(text('ALTER TABLE wb_sales_daily ENABLE ROW LEVEL SECURITY'))
        conn.execute(text('ALTER TABLE wb_sales_daily FORCE ROW LEVEL SECURITY'))
        conn.execute(text('DROP POLICY IF EXISTS tenant_isolation ON wb_sales_daily'))
        conn.execute(text("CREATE POLICY tenant_isolation ON wb_sales_daily USING (organization_id = current_setting('app.organization_id', true)::integer) WITH CHECK (organization_id = current_setting('app.organization_id', true)::integer)"))
