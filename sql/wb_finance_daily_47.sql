BEGIN;
CREATE TABLE IF NOT EXISTS public.wb_finance_daily_reports (
 organization_id integer NOT NULL, report_id bigint NOT NULL, report_date date NOT NULL,
 report_type integer, created_date date,
 expected_retail numeric(18,2), expected_for_pay numeric(18,2), expected_bank_payment numeric(18,2),
 expected_logistics numeric(18,2), expected_penalty numeric(18,2), expected_deduction numeric(18,2),
 expected_storage numeric(18,2), expected_acceptance numeric(18,2),
 status text NOT NULL DEFAULT 'queued', cursor_rrd bigint NOT NULL DEFAULT 0,
 loaded_rows integer NOT NULL DEFAULT 0, last_error text, updated_at timestamp NOT NULL DEFAULT now(),
 PRIMARY KEY (organization_id,report_id)
);
CREATE INDEX IF NOT EXISTS wb_finance_daily_reports_date_idx ON public.wb_finance_daily_reports(organization_id,report_date);
CREATE TABLE IF NOT EXISTS public.wb_finance_daily_entries (
 organization_id integer NOT NULL, report_id bigint NOT NULL, rrd_id bigint NOT NULL,
 nm_id text, vendor_code text, sku text, srid text,
 operation text, reason text,
 retail numeric(18,2) NOT NULL DEFAULT 0,
 for_pay numeric(18,2) NOT NULL DEFAULT 0,
 commission numeric(18,2) NOT NULL DEFAULT 0,
 vat numeric(18,2) NOT NULL DEFAULT 0,
 acquiring numeric(18,2) NOT NULL DEFAULT 0,
 logistics numeric(18,2) NOT NULL DEFAULT 0,
 storage numeric(18,2) NOT NULL DEFAULT 0,
 acceptance numeric(18,2) NOT NULL DEFAULT 0,
 penalty numeric(18,2) NOT NULL DEFAULT 0,
 deduction numeric(18,2) NOT NULL DEFAULT 0,
 additional_payment numeric(18,2) NOT NULL DEFAULT 0,
 PRIMARY KEY (organization_id,report_id,rrd_id)
);
CREATE INDEX IF NOT EXISTS wb_finance_daily_entries_report_idx ON public.wb_finance_daily_entries(organization_id,report_id);
DO $$ DECLARE t text; BEGIN
 FOREACH t IN ARRAY ARRAY['wb_finance_daily_reports','wb_finance_daily_entries'] LOOP
  EXECUTE format('ALTER TABLE public.%I ENABLE ROW LEVEL SECURITY',t);
  EXECUTE format('ALTER TABLE public.%I FORCE ROW LEVEL SECURITY',t);
  EXECUTE format('DROP POLICY IF EXISTS tenant_isolation ON public.%I',t);
  EXECUTE format('CREATE POLICY tenant_isolation ON public.%I USING (organization_id = NULLIF(current_setting(''app.organization_id'',true),'''')::integer) WITH CHECK (organization_id = NULLIF(current_setting(''app.organization_id'',true),'''')::integer)',t);
  EXECUTE format('GRANT SELECT,INSERT,UPDATE,DELETE ON public.%I TO marketplace_app',t);
 END LOOP;
END $$;
COMMIT;
SELECT relname,relrowsecurity,relforcerowsecurity FROM pg_class WHERE relname IN ('wb_finance_daily_reports','wb_finance_daily_entries');
