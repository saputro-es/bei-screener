-- Canonical remains immutable to direct table writes.
-- Only the validated upload RPC may promote newly persisted operational rows.

CREATE OR REPLACE FUNCTION public.prevent_canonical_mutation()
RETURNS trigger
LANGUAGE plpgsql
AS $$
BEGIN
    IF current_setting('app.canonical_promotion', true) = '1' THEN
        RETURN CASE WHEN TG_OP = 'DELETE' THEN OLD ELSE NEW END;
    END IF;
    RAISE EXCEPTION 'Canonical analysis baseline is LOCKED; mutation is not allowed.';
END;
$$;

CREATE OR REPLACE FUNCTION public.promote_canonical_after_validated_upload()
RETURNS jsonb
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = public, pg_temp
AS $$
DECLARE
    v_canonical_latest date;
    v_operational_latest date;
    v_daily_inserted integer := 0;
    v_orderbook_inserted integer := 0;
BEGIN
    SELECT max(trade_date) INTO v_canonical_latest FROM public.canonical_stock_daily;
    SELECT max(trade_date) INTO v_operational_latest FROM public.stock_daily;
    IF v_operational_latest IS NULL THEN
        RETURN jsonb_build_object('promoted', false, 'reason', 'operational_empty');
    END IF;
    IF v_canonical_latest IS NOT NULL AND v_operational_latest < v_canonical_latest THEN
        RAISE EXCEPTION 'Operational dataset % is older than canonical baseline %', v_operational_latest, v_canonical_latest;
    END IF;

    PERFORM set_config('app.canonical_promotion', '1', true);

    INSERT INTO public.canonical_stock_daily (
        id, upload_run_id, trade_date, stock_code, company_name, open_price, high_price, low_price, close_price, volume, value, frequency, foreign_sell, foreign_buy, net_foreign_buy,
        bid_price_1, bid_volume_1, ask_price_1, ask_volume_1, bid_price_2, bid_volume_2, ask_price_2, ask_volume_2,
        bid_price_3, bid_volume_3, ask_price_3, ask_volume_3, bid_price_4, bid_volume_4, ask_price_4, ask_volume_4,
        bid_price_5, bid_volume_5, ask_price_5, ask_volume_5, raw_data)
    SELECT s.id, s.upload_run_id, s.trade_date, btrim(s.stock_code), s.company_name, s.open_price, s.high_price, s.low_price, s.close_price, s.volume, s.value, s.frequency, s.foreign_sell, s.foreign_buy, s.net_foreign_buy,
        s.bid_price_1, s.bid_volume_1, s.ask_price_1, s.ask_volume_1, s.bid_price_2, s.bid_volume_2, s.ask_price_2, s.ask_volume_2,
        s.bid_price_3, s.bid_volume_3, s.ask_price_3, s.ask_volume_3, s.bid_price_4, s.bid_volume_4, s.ask_price_4, s.ask_volume_4,
        s.bid_price_5, s.bid_volume_5, s.ask_price_5, s.ask_volume_5, s.raw_data
    FROM public.stock_daily s
    WHERE (v_canonical_latest IS NULL OR s.trade_date > v_canonical_latest)
      AND NOT EXISTS (SELECT 1 FROM public.canonical_stock_daily c WHERE c.trade_date = s.trade_date AND c.stock_code = btrim(s.stock_code));
    GET DIAGNOSTICS v_daily_inserted = ROW_COUNT;

    INSERT INTO public.canonical_orderbook_snapshot (
        id, upload_run_id, stock_daily_id, snapshot_date, snapshot_time, stock_code,
        bid_price_1, bid_volume_1, ask_price_1, ask_volume_1, bid_price_2, bid_volume_2, ask_price_2, ask_volume_2,
        bid_price_3, bid_volume_3, ask_price_3, ask_volume_3, bid_price_4, bid_volume_4, ask_price_4, ask_volume_4,
        bid_price_5, bid_volume_5, ask_price_5, ask_volume_5, raw_data)
    SELECT o.id, o.upload_run_id, c.id, o.snapshot_date, coalesce(o.snapshot_time, '00:00:00'::time), btrim(o.stock_code),
        o.bid_price_1, o.bid_volume_1, o.ask_price_1, o.ask_volume_1, o.bid_price_2, o.bid_volume_2, o.ask_price_2, o.ask_volume_2,
        o.bid_price_3, o.bid_volume_3, o.ask_price_3, o.ask_volume_3, o.bid_price_4, o.bid_volume_4, o.ask_price_4, o.ask_volume_4,
        o.bid_price_5, o.bid_volume_5, o.ask_price_5, o.ask_volume_5, o.raw_data
    FROM public.orderbook_snapshot o
    JOIN public.canonical_stock_daily c ON c.trade_date = o.snapshot_date AND c.stock_code = btrim(o.stock_code)
    WHERE (v_canonical_latest IS NULL OR o.snapshot_date > v_canonical_latest)
      AND NOT EXISTS (SELECT 1 FROM public.canonical_orderbook_snapshot co WHERE co.snapshot_date = o.snapshot_date AND co.snapshot_time = coalesce(o.snapshot_time, '00:00:00'::time) AND co.stock_code = btrim(o.stock_code));
    GET DIAGNOSTICS v_orderbook_inserted = ROW_COUNT;

    RETURN jsonb_build_object('promoted', true, 'canonical_latest_before', v_canonical_latest, 'operational_latest', v_operational_latest, 'daily_inserted', v_daily_inserted, 'orderbook_inserted', v_orderbook_inserted);
END;
$$;

REVOKE ALL ON FUNCTION public.promote_canonical_after_validated_upload() FROM PUBLIC;
REVOKE ALL ON FUNCTION public.promote_canonical_after_validated_upload() FROM anon;
REVOKE ALL ON FUNCTION public.promote_canonical_after_validated_upload() FROM authenticated;
GRANT EXECUTE ON FUNCTION public.promote_canonical_after_validated_upload() TO service_role;

CREATE OR REPLACE FUNCTION public.persist_upload_batch(p_run jsonb, p_files jsonb, p_daily jsonb, p_orderbook jsonb)
RETURNS jsonb
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = public, pg_temp
SET statement_timeout = '15min'
AS $$
DECLARE
    v_run_id uuid; v_existing_run_id uuid; v_batch_key text; v_file_count integer;
    v_ledger_count integer := 0; v_daily_count integer := 0; v_orderbook_count integer := 0; v_promotion jsonb;
BEGIN
    IF jsonb_typeof(COALESCE(p_files,'[]'::jsonb)) <> 'array' OR jsonb_array_length(COALESCE(p_files,'[]'::jsonb))=0 THEN RAISE EXCEPTION 'At least one upload file is required'; END IF;
    IF jsonb_typeof(COALESCE(p_daily,'[]'::jsonb)) <> 'array' OR jsonb_array_length(COALESCE(p_daily,'[]'::jsonb))=0 THEN RAISE EXCEPTION 'At least one valid daily row is required'; END IF;
    IF jsonb_typeof(COALESCE(p_orderbook,'[]'::jsonb)) <> 'array' THEN RAISE EXCEPTION 'Orderbook payload must be an array'; END IF;
    v_batch_key:=lower(NULLIF(btrim(p_run->>'batch_key'),''));
    IF v_batch_key IS NULL OR length(v_batch_key)<>64 OR v_batch_key !~ '^[0-9a-f]{64}$' THEN RAISE EXCEPTION 'Invalid batch_key'; END IF;
    v_file_count:=jsonb_array_length(p_files);
    SELECT id INTO v_existing_run_id FROM public.upload_runs WHERE batch_key=v_batch_key LIMIT 1;
    IF v_existing_run_id IS NOT NULL THEN RETURN jsonb_build_object('upload_run_id',v_existing_run_id,'ledger_rows',0,'daily_rows',0,'orderbook_rows',0,'duplicate',true); END IF;
    INSERT INTO public.upload_runs(source,note,batch_key) VALUES(COALESCE(NULLIF(p_run->>'source',''),'app_upload'),p_run->>'note',v_batch_key) ON CONFLICT(batch_key) DO NOTHING RETURNING id INTO v_run_id;
    IF v_run_id IS NULL THEN SELECT id INTO v_existing_run_id FROM public.upload_runs WHERE batch_key=v_batch_key LIMIT 1; RETURN jsonb_build_object('upload_run_id',v_existing_run_id,'ledger_rows',0,'daily_rows',0,'orderbook_rows',0,'duplicate',true); END IF;
    INSERT INTO public.upload_ledger(upload_run_id,sha256,filename,size_bytes,rows_read,rows_saved,metadata)
    SELECT v_run_id,lower(f.sha256),btrim(f.filename),f.size_bytes,COALESCE(f.rows_read,0),COALESCE(f.rows_saved,0),COALESCE(f.metadata,'{}'::jsonb)
    FROM jsonb_to_recordset(p_files) AS f(sha256 text,filename text,size_bytes bigint,rows_read integer,rows_saved integer,metadata jsonb)
    WHERE f.sha256 ~ '^[0-9a-fA-F]{64}$' AND NULLIF(btrim(f.filename),'') IS NOT NULL AND f.size_bytes>=0 AND COALESCE(f.rows_read,0)>=0 AND COALESCE(f.rows_saved,0)>=0;
    GET DIAGNOSTICS v_ledger_count=ROW_COUNT; IF v_ledger_count<>v_file_count THEN RAISE EXCEPTION 'Invalid file metadata or duplicate upload hash detected; batch rolled back'; END IF;
    INSERT INTO public.stock_daily(upload_run_id,trade_date,stock_code,company_name,open_price,high_price,low_price,close_price,volume,value,frequency,foreign_sell,foreign_buy,bid_price_1,bid_volume_1,ask_price_1,ask_volume_1,bid_price_2,bid_volume_2,ask_price_2,ask_volume_2,bid_price_3,bid_volume_3,ask_price_3,ask_volume_3,bid_price_4,bid_volume_4,ask_price_4,ask_volume_4,bid_price_5,bid_volume_5,ask_price_5,ask_volume_5,raw_data)
    SELECT v_run_id,d.trade_date,btrim(d.stock_code),d.company_name,d.open_price,d.high_price,d.low_price,d.close_price,d.volume,d.value,d.frequency,d.foreign_sell,d.foreign_buy,d.bid_price_1,d.bid_volume_1,d.ask_price_1,d.ask_volume_1,d.bid_price_2,d.bid_volume_2,d.ask_price_2,d.ask_volume_2,d.bid_price_3,d.bid_volume_3,d.ask_price_3,d.ask_volume_3,d.bid_price_4,d.bid_volume_4,d.ask_price_4,d.ask_volume_4,d.bid_price_5,d.bid_volume_5,d.ask_price_5,d.ask_volume_5,d.raw_data
    FROM jsonb_to_recordset(p_daily) AS d(trade_date date,stock_code text,company_name text,open_price double precision,high_price double precision,low_price double precision,close_price double precision,volume double precision,value double precision,frequency double precision,foreign_sell double precision,foreign_buy double precision,bid_price_1 double precision,bid_volume_1 double precision,ask_price_1 double precision,ask_volume_1 double precision,bid_price_2 double precision,bid_volume_2 double precision,ask_price_2 double precision,ask_volume_2 double precision,bid_price_3 double precision,bid_volume_3 double precision,ask_price_3 double precision,bid_volume_3 double precision,ask_price_3 double precision,bid_price_4 double precision,bid_volume_4 double precision,ask_price_4 double precision,ask_volume_4 double precision,bid_price_5 double precision,bid_volume_5 double precision,ask_price_5 double precision,ask_volume_5 double precision,raw_data jsonb)
    WHERE d.trade_date IS NOT NULL AND NULLIF(btrim(d.stock_code),'') IS NOT NULL;
    GET DIAGNOSTICS v_daily_count=ROW_COUNT; IF v_daily_count=0 THEN RAISE EXCEPTION 'No valid daily rows supplied'; END IF;
    INSERT INTO public.orderbook_snapshot(upload_run_id,snapshot_date,snapshot_time,stock_code,bid_price_1,bid_volume_1,ask_price_1,ask_volume_1,bid_price_2,bid_volume_2,ask_price_2,ask_volume_2,bid_price_3,bid_volume_3,ask_price_3,ask_volume_3,bid_price_4,bid_volume_4,ask_price_4,ask_volume_4,bid_price_5,bid_volume_5,ask_price_5,ask_volume_5,raw_data)
    SELECT v_run_id,o.snapshot_date,COALESCE(o.snapshot_time,'00:00:00'::time),btrim(o.stock_code),o.bid_price_1,o.bid_volume_1,o.ask_price_1,o.ask_volume_1,o.bid_price_2,o.bid_volume_2,o.ask_price_2,o.ask_volume_2,o.bid_price_3,o.bid_volume_3,o.ask_price_3,o.ask_volume_3,o.bid_price_4,o.bid_volume_4,o.ask_price_4,o.ask_volume_4,o.bid_price_5,o.bid_volume_5,o.ask_price_5,o.ask_volume_5,o.raw_data
    FROM jsonb_to_recordset(p_orderbook) AS o(snapshot_date date,snapshot_time time,stock_code text,bid_price_1 double precision,bid_volume_1 double precision,ask_price_1 double precision,ask_volume_1 double precision,bid_price_2 double precision,bid_volume_2 double precision,ask_price_2 double precision,ask_volume_2 double precision,bid_price_3 double precision,bid_volume_3 double precision,ask_price_3 double precision,ask_volume_3 double precision,bid_price_4 double precision,bid_volume_4 double precision,ask_price_4 double precision,ask_volume_4 double precision,bid_price_5 double precision,bid_volume_5 double precision,ask_price_5 double precision,ask_volume_5 double precision,raw_data jsonb)
    WHERE o.snapshot_date IS NOT NULL AND NULLIF(btrim(o.stock_code),'') IS NOT NULL;
    GET DIAGNOSTICS v_orderbook_count=ROW_COUNT;
    v_promotion := public.promote_canonical_after_validated_upload();
    RETURN jsonb_build_object('upload_run_id',v_run_id,'ledger_rows',v_ledger_count,'daily_rows',v_daily_count,'orderbook_rows',v_orderbook_count,'duplicate',false,'canonical_promotion',v_promotion);
END;
$$;

REVOKE ALL ON FUNCTION public.persist_upload_batch(jsonb,jsonb,jsonb,jsonb) FROM PUBLIC;
REVOKE ALL ON FUNCTION public.persist_upload_batch(jsonb,jsonb,jsonb,jsonb) FROM anon;
REVOKE ALL ON FUNCTION public.persist_upload_batch(jsonb,jsonb,jsonb,jsonb) FROM authenticated;
GRANT EXECUTE ON FUNCTION public.persist_upload_batch(jsonb,jsonb,jsonb,jsonb) TO service_role;
