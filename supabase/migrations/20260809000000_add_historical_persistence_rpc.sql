-- Atomic, idempotent historical persistence RPC for the BEI Screener.
-- Additive and non-destructive: it never drops or truncates historical data.

CREATE OR REPLACE FUNCTION persist_bei_historical_batch(
    p_upload_run_id uuid,
    p_upload_ledger jsonb,
    p_stock_daily jsonb,
    p_orderbook jsonb,
    p_technical jsonb
)
RETURNS jsonb
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = public
AS $$
DECLARE
    v_ledger_count integer := 0;
    v_stock_count integer := 0;
    v_orderbook_count integer := 0;
    v_technical_count integer := 0;
BEGIN
    INSERT INTO upload_runs (id, source, note)
    VALUES (p_upload_run_id, 'app_upload', 'BEI Screener historical persistence')
    ON CONFLICT (id) DO NOTHING;

    INSERT INTO upload_ledger (upload_run_id, sha256, filename, size_bytes, rows_read, rows_saved, metadata)
    SELECT p_upload_run_id, x.sha256, x.filename, COALESCE(x.size_bytes,0), COALESCE(x.rows_read,0), COALESCE(x.rows_saved,0), COALESCE(x.metadata,'{}'::jsonb)
    FROM jsonb_to_recordset(COALESCE(p_upload_ledger,'[]'::jsonb)) AS x(
        sha256 text, filename text, size_bytes bigint, rows_read integer, rows_saved integer, metadata jsonb
    )
    ON CONFLICT (sha256) DO UPDATE SET
        upload_run_id=EXCLUDED.upload_run_id, filename=EXCLUDED.filename, size_bytes=EXCLUDED.size_bytes,
        rows_read=EXCLUDED.rows_read, rows_saved=EXCLUDED.rows_saved, metadata=EXCLUDED.metadata;
    GET DIAGNOSTICS v_ledger_count = ROW_COUNT;

    INSERT INTO stock_daily (
        upload_run_id, trade_date, stock_code, company_name, open_price, high_price, low_price, close_price,
        volume, value, frequency, foreign_sell, foreign_buy,
        bid_price_1,bid_volume_1,ask_price_1,ask_volume_1,bid_price_2,bid_volume_2,ask_price_2,ask_volume_2,
        bid_price_3,bid_volume_3,ask_price_3,ask_volume_3,bid_price_4,bid_volume_4,ask_price_4,ask_volume_4,
        bid_price_5,bid_volume_5,ask_price_5,ask_volume_5,raw_data
    )
    SELECT p_upload_run_id,x.trade_date,upper(trim(x.stock_code)),x.company_name,x.open_price,x.high_price,x.low_price,x.close_price,
        x.volume,x.value,x.frequency,x.foreign_sell,x.foreign_buy,
        x.bid_price_1,x.bid_volume_1,x.ask_price_1,x.ask_volume_1,x.bid_price_2,x.bid_volume_2,x.ask_price_2,x.ask_volume_2,
        x.bid_price_3,x.bid_volume_3,x.ask_price_3,x.ask_volume_3,x.bid_price_4,x.bid_volume_4,x.ask_price_4,x.ask_volume_4,
        x.bid_price_5,x.bid_volume_5,x.ask_price_5,x.ask_volume_5,x.raw_data
    FROM jsonb_to_recordset(COALESCE(p_stock_daily,'[]'::jsonb)) AS x(
        trade_date date, stock_code text, company_name text, open_price double precision, high_price double precision,
        low_price double precision, close_price double precision, volume double precision, value double precision,
        frequency double precision, foreign_sell double precision, foreign_buy double precision,
        bid_price_1 double precision,bid_volume_1 double precision,ask_price_1 double precision,ask_volume_1 double precision,
        bid_price_2 double precision,bid_volume_2 double precision,ask_price_2 double precision,ask_volume_2 double precision,
        bid_price_3 double precision,bid_volume_3 double precision,ask_price_3 double precision,ask_volume_3 double precision,
        bid_price_4 double precision,bid_volume_4 double precision,ask_price_4 double precision,ask_volume_4 double precision,
        bid_price_5 double precision,bid_volume_5 double precision,ask_price_5 double precision,ask_volume_5 double precision,
        raw_data jsonb
    )
    WHERE x.trade_date IS NOT NULL AND btrim(x.stock_code) <> ''
    ON CONFLICT (upload_run_id,trade_date,stock_code) DO UPDATE SET
        company_name=EXCLUDED.company_name,open_price=EXCLUDED.open_price,high_price=EXCLUDED.high_price,
        low_price=EXCLUDED.low_price,close_price=EXCLUDED.close_price,volume=EXCLUDED.volume,value=EXCLUDED.value,
        frequency=EXCLUDED.frequency,foreign_sell=EXCLUDED.foreign_sell,foreign_buy=EXCLUDED.foreign_buy,
        bid_price_1=EXCLUDED.bid_price_1,bid_volume_1=EXCLUDED.bid_volume_1,ask_price_1=EXCLUDED.ask_price_1,ask_volume_1=EXCLUDED.ask_volume_1,
        bid_price_2=EXCLUDED.bid_price_2,bid_volume_2=EXCLUDED.bid_volume_2,ask_price_2=EXCLUDED.ask_price_2,ask_volume_2=EXCLUDED.ask_volume_2,
        bid_price_3=EXCLUDED.bid_price_3,bid_volume_3=EXCLUDED.bid_volume_3,ask_price_3=EXCLUDED.ask_price_3,ask_volume_3=EXCLUDED.ask_volume_3,
        bid_price_4=EXCLUDED.bid_price_4,bid_volume_4=EXCLUDED.bid_volume_4,ask_price_4=EXCLUDED.ask_price_4,ask_volume_4=EXCLUDED.ask_volume_4,
        bid_price_5=EXCLUDED.bid_price_5,bid_volume_5=EXCLUDED.bid_volume_5,ask_price_5=EXCLUDED.ask_price_5,ask_volume_5=EXCLUDED.ask_volume_5,
        raw_data=EXCLUDED.raw_data;
    GET DIAGNOSTICS v_stock_count = ROW_COUNT;

    INSERT INTO orderbook_snapshot (
        upload_run_id,stock_daily_id,snapshot_date,snapshot_time,stock_code,
        bid_price_1,bid_volume_1,ask_price_1,ask_volume_1,bid_price_2,bid_volume_2,ask_price_2,ask_volume_2,
        bid_price_3,bid_volume_3,ask_price_3,ask_volume_3,bid_price_4,bid_volume_4,ask_price_4,ask_volume_4,
        bid_price_5,bid_volume_5,ask_price_5,ask_volume_5,raw_data
    )
    SELECT p_upload_run_id,sd.id,x.snapshot_date,COALESCE(x.snapshot_time,'00:00:00'::time),upper(trim(x.stock_code)),
        x.bid_price_1,x.bid_volume_1,x.ask_price_1,x.ask_volume_1,x.bid_price_2,x.bid_volume_2,x.ask_price_2,x.ask_volume_2,
        x.bid_price_3,x.bid_volume_3,x.ask_price_3,x.ask_volume_3,x.bid_price_4,x.bid_volume_4,x.ask_price_4,x.ask_volume_4,
        x.bid_price_5,x.bid_volume_5,x.ask_price_5,x.ask_volume_5,x.raw_data
    FROM jsonb_to_recordset(COALESCE(p_orderbook,'[]'::jsonb)) AS x(
        snapshot_date date,snapshot_time time,stock_code text,
        bid_price_1 double precision,bid_volume_1 double precision,ask_price_1 double precision,ask_volume_1 double precision,
        bid_price_2 double precision,bid_volume_2 double precision,ask_price_2 double precision,ask_volume_2 double precision,
        bid_price_3 double precision,bid_volume_3 double precision,ask_price_3 double precision,ask_volume_3 double precision,
        bid_price_4 double precision,bid_volume_4 double precision,ask_price_4 double precision,ask_volume_4 double precision,
        bid_price_5 double precision,bid_volume_5 double precision,ask_price_5 double precision,ask_volume_5 double precision,raw_data jsonb
    )
    LEFT JOIN stock_daily sd ON sd.upload_run_id=p_upload_run_id AND sd.trade_date=x.snapshot_date AND sd.stock_code=upper(trim(x.stock_code))
    WHERE x.snapshot_date IS NOT NULL AND btrim(x.stock_code) <> ''
    ON CONFLICT (upload_run_id,snapshot_date,snapshot_time,stock_code) DO UPDATE SET
        stock_daily_id=EXCLUDED.stock_daily_id,bid_price_1=EXCLUDED.bid_price_1,bid_volume_1=EXCLUDED.bid_volume_1,
        ask_price_1=EXCLUDED.ask_price_1,ask_volume_1=EXCLUDED.ask_volume_1,bid_price_2=EXCLUDED.bid_price_2,bid_volume_2=EXCLUDED.bid_volume_2,
        ask_price_2=EXCLUDED.ask_price_2,ask_volume_2=EXCLUDED.ask_volume_2,bid_price_3=EXCLUDED.bid_price_3,bid_volume_3=EXCLUDED.bid_volume_3,
        ask_price_3=EXCLUDED.ask_price_3,ask_volume_3=EXCLUDED.ask_volume_3,bid_price_4=EXCLUDED.bid_price_4,bid_volume_4=EXCLUDED.bid_volume_4,
        ask_price_4=EXCLUDED.ask_price_4,ask_volume_4=EXCLUDED.ask_volume_4,bid_price_5=EXCLUDED.bid_price_5,bid_volume_5=EXCLUDED.bid_volume_5,
        ask_price_5=EXCLUDED.ask_price_5,ask_volume_5=EXCLUDED.ask_volume_5,raw_data=EXCLUDED.raw_data;
    GET DIAGNOSTICS v_orderbook_count = ROW_COUNT;

    INSERT INTO technical_indicator_snapshot (
        upload_run_id,stock_daily_id,trade_date,stock_code,sma20,sma50,sma200,volume_ma20,volume_ratio,rsi14,atr14,
        horizons_available,history_days,technical_status
    )
    SELECT p_upload_run_id,sd.id,x.trade_date,upper(trim(x.stock_code)),x.sma20,x.sma50,x.sma200,x.volume_ma20,x.volume_ratio,x.rsi14,x.atr14,
        x.horizons_available,x.history_days,x.technical_status
    FROM jsonb_to_recordset(COALESCE(p_technical,'[]'::jsonb)) AS x(
        trade_date date,stock_code text,sma20 double precision,sma50 double precision,sma200 double precision,
        volume_ma20 double precision,volume_ratio double precision,rsi14 double precision,atr14 double precision,
        horizons_available integer,history_days integer,technical_status text
    )
    LEFT JOIN stock_daily sd ON sd.upload_run_id=p_upload_run_id AND sd.trade_date=x.trade_date AND sd.stock_code=upper(trim(x.stock_code))
    WHERE x.trade_date IS NOT NULL AND btrim(x.stock_code) <> ''
    ON CONFLICT (upload_run_id,trade_date,stock_code) DO UPDATE SET
        stock_daily_id=EXCLUDED.stock_daily_id,sma20=EXCLUDED.sma20,sma50=EXCLUDED.sma50,sma200=EXCLUDED.sma200,
        volume_ma20=EXCLUDED.volume_ma20,volume_ratio=EXCLUDED.volume_ratio,rsi14=EXCLUDED.rsi14,atr14=EXCLUDED.atr14,
        horizons_available=EXCLUDED.horizons_available,history_days=EXCLUDED.history_days,technical_status=EXCLUDED.technical_status;
    GET DIAGNOSTICS v_technical_count = ROW_COUNT;

    RETURN jsonb_build_object('upload_run_id',p_upload_run_id,'ledger_rows',v_ledger_count,'stock_rows',v_stock_count,'orderbook_rows',v_orderbook_count,'technical_rows',v_technical_count);
END;
$$;

REVOKE ALL ON FUNCTION persist_bei_historical_batch(uuid,jsonb,jsonb,jsonb,jsonb) FROM PUBLIC;
REVOKE ALL ON FUNCTION persist_bei_historical_batch(uuid,jsonb,jsonb,jsonb,jsonb) FROM anon;
REVOKE ALL ON FUNCTION persist_bei_historical_batch(uuid,jsonb,jsonb,jsonb,jsonb) FROM authenticated;
GRANT EXECUTE ON FUNCTION persist_bei_historical_batch(uuid,jsonb,jsonb,jsonb,jsonb) TO service_role;

COMMENT ON FUNCTION persist_bei_historical_batch(uuid,jsonb,jsonb,jsonb,jsonb)
IS 'Atomic/idempotent server-side persistence of one BEI upload file into historical Supabase tables.';
