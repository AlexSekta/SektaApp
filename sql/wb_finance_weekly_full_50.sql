BEGIN;
ALTER TABLE public.wb_finance_reports
 ADD COLUMN IF NOT EXISTS expected_retail numeric(18,2),
 ADD COLUMN IF NOT EXISTS expected_for_pay numeric(18,2),
 ADD COLUMN IF NOT EXISTS expected_bank_payment numeric(18,2),
 ADD COLUMN IF NOT EXISTS expected_logistics numeric(18,2),
 ADD COLUMN IF NOT EXISTS expected_storage numeric(18,2),
 ADD COLUMN IF NOT EXISTS expected_acceptance numeric(18,2),
 ADD COLUMN IF NOT EXISTS expected_additional_payment numeric(18,2),
 ADD COLUMN IF NOT EXISTS report_type integer;
ALTER TABLE public.wb_finance_entries
 ADD COLUMN IF NOT EXISTS operation text,
 ADD COLUMN IF NOT EXISTS retail numeric(18,2) NOT NULL DEFAULT 0,
 ADD COLUMN IF NOT EXISTS for_pay numeric(18,2) NOT NULL DEFAULT 0,
 ADD COLUMN IF NOT EXISTS commission numeric(18,2) NOT NULL DEFAULT 0,
 ADD COLUMN IF NOT EXISTS vat numeric(18,2) NOT NULL DEFAULT 0,
 ADD COLUMN IF NOT EXISTS acquiring numeric(18,2) NOT NULL DEFAULT 0,
 ADD COLUMN IF NOT EXISTS logistics numeric(18,2) NOT NULL DEFAULT 0,
 ADD COLUMN IF NOT EXISTS storage numeric(18,2) NOT NULL DEFAULT 0,
 ADD COLUMN IF NOT EXISTS acceptance numeric(18,2) NOT NULL DEFAULT 0;
-- Old complete reports only held deductions/penalties. Queue them for full financial re-ingestion.
UPDATE public.wb_finance_reports
 SET status='queued',cursor_rrd=0,last_error=NULL,updated_at=now()
 WHERE status IN ('complete','mismatch');
COMMIT;
