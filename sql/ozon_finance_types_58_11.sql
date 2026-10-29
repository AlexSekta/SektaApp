BEGIN;
CREATE TABLE IF NOT EXISTS ozon_finance_type_catalog (
 organization_id integer NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
 type_id integer NOT NULL,
 name text NOT NULL,
 description text,
 updated_at timestamptz NOT NULL DEFAULT now(),
 PRIMARY KEY (organization_id,type_id)
);
ALTER TABLE ozon_finance_type_catalog ENABLE ROW LEVEL SECURITY;
ALTER TABLE ozon_finance_type_catalog FORCE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS ozon_finance_type_catalog_tenant ON ozon_finance_type_catalog;
CREATE POLICY ozon_finance_type_catalog_tenant ON ozon_finance_type_catalog
 USING (organization_id = NULLIF(current_setting('app.organization_id',true),'')::integer)
 WITH CHECK (organization_id = NULLIF(current_setting('app.organization_id',true),'')::integer);
COMMIT;
