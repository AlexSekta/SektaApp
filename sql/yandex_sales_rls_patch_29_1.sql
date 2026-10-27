-- Patch 29.1 hotfix: correct quoting in tenant isolation policy.
-- Run as PostgreSQL owner (postgres). Transactional; does not change sales rows.
BEGIN;
DO $migration$
DECLARE
  tbl text;
  seq_name text;
BEGIN
  FOREACH tbl IN ARRAY ARRAY['yandex_sales_order_lines', 'yandex_sales_sync_days', 'yandex_sales_history_jobs'] LOOP
    IF to_regclass(format('public.%I', tbl)) IS NULL THEN
      RAISE EXCEPTION 'Missing table public.%', tbl;
    END IF;

    EXECUTE format('ALTER TABLE public.%I ENABLE ROW LEVEL SECURITY', tbl);
    EXECUTE format('ALTER TABLE public.%I FORCE ROW LEVEL SECURITY', tbl);

    -- Only replace the tenant policy; do not touch any other policies.
    EXECUTE format('DROP POLICY IF EXISTS tenant_isolation ON public.%I', tbl);
    EXECUTE format(
      'CREATE POLICY tenant_isolation ON public.%I '
      || 'USING (organization_id = NULLIF(current_setting(%L, true), %L)::integer) '
      || 'WITH CHECK (organization_id = NULLIF(current_setting(%L, true), %L)::integer)',
      tbl, 'app.organization_id', '', 'app.organization_id', ''
    );

    EXECUTE format('GRANT SELECT, INSERT, UPDATE, DELETE ON TABLE public.%I TO marketplace_app', tbl);
    seq_name := pg_get_serial_sequence(format('public.%I', tbl), 'id');
    IF seq_name IS NOT NULL THEN
      EXECUTE format('GRANT USAGE, SELECT ON SEQUENCE %s TO marketplace_app', seq_name::regclass);
    END IF;
  END LOOP;
END
$migration$;
COMMIT;

SELECT c.relname, c.relrowsecurity AS rowsecurity, c.relforcerowsecurity AS force_rls
FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace
WHERE n.nspname = 'public'
  AND c.relname IN ('yandex_sales_order_lines', 'yandex_sales_sync_days', 'yandex_sales_history_jobs')
ORDER BY c.relname;
