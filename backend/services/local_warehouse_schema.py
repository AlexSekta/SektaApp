from sqlalchemy import text
from backend.database import engine
from backend.auth.tenant import _ensure_app_role

def ensure_local_warehouses():
    with engine.begin() as conn:
        _ensure_app_role(conn)
        conn.execute(text('''CREATE TABLE IF NOT EXISTS local_warehouses (
            id BIGSERIAL PRIMARY KEY,
            organization_id INTEGER NOT NULL,
            name VARCHAR(100) NOT NULL,
            CONSTRAINT local_warehouses_org_name UNIQUE(organization_id,name)
        )'''))
        conn.execute(text('ALTER TABLE local_warehouses ENABLE ROW LEVEL SECURITY'))
        conn.execute(text('ALTER TABLE local_warehouses FORCE ROW LEVEL SECURITY'))
        conn.execute(text('DROP POLICY IF EXISTS tenant_isolation ON local_warehouses'))
        conn.execute(text("""CREATE POLICY tenant_isolation ON local_warehouses
            USING (organization_id = NULLIF(current_setting('app.organization_id',true),'')::integer)
            WITH CHECK (organization_id = NULLIF(current_setting('app.organization_id',true),'')::integer)"""))


def ensure_stock_view_settings():
    """Отдельные настройки вида: по умолчанию ничего не скрываем."""
    with engine.begin() as conn:
        _ensure_app_role(conn)
        conn.execute(text('''CREATE TABLE IF NOT EXISTS organization_stock_view (
          organization_id INTEGER PRIMARY KEY,
          fbs BOOLEAN NOT NULL DEFAULT TRUE,
          fbo BOOLEAN NOT NULL DEFAULT TRUE,
          wb BOOLEAN NOT NULL DEFAULT TRUE,
          ozon BOOLEAN NOT NULL DEFAULT TRUE,
          yandex BOOLEAN NOT NULL DEFAULT TRUE
        )'''))
        conn.execute(text('ALTER TABLE organization_stock_view ENABLE ROW LEVEL SECURITY'))
        conn.execute(text('ALTER TABLE organization_stock_view FORCE ROW LEVEL SECURITY'))
        conn.execute(text('DROP POLICY IF EXISTS tenant_isolation ON organization_stock_view'))
        conn.execute(text("""CREATE POLICY tenant_isolation ON organization_stock_view
          USING (organization_id = NULLIF(current_setting('app.organization_id',true),'')::integer)
          WITH CHECK (organization_id = NULLIF(current_setting('app.organization_id',true),'')::integer)"""))
