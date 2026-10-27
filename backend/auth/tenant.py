from contextlib import contextmanager
import hashlib
from sqlalchemy import text
from sqlalchemy.orm import Session
from backend.database import engine, Base, SessionLocal
from backend.logging_config import get_logger

from backend.models.product import Product
from backend.models.warehouse import Warehouse
from backend.models.stock_history import StockHistory
from backend.models.master_product import MasterProduct
from backend.models.one_c_stock import OneCStock
from backend.models.auto_stock_history import AutoStockHistory
from backend.models.wb_review import WBReview
from backend.models.wb_question import WBQuestion
from backend.models.yandex_question import YandexQuestion, YandexQuestionAnswer, YandexQuestionAnswerComment
from backend.models.yandex_review import YandexReview
from backend.models.yandex_review_comment import YandexReviewComment
from backend.models.auth import Organization, User, AuthSession
from backend.models.marketplace_connection import MarketplaceConnection

logger = get_logger("tenant")
TENANT_TABLES = [
    "products", "warehouses", "stock_history", "master_products", "one_c_stocks",
    "auto_stock_history", "wb_reviews", "wb_questions", "yandex_questions",
    "yandex_question_answers", "yandex_question_answer_comments", "yandex_reviews",
    "yandex_review_comments",
]
UNIQUE_SPECS = {
    "master_products": [("organization_id", "internal_article"), ("organization_id", "seller_article")],
    "stock_history": [("organization_id", "date", "marketplace", "warehouse_id", "sku")],
    "one_c_stocks": [("organization_id", "seller_article", "group")],
    "auto_stock_history": [("organization_id", "date", "marketplace")],
    "wb_questions": [("organization_id", "question_id")],
    "wb_reviews": [("organization_id", "feedback_id")],
    "yandex_questions": [("organization_id", "business_id", "question_id")],
    "yandex_question_answers": [("organization_id", "business_id", "question_id", "answer_id")],
    "yandex_question_answer_comments": [("organization_id", "business_id", "question_id", "comment_id")],
    "yandex_reviews": [("organization_id", "business_id", "feedback_id")],
    "yandex_review_comments": [("organization_id", "business_id", "feedback_id", "comment_id")],
}
MIGRATION_VERSION = "multitenancy_v2"
APP_DB_ROLE = "marketplace_app"

def _qi(value: str) -> str:
    return '"' + value.replace('"', '""') + '"'

def _constraint_name(table, cols):
    raw = "tenant_" + table + "_" + "_".join(cols)
    return "uq_" + table[:35] + "_" + hashlib.sha1(raw.encode()).hexdigest()[:10]

def _marker_exists(conn):
    conn.execute(text("CREATE TABLE IF NOT EXISTS schema_migrations (version VARCHAR(100) PRIMARY KEY, applied_at TIMESTAMP NOT NULL DEFAULT NOW())"))
    return conn.execute(text("SELECT 1 FROM schema_migrations WHERE version=:v"), {"v": MIGRATION_VERSION}).first() is not None

def _any_business_data(conn):
    for table in TENANT_TABLES:
        if conn.execute(text("SELECT to_regclass(:t)"), {"t": table}).scalar():
            if conn.execute(text(f"SELECT EXISTS (SELECT 1 FROM {_qi(table)} LIMIT 1)")).scalar():
                return True
    return False

def _bootstrap_org(conn):
    row = conn.execute(text("SELECT id FROM organizations ORDER BY id LIMIT 1")).first()
    if row:
        return int(row[0])
    if not _any_business_data(conn):
        return None
    org_id = int(conn.execute(text("INSERT INTO organizations(name, created_at) VALUES (:name, NOW()) RETURNING id"), {"name": "Основная организация"}).scalar_one())
    logger.info("TENANT_BOOTSTRAP_ORGANIZATION | organization_id=%s", org_id)
    return org_id


def _ensure_app_role(conn):
    conn.execute(text("""
        DO $$
        BEGIN
            IF NOT EXISTS (
                SELECT 1 FROM pg_roles WHERE rolname = 'marketplace_app'
            ) THEN
                CREATE ROLE marketplace_app NOLOGIN;
            END IF;
        END
        $$;
    """))
    conn.execute(text("GRANT USAGE ON SCHEMA public TO marketplace_app"))
    conn.execute(text("GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA public TO marketplace_app"))
    conn.execute(text("GRANT USAGE, SELECT, UPDATE ON ALL SEQUENCES IN SCHEMA public TO marketplace_app"))
    conn.execute(text("""
        ALTER DEFAULT PRIVILEGES IN SCHEMA public
        GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES TO marketplace_app
    """))
    conn.execute(text("""
        ALTER DEFAULT PRIVILEGES IN SCHEMA public
        GRANT USAGE, SELECT, UPDATE ON SEQUENCES TO marketplace_app
    """))

def set_app_db_role(db: Session):
    db.connection().exec_driver_sql("SET ROLE marketplace_app")

def reset_app_db_role(db: Session):
    try:
        db.connection().exec_driver_sql("RESET ROLE")
    except Exception:
        pass

def ensure_multitenancy_schema():
    Base.metadata.create_all(bind=engine)
    with engine.begin() as conn:
        _ensure_app_role(conn)
        if _marker_exists(conn):
            return
        org_id = _bootstrap_org(conn)
        for table in TENANT_TABLES:
            if not conn.execute(text("SELECT to_regclass(:t)"), {"t": table}).scalar():
                continue
            cols = {r[0] for r in conn.execute(text("SELECT column_name FROM information_schema.columns WHERE table_schema=current_schema() AND table_name=:t"), {"t": table}).fetchall()}
            if "organization_id" not in cols:
                conn.execute(text(f"ALTER TABLE {_qi(table)} ADD COLUMN organization_id INTEGER"))
            if org_id is not None:
                conn.execute(text(f"UPDATE {_qi(table)} SET organization_id=:org WHERE organization_id IS NULL"), {"org": org_id})
            conn.execute(text(f"ALTER TABLE {_qi(table)} ALTER COLUMN organization_id SET DEFAULT current_setting('app.organization_id', true)::integer"))
            conn.execute(text(f"ALTER TABLE {_qi(table)} ALTER COLUMN organization_id SET NOT NULL"))
            index_name = "ix_" + table + "_organization_id"
            conn.execute(text(f"CREATE INDEX IF NOT EXISTS {_qi(index_name)} ON {_qi(table)} (organization_id)"))
        # Old master-products migration created a global unique index. Remove it
        # before installing the tenant-scoped uniqueness below.
        conn.execute(text("DROP INDEX IF EXISTS ux_master_products_internal_article"))

        for table, specs in UNIQUE_SPECS.items():
            if not conn.execute(text("SELECT to_regclass(:t)"), {"t": table}).scalar():
                continue
            constraints = conn.execute(text("SELECT conname FROM pg_constraint WHERE conrelid=to_regclass(:table) AND contype='u'"), {"table": table}).fetchall()
            for (name,) in constraints:
                conn.execute(text(f"ALTER TABLE {_qi(table)} DROP CONSTRAINT {_qi(name)}"))
            for cols in specs:
                cname = _constraint_name(table, cols)
                cols_sql = ", ".join(_qi(c) for c in cols)
                conn.execute(text(f"ALTER TABLE {_qi(table)} ADD CONSTRAINT {_qi(cname)} UNIQUE ({cols_sql})"))
        for table in TENANT_TABLES:
            if not conn.execute(text("SELECT to_regclass(:t)"), {"t": table}).scalar():
                continue
            conn.execute(text(f"ALTER TABLE {_qi(table)} ENABLE ROW LEVEL SECURITY"))
            conn.execute(text(f"ALTER TABLE {_qi(table)} FORCE ROW LEVEL SECURITY"))
            conn.execute(text(f"DROP POLICY IF EXISTS tenant_isolation ON {_qi(table)}"))
            conn.execute(text(f"CREATE POLICY tenant_isolation ON {_qi(table)} USING (organization_id = current_setting('app.organization_id', true)::integer) WITH CHECK (organization_id = current_setting('app.organization_id', true)::integer)"))
        conn.execute(text("INSERT INTO schema_migrations(version) VALUES (:v) ON CONFLICT (version) DO NOTHING"), {"v": MIGRATION_VERSION})
        logger.info("TENANT_SCHEMA_READY | version=%s", MIGRATION_VERSION)

def legacy_sync_organization_id():
    with engine.connect() as conn:
        row = conn.execute(text("SELECT id FROM organizations ORDER BY id LIMIT 1")).first()
        return int(row[0]) if row else None

def set_tenant_context(db: Session, organization_id: int):
    db.connection().exec_driver_sql("SET app.organization_id = %s", (str(int(organization_id)),))

def clear_tenant_context(db: Session):
    try:
        db.connection().exec_driver_sql("RESET app.organization_id")
    except Exception:
        pass

@contextmanager
def tenant_session(organization_id: int):
    db = SessionLocal()
    try:
        set_app_db_role(db)
        set_tenant_context(db, organization_id)
        yield db
    finally:
        clear_tenant_context(db)
        reset_app_db_role(db)
        db.close()


def ensure_marketplace_connections_schema():
    Base.metadata.create_all(bind=engine, tables=[MarketplaceConnection.__table__])
    with engine.begin() as conn:
        _ensure_app_role(conn)
        conn.execute(text("ALTER TABLE marketplace_connections ENABLE ROW LEVEL SECURITY"))
        conn.execute(text("ALTER TABLE marketplace_connections FORCE ROW LEVEL SECURITY"))
        conn.execute(text("DROP POLICY IF EXISTS tenant_isolation ON marketplace_connections"))
        conn.execute(text("CREATE POLICY tenant_isolation ON marketplace_connections USING (organization_id = current_setting('app.organization_id', true)::integer) WITH CHECK (organization_id = current_setting('app.organization_id', true)::integer)"))
        conn.execute(text("CREATE UNIQUE INDEX IF NOT EXISTS ux_marketplace_connections_org_marketplace ON marketplace_connections (organization_id, marketplace)"))


def ensure_team_schema():
    """Idempotent extra tables; business-data migrations and stocks untouched."""
    from backend.models.auth import OrganizationInvitation, UserAuditEvent
    Base.metadata.create_all(bind=engine, tables=[OrganizationInvitation.__table__, UserAuditEvent.__table__])
    with engine.begin() as conn:
        _ensure_app_role(conn)
        for table in ("organization_invitations", "user_audit_events"):
            conn.execute(text(f'ALTER TABLE "{table}" ENABLE ROW LEVEL SECURITY'))
            conn.execute(text(f'ALTER TABLE "{table}" FORCE ROW LEVEL SECURITY'))
            conn.execute(text(f'DROP POLICY IF EXISTS tenant_isolation ON "{table}"'))
            conn.execute(text(f"""CREATE POLICY tenant_isolation ON "{table}"
                USING (organization_id = NULLIF(current_setting('app.organization_id', true), '')::integer)
                WITH CHECK (organization_id = NULLIF(current_setting('app.organization_id', true), '')::integer)"""))
