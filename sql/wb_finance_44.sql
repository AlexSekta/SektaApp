BEGIN;
CREATE TABLE IF NOT EXISTS public.wb_finance_reports (
 organization_id integer NOT NULL, report_id bigint NOT NULL, date_from date NOT NULL, date_to date NOT NULL,
 expected_penalty numeric(18,2), expected_deduction numeric(18,2),
 status text NOT NULL DEFAULT 'queued', cursor_rrd bigint NOT NULL DEFAULT 0,
 loaded_rows integer NOT NULL DEFAULT 0, last_error text, updated_at timestamp NOT NULL DEFAULT now(),
 PRIMARY KEY (organization_id, report_id)
);
CREATE TABLE IF NOT EXISTS public.wb_finance_entries (
 organization_id integer NOT NULL, report_id bigint NOT NULL, rrd_id bigint NOT NULL,
 nm_id text, vendor_code text, sku text, srid text,
 penalty numeric(18,2) NOT NULL DEFAULT 0, deduction numeric(18,2) NOT NULL DEFAULT 0,
 additional_payment numeric(18,2) NOT NULL DEFAULT 0, reason text NOT NULL,
 PRIMARY KEY (organization_id, report_id, rrd_id)
);
CREATE INDEX IF NOT EXISTS wb_finance_entries_report_idx ON public.wb_finance_entries(organization_id, report_id);
DO $$ DECLARE t text; BEGIN
 FOREACH t IN ARRAY ARRAY['wb_finance_reports','wb_finance_entries'] LOOP
  EXECUTE format('ALTER TABLE public.%I ENABLE ROW LEVEL SECURITY',t);
  EXECUTE format('ALTER TABLE public.%I FORCE ROW LEVEL SECURITY',t);
  EXECUTE format('DROP POLICY IF EXISTS tenant_isolation ON public.%I',t);
  EXECUTE format('CREATE POLICY tenant_isolation ON public.%I USING (organization_id = NULLIF(current_setting(''app.organization_id'', true), '''')::integer) WITH CHECK (organization_id = NULLIF(current_setting(''app.organization_id'', true), '''')::integer)',t);
  EXECUTE format('GRANT SELECT,INSERT,UPDATE,DELETE ON public.%I TO marketplace_app',t);
 END LOOP;
END $$;
COMMIT;
SELECT relname,relrowsecurity,relforcerowsecurity FROM pg_class WHERE relname IN ('wb_finance_reports','wb_finance_entries');
