-- Keep the UNIQUE constraint as the single source of truth for batch_key.
-- Dropping a redundant index does not remove historical data.
DROP INDEX IF EXISTS public.ux_upload_runs_batch_key;
