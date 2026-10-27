BEGIN;
CREATE TABLE IF NOT EXISTS public.ozon_sales_history_jobs (
    id SERIAL PRIMARY KEY,
    organization_id INTEGER NOT NULL,
    next_day DATE,
    status VARCHAR(24) NOT NULL DEFAULT 'pending',
    last_error TEXT,
    updated_at TIMESTAMP NOT NULL DEFAULT NOW(),
    CONSTRAINT uq_ozon_sales_history_org UNIQUE (organization_id)
);
CREATE INDEX IF NOT EXISTS ix_ozon_sales_history_jobs_organization_id ON public.ozon_sales_history_jobs (organization_id);
GRANT SELECT, INSERT, UPDATE, DELETE ON public.ozon_sales_history_jobs TO marketplace_app;
GRANT USAGE, SELECT, UPDATE ON SEQUENCE public.ozon_sales_history_jobs_id_seq TO marketplace_app;
ALTER TABLE public.ozon_sales_history_jobs ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.ozon_sales_history_jobs FORCE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS tenant_isolation ON public.ozon_sales_history_jobs;
CREATE POLICY tenant_isolation ON public.ozon_sales_history_jobs
USING (organization_id = NULLIF(current_setting('app.organization_id', true), '')::integer)
WITH CHECK (organization_id = NULLIF(current_setting('app.organization_id', true), '')::integer);
COMMIT;
SELECT c.relname, c.relrowsecurity AS rowsecurity, c.relforcerowsecurity AS force_rls
FROM pg_class c WHERE c.oid='public.ozon_sales_history_jobs'::regclass;
