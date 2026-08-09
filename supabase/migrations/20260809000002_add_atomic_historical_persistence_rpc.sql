-- Atomic server-side persistence entrypoint for the BEI Screener backend.
-- SECURITY DEFINER is restricted to service_role; anon/authenticated/public cannot execute it.

CREATE OR REPLACE FUNCTION public.persist_upload_batch(
    p_run jsonb,
    p_files jsonb,
    p_daily jsonb,
    p_orderbook jsonb
)
RETURNS jsonb
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = public, pg_temp
AS $$
DECLARE
    v_run_id uuid;
    v_ledger_count integer := 0;
    v_daily_count integer := 0;
    v_orderbook_count integer := 0;
BEGIN
    INSERT INTO public.upload_runs (source, note)
    VALUES (COALESCE(NULLIF(p_run->>'source', ''), 'app_upload'), p_run->>'note')
    RETURNING id INTO v_run_id;

    IF jsonb_typeof(COALESCE(p_files, '[]'::jsonb)) <> 'array'
       OR jsonb_typeof(COALESCE(p_daily, '[]'::jsonb)) <> 'array'
       OR jsonb_typeof(COALESCE(p_orderbook, '[]'::jsonb)) <> 'array' THEN
        RAISE EXCEPTION 'Historical persistence payload arrays are required';
    END IF;

    INSERT INTO public.upload_ledger (upload_run_id, sha256, filename, size_bytes, rows_read, rows_saved, metadata)
    SELECT v_run_id, f.sha256, f.filename, f.size_bytes, COALESCE(f.rows_read, 0), COALESCE(f.rows_saved, 0), COALESCE(f.metadata, '{}'::jsonb)
    FROM jsonb_to_recordset(p_files) AS f(sha256 text, filename text, size_bytes bigint, rows_read integer, rows_saved integer, metadata jsonb)
    ON CONFLICT (sha256) DO NOTHING;
    GET DIAGNOSTICS v_ledger_count = ROW_COUNT;

    INSERT INTO public.stock_daily (
        upload_run_id, trade_date, stock_code, company_name,
        open_price, high_price, low_price, close_price, volume, value, frequency, foreign_sell, foreign_buy,
        bid_price_1, bid_volume_1, ask_price_1, ask_volume_1,
        bid_price_2, bid_volume_2, ask_price_2, ask_volume_2,
        bid_price_3, bid_volume_3, ask_price_3, ask_volume_3,
        bid_price_4, bid_volume_4, ask_price_4, ask_volume_4,
        bid_price_5, bid_volume_5, ask_price_5, ask_volume_5, raw_data
    )
    SELECT
        v_run_id, d.trade_date, btrim(d.stock_code), d.company_name,
        d.open_price, d.high_price, d.low_price, d.close_price, d.volume, d.value, d.frequency, d.foreign_sell, d.foreign_buy,
        d.bid_price_1, d.bid_volume_1, d.ask_price_1, d.ask_volume_1,
        d.bid_price_2, d.bid_volume_2, d.ask_price_2, d.ask_volume_2,
        d.bid_price_3, d.bid_volume_3, d.ask_price_3, d.ask_volume_3,
        d.bid_price_4, d.bid_volume_4, d.ask_price_4, d.ask_volume_4,
        d.bid_price_5, d.bid_volume_5, d.ask_price_5, d.ask_volume_5, d.raw_data
    FROM jsonb_to_recordset(p_daily) AS d(
        trade_date date, stock_code text, company_name text,
        open_price double precision, high_price double precision, low_price double precision, close_price double precision,
        volume double precision, value double precision, frequency double precision, foreign_sell double precision, foreign_buy double precision,
        bid_price_1 double precision, bid_volume_1 double precision, ask_price_1 double precision, ask_volume_1 double precision,
        bid_price_2 double precision, bid_volume_2 double precision, ask_price_2 double precision, ask_volume_2 double precision,
        bid_price_3 double precision, bid_volume_3 double precision, ask_price_3 double precision, ask_volume_3 double precision,
        bid_price_4 double precision, bid_volume_4 double precision, ask_price_4 double precision, ask_volume_4 double precision,
        bid_price_5 double precision, bid_volume_5 double precision, ask_price_5 double precision, ask_volume_5 double precision,
        raw_data jsonb
    )
    WHERE d.trade_date IS NOT NULL AND btrim(d.stock_code) <> ''
    ON CONFLICT (upload_run_id, trade_date, stock_code) DO UPDATE SET
        company_name = EXCLUDED.company_name, open_price = EXCLUDED.open_price, high_price = EXCLUDED.high_price, low_price = EXCLUDED.low_price,
        close_price = EXCLUDED.close_price, volume = EXCLUDED.volume, value = EXCLUDED.value, frequency = EXCLUDED.frequency,
        foreign_sell = EXCLUDED.foreign_sell, foreign_buy = EXCLUDED.foreign_buy,
        bid_price_1 = EXCLUDED.bid_price_1, bid_volume_1 = EXCLUDED.bid_volume_1, ask_price_1 = EXCLUDED.ask_price_1, ask_volume_1 = EXCLUDED.ask_volume_1,
        bid_price_2 = EXCLUDED.bid_price_2, bid_volume_2 = EXCLUDED.bid_volume_2, ask_price_2 = EXCLUDED.ask_price_2, ask_volume_2 = EXCLUDED.ask_volume_2,
        bid_price_3 = EXCLUDED.bid_price_3, bid_volume_3 = EXCLUDED.bid_volume_3, ask_price_3 = EXCLUDED.ask_price_3, ask_volume_3 = EXCLUDED.ask_volume_3,
        bid_price_4 = EXCLUDED.bid_price_4, bid_volume_4 = EXCLUDED.bid_volume_4, ask_price_4 = EXCLUDED.ask_price_4, ask_volume_4 = EXCLUDED.ask_volume_4,
        bid_price_5 = EXCLUDED.bid_price_5, bid_volume_5 = EXCLUDED.bid_volume_5, ask_price_5 = EXCLUDED.ask_price_5, ask_volume_5 = EXCLUDED.ask_volume_5,
        raw_data = EXCLUDED.raw_data;
    GET DIAGNOSTICS v_daily_count = ROW_COUNT;

    INSERT INTO public.orderbook_snapshot (
        upload_run_id, snapshot_date, snapshot_time, stock_code,
        bid_price_1, bid_volume_1, ask_price_1, ask_volume_1,
        bid_price_2, bid_volume_2, ask_price_2, ask_volume_2,
        bid_price_3, bid_volume_3, ask_price_3, ask_volume_3,
        bid_price_4, bid_volume_4, ask_price_4, ask_volume_4,
        bid_price_5, bid_volume_5, ask_price_5, ask_volume_5, raw_data
    )
    SELECT
        v_run_id, o.snapshot_date, COALESCE(o.snapshot_time, '00:00:00'::time), btrim(o.stock_code),
        o.bid_price_1, o.bid_volume_1, o.ask_price_1, o.ask_volume_1,
        o.bid_price_2, o.bid_volume_2, o.ask_price_2, o.ask_volume_2,
        o.bid_price_3, o.bid_volume_3, o.ask_price_3, o.ask_volume_3,
        o.bid_price_4, o.bid_volume_4, o.ask_price_4, o.ask_volume_4,
        o.bid_price_5, o.bid_volume_5, o.ask_price_5, o.ask_volume_5, o.raw_data
    FROM jsonb_to_recordset(p_orderbook) AS o(
        snapshot_date date, snapshot_time time, stock_code text,
        bid_price_1 double precision, bid_volume_1 double precision, ask_price_1 double precision, ask_volume_1 double precision,
        bid_price_2 double precision, bid_volume_2 double precision, ask_price_2 double precision, ask_volume_2 double precision,
        bid_price_3 double precision, bid_volume_3 double precision, ask_price_3 double precision, ask_volume_3 double precision,
        bid_price_4 double precision, bid_volume_4 double precision, ask_price_4 double precision, ask_volume_4 double precision,
        bid_price_5 double precision, bid_volume_5 double precision, ask_price_5 double precision, ask_volume_5 double precision,
        raw_data jsonb
    )
    WHERE o.snapshot_date IS NOT NULL AND btrim(o.stock_code) <> ''
    ON CONFLICT (upload_run_id, snapshot_date, snapshot_time, stock_code) DO UPDATE SET
        bid_price_1 = EXCLUDED.bid_price_1, bid_volume_1 = EXCLUDED.bid_volume_1, ask_price_1 = EXCLUDED.ask_price_1, ask_volume_1 = EXCLUDED.ask_volume_1,
        bid_price_2 = EXCLUDED.bid_price_2, bid_volume_2 = EXCLUDED.bid_volume_2, ask_price_2 = EXCLUDED.ask_price_2, ask_volume_2 = EXCLUDED.ask_volume_2,
        bid_price_3 = EXCLUDED.bid_price_3, bid_volume_3 = EXCLUDED.bid_volume_3, ask_price_3 = EXCLUDED.ask_price_3, ask_volume_3 = EXCLUDED.ask_volume_3,
        bid_price_4 = EXCLUDED.bid_price_4, bid_volume_4 = EXCLUDED.bid_volume_4, ask_price_4 = EXCLUDED.ask_price_4, ask_volume_4 = EXCLUDED.ask_volume_4,
        bid_price_5 = EXCLUDED.bid_price_5, bid_volume_5 = EXCLUDED.bid_volume_5, ask_price_5 = EXCLUDED.ask_price_5, ask_volume_5 = EXCLUDED.ask_volume_5,
        raw_data = EXCLUDED.raw_data;
    GET DIAGNOSTICS v_orderbook_count = ROW_COUNT;

    RETURN jsonb_build_object('upload_run_id', v_run_id, 'ledger_rows', v_ledger_count, 'daily_rows', v_daily_count, 'orderbook_rows', v_orderbook_count);
END;
$$;

REVOKE ALL ON FUNCTION public.persist_upload_batch(jsonb, jsonb, jsonb, jsonb) FROM PUBLIC;
REVOKE ALL ON FUNCTION public.persist_upload_batch(jsonb, jsonb, jsonb, jsonb) FROM anon;
REVOKE ALL ON FUNCTION public.persist_upload_batch(jsonb, jsonb, jsonb, jsonb) FROM authenticated;
GRANT EXECUTE ON FUNCTION public.persist_upload_batch(jsonb, jsonb, jsonb, jsonb) TO service_role;
