-- Corrective additive migration for the historical Supabase schema.
-- No historical rows are removed or modified.

ALTER TABLE orderbook_snapshot
    ADD COLUMN IF NOT EXISTS ask_volume_4 double precision;

CREATE OR REPLACE VIEW latest_stock_daily AS
SELECT DISTINCT ON (stock_code) *
FROM stock_daily
ORDER BY stock_code, trade_date DESC, created_at DESC, id DESC;

CREATE OR REPLACE VIEW latest_orderbook_snapshot AS
SELECT DISTINCT ON (stock_code) *
FROM orderbook_snapshot
ORDER BY stock_code, snapshot_date DESC, snapshot_time DESC, created_at DESC, id DESC;
