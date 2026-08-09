-- Performance-only cleanup for the historical persistence schema.
-- Non-destructive: no historical rows are removed or modified.
-- The UNIQUE constraint on upload_ledger.sha256 already owns an equivalent index,
-- so the manually duplicated index is unnecessary.
DROP INDEX IF EXISTS public.ux_upload_ledger_sha256;

-- Cover the technical-indicator foreign key for joins and referential checks.
CREATE INDEX IF NOT EXISTS idx_technical_indicator_stock_daily
    ON public.technical_indicator_snapshot (stock_daily_id);
