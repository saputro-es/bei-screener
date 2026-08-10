-- Fix multi-file persistence failures caused by PostgreSQL jsonb_to_recordset
-- field-reference/schema-plan resolution (e.g. d.ask_volume_3).
-- The upload remains atomic and canonical promotion remains inside the same RPC.

CREATE OR REPLACE FUNCTION public.persist_upload_batch(p_run jsonb,p_files jsonb,p_daily jsonb,p_orderbook jsonb)
RETURNS jsonb
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = public, pg_temp
SET statement_timeout = '15min'
AS $$
DECLARE
    v_run_id uuid;
    v_existing_run_id uuid;
    v_batch_key text;
    v_file_count integer;
    v_ledger_count integer := 0;
    v_daily_count integer := 0;
    v_orderbook_count integer := 0;
    v_promotion jsonb;
BEGIN
    IF jsonb_typeof(COALESCE(p_files,'[]'::jsonb)) <> 'array' OR jsonb_array_length(COALESCE(p_files,'[]'::jsonb))=0 THEN RAISE EXCEPTION 'At least one upload file is required'; END IF;
    IF jsonb_typeof(COALESCE(p_daily,'[]'::jsonb)) <> 'array' OR jsonb_array_length(COALESCE(p_daily,'[]'::jsonb))=0 THEN RAISE EXCEPTION 'At least one valid daily row is required'; END IF;
    IF jsonb_typeof(COALESCE(p_orderbook,'[]'::jsonb)) <> 'array' THEN RAISE EXCEPTION 'Orderbook payload must be an array'; END IF;
    v_batch_key := lower(NULLIF(btrim(p_run->>'batch_key'),''));
    IF v_batch_key IS NULL OR length(v_batch_key)<>64 OR v_batch_key !~ '^[0-9a-f]{64}$' THEN RAISE EXCEPTION 'Invalid batch_key'; END IF;
    v_file_count := jsonb_array_length(p_files);

    SELECT id INTO v_existing_run_id FROM public.upload_runs WHERE batch_key=v_batch_key LIMIT 1;
    IF v_existing_run_id IS NOT NULL THEN
        RETURN jsonb_build_object('upload_run_id',v_existing_run_id,'ledger_rows',0,'daily_rows',0,'orderbook_rows',0,'duplicate',true);
    END IF;

    INSERT INTO public.upload_runs(source,note,batch_key)
    VALUES(COALESCE(NULLIF(p_run->>'source',''),'app_upload'),p_run->>'note',v_batch_key)
    ON CONFLICT(batch_key) DO NOTHING RETURNING id INTO v_run_id;
    IF v_run_id IS NULL THEN
        SELECT id INTO v_existing_run_id FROM public.upload_runs WHERE batch_key=v_batch_key LIMIT 1;
        RETURN jsonb_build_object('upload_run_id',v_existing_run_id,'ledger_rows',0,'daily_rows',0,'orderbook_rows',0,'duplicate',true);
    END IF;

    INSERT INTO public.upload_ledger(upload_run_id,sha256,filename,size_bytes,rows_read,rows_saved,metadata)
    SELECT v_run_id,lower(f.sha256),btrim(f.filename),f.size_bytes,COALESCE(f.rows_read,0),COALESCE(f.rows_saved,0),COALESCE(f.metadata,'{}'::jsonb)
    FROM jsonb_to_recordset(p_files) AS f(sha256 text,filename text,size_bytes bigint,rows_read integer,rows_saved integer,metadata jsonb)
    WHERE f.sha256 ~ '^[0-9a-fA-F]{64}$' AND NULLIF(btrim(f.filename),'') IS NOT NULL AND f.size_bytes>=0 AND COALESCE(f.rows_read,0)>=0 AND COALESCE(f.rows_saved,0)>=0;
    GET DIAGNOSTICS v_ledger_count=ROW_COUNT;
    IF v_ledger_count<>v_file_count THEN RAISE EXCEPTION 'Invalid file metadata or duplicate upload hash detected; batch rolled back'; END IF;

    -- JSON operators avoid recordset field-resolution failures while preserving types.
    INSERT INTO public.stock_daily(upload_run_id,trade_date,stock_code,company_name,open_price,high_price,low_price,close_price,volume,value,frequency,foreign_sell,foreign_buy,bid_price_1,bid_volume_1,ask_price_1,ask_volume_1,bid_price_2,bid_volume_2,ask_price_2,ask_volume_2,bid_price_3,bid_volume_3,ask_price_3,ask_volume_3,bid_price_4,bid_volume_4,ask_price_4,ask_volume_4,bid_price_5,bid_volume_5,ask_price_5,ask_volume_5,raw_data)
    SELECT v_run_id,NULLIF(x->>'trade_date','')::date,btrim(x->>'stock_code'),x->>'company_name',NULLIF(x->>'open_price','')::double precision,NULLIF(x->>'high_price','')::double precision,NULLIF(x->>'low_price','')::double precision,NULLIF(x->>'close_price','')::double precision,NULLIF(x->>'volume','')::double precision,NULLIF(x->>'value','')::double precision,NULLIF(x->>'frequency','')::double precision,NULLIF(x->>'foreign_sell','')::double precision,NULLIF(x->>'foreign_buy','')::double precision,NULLIF(x->>'bid_price_1','')::double precision,NULLIF(x->>'bid_volume_1','')::double precision,NULLIF(x->>'ask_price_1','')::double precision,NULLIF(x->>'ask_volume_1','')::double precision,NULLIF(x->>'bid_price_2','')::double precision,NULLIF(x->>'bid_volume_2','')::double precision,NULLIF(x->>'ask_price_2','')::double precision,NULLIF(x->>'ask_volume_2','')::double precision,NULLIF(x->>'bid_price_3','')::double precision,NULLIF(x->>'bid_volume_3','')::double precision,NULLIF(x->>'ask_price_3','')::double precision,NULLIF(x->>'ask_volume_3','')::double precision,NULLIF(x->>'bid_price_4','')::double precision,NULLIF(x->>'bid_volume_4','')::double precision,NULLIF(x->>'ask_price_4','')::double precision,NULLIF(x->>'ask_volume_4','')::double precision,NULLIF(x->>'bid_price_5','')::double precision,NULLIF(x->>'bid_volume_5','')::double precision,NULLIF(x->>'ask_price_5','')::double precision,NULLIF(x->>'ask_volume_5','')::double precision,x
    FROM jsonb_array_elements(p_daily) AS e(x)
    WHERE NULLIF(x->>'trade_date','') IS NOT NULL AND NULLIF(btrim(x->>'stock_code'),'') IS NOT NULL;
    GET DIAGNOSTICS v_daily_count=ROW_COUNT;
    IF v_daily_count=0 THEN RAISE EXCEPTION 'No valid daily rows supplied'; END IF;

    INSERT INTO public.orderbook_snapshot(upload_run_id,snapshot_date,snapshot_time,stock_code,bid_price_1,bid_volume_1,ask_price_1,ask_volume_1,bid_price_2,bid_volume_2,ask_price_2,ask_volume_2,bid_price_3,bid_volume_3,ask_price_3,ask_volume_3,bid_price_4,bid_volume_4,ask_price_4,ask_volume_4,bid_price_5,bid_volume_5,ask_price_5,ask_volume_5,raw_data)
    SELECT v_run_id,NULLIF(x->>'snapshot_date','')::date,COALESCE(NULLIF(x->>'snapshot_time','')::time,'00:00:00'::time),btrim(x->>'stock_code'),NULLIF(x->>'bid_price_1','')::double precision,NULLIF(x->>'bid_volume_1','')::double precision,NULLIF(x->>'ask_price_1','')::double precision,NULLIF(x->>'ask_volume_1','')::double precision,NULLIF(x->>'bid_price_2','')::double precision,NULLIF(x->>'bid_volume_2','')::double precision,NULLIF(x->>'ask_price_2','')::double precision,NULLIF(x->>'ask_volume_2','')::double precision,NULLIF(x->>'bid_price_3','')::double precision,NULLIF(x->>'bid_volume_3','')::double precision,NULLIF(x->>'ask_price_3','')::double precision,NULLIF(x->>'ask_volume_3','')::double precision,NULLIF(x->>'bid_price_4','')::double precision,NULLIF(x->>'bid_volume_4','')::double precision,NULLIF(x->>'ask_price_4','')::double precision,NULLIF(x->>'ask_volume_4','')::double precision,NULLIF(x->>'bid_price_5','')::double precision,NULLIF(x->>'bid_volume_5','')::double precision,NULLIF(x->>'ask_price_5','')::double precision,NULLIF(x->>'ask_volume_5','')::double precision,x
    FROM jsonb_array_elements(p_orderbook) AS e(x)
    WHERE NULLIF(x->>'snapshot_date','') IS NOT NULL AND NULLIF(btrim(x->>'stock_code'),'') IS NOT NULL;
    GET DIAGNOSTICS v_orderbook_count=ROW_COUNT;

    v_promotion := public.promote_canonical_after_validated_upload();
    RETURN jsonb_build_object('upload_run_id',v_run_id,'ledger_rows',v_ledger_count,'daily_rows',v_daily_count,'orderbook_rows',v_orderbook_count,'duplicate',false,'canonical_promotion',v_promotion);
END;
$$;

REVOKE ALL ON FUNCTION public.persist_upload_batch(jsonb,jsonb,jsonb,jsonb) FROM PUBLIC;
REVOKE ALL ON FUNCTION public.persist_upload_batch(jsonb,jsonb,jsonb,jsonb) FROM anon;
REVOKE ALL ON FUNCTION public.persist_upload_batch(jsonb,jsonb,jsonb,jsonb) FROM authenticated;
GRANT EXECUTE ON FUNCTION public.persist_upload_batch(jsonb,jsonb,jsonb,jsonb) TO service_role;
