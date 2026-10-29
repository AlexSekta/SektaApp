BEGIN;
CREATE TABLE IF NOT EXISTS ozon_finance_days (
  organization_id INTEGER NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
  day DATE NOT NULL,
  status TEXT NOT NULL DEFAULT 'queued',
  last_id TEXT NOT NULL DEFAULT '',
  page_count INTEGER NOT NULL DEFAULT 0,
  row_count INTEGER NOT NULL DEFAULT 0,
  total_amount NUMERIC(20, 2) NOT NULL DEFAULT 0,
  last_error TEXT,
  updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  PRIMARY KEY (organization_id, day),
  CONSTRAINT ozon_finance_days_status_ck CHECK (status IN ('queued','loading','complete','retry'))
);
CREATE TABLE IF NOT EXISTS ozon_finance_accruals (
  organization_id INTEGER NOT NULL,
  day DATE NOT NULL,
  accrual_id BIGINT NOT NULL,
  accrued_at TEXT,
  category TEXT NOT NULL,
  amount NUMERIC(20, 2) NOT NULL,
  currency TEXT,
  unit_number TEXT,
  posting_number TEXT,
  item_fees JSONB,
  non_item_fee JSONB,
  container_fees JSONB,
  posting JSONB,
  PRIMARY KEY (organization_id, accrual_id),
  FOREIGN KEY (organization_id, day) REFERENCES ozon_finance_days(organization_id, day) ON DELETE CASCADE
);
CREATE INDEX IF NOT EXISTS ix_ozon_finance_accruals_day ON ozon_finance_accruals (organization_id, day);
CREATE INDEX IF NOT EXISTS ix_ozon_finance_accruals_category ON ozon_finance_accruals (organization_id, day, category);
DO $$
BEGIN
  IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'marketplace_app') THEN
    GRANT SELECT, INSERT, UPDATE, DELETE ON ozon_finance_days, ozon_finance_accruals TO marketplace_app;
  END IF;
END $$;
ALTER TABLE ozon_finance_days ENABLE ROW LEVEL SECURITY;
ALTER TABLE ozon_finance_days FORCE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS ozon_finance_days_tenant ON ozon_finance_days;
CREATE POLICY ozon_finance_days_tenant ON ozon_finance_days
  USING (organization_id = NULLIF(current_setting('app.organization_id', true), '')::integer)
  WITH CHECK (organization_id = NULLIF(current_setting('app.organization_id', true), '')::integer);
ALTER TABLE ozon_finance_accruals ENABLE ROW LEVEL SECURITY;
ALTER TABLE ozon_finance_accruals FORCE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS ozon_finance_accruals_tenant ON ozon_finance_accruals;
CREATE POLICY ozon_finance_accruals_tenant ON ozon_finance_accruals
  USING (organization_id = NULLIF(current_setting('app.organization_id', true), '')::integer)
  WITH CHECK (organization_id = NULLIF(current_setting('app.organization_id', true), '')::integer);
COMMIT;
