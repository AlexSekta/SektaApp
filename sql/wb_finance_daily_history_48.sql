BEGIN;
CREATE TABLE IF NOT EXISTS public.wb_finance_daily_history_jobs (
 organization_id integer PRIMARY KEY,
 next_to date NOT NULL,
 status text NOT NULL DEFAULT 'running',
 last_error text,
 updated_at timestamp NOT NULL DEFAULT now()
);
ALTER TABLE public.wb_finance_daily_history_jobs ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.wb_finance_daily_history_jobs FORCE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS tenant_isolation ON public.wb_finance_daily_history_jobs;
CREATE POLICY tenant_isolation ON public.wb_finance_daily_history_jobs
 USING (organization_id = NULLIF(current_setting('app.organization_id',true),'')::integer)
 WITH CHECK (organization_id = NULLIF(current_setting('app.organization_id',true),'')::integer);
GRANT SELECT,INSERT,UPDATE,DELETE ON public.wb_finance_daily_history_jobs TO marketplace_app;
COMMIT;
