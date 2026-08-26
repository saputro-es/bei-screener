-- Fix historical persistence RPC issues: duplicate bid_volume_4 declaration and
-- the protected canonical baseline gate. Historical data is preserved.

CREATE OR REPLACE FUNCTION public.persist_upload_batch(p_run jsonb, p_files jsonb, p_daily jsonb, p_orderbook jsonb)
RETURNS jsonb LANGUAGE plpgsql SECURITY DEFINER SET search_path=public AS $$
DECLARE
 v_run_id uuid; v_existing uuid; v_batch_key text;
 v_daily_rows integer:=0; v_orderbook_rows integer:=0; v_ledger_rows integer:=0;
BEGIN
 v_batch_key:=NULLIF(trim(p_run->>'batch_key'),'');
 SELECT id INTO v_existing FROM upload_runs WHERE batch_key=v_batch_key LIMIT 1;
 IF v_existing IS NOT NULL THEN RETURN jsonb_build_object('saved',true,'duplicate',true,'upload_run_id',v_existing,'ledger_rows',0,'daily_rows',0,'orderbook_rows',0); END IF;
 INSERT INTO upload_runs(source,note,batch_key) VALUES (COALESCE(NULLIF(p_run->>'source',''),'app_upload'),p_run->>'note',v_batch_key) RETURNING id INTO v_run_id;
 INSERT INTO upload_ledger(upload_run_id,sha256,filename,size_bytes,rows_read,rows_saved,metadata)
 SELECT v_run_id,lower(x.sha256),x.filename,x.size_bytes,x.rows_read,x.rows_saved,COALESCE(x.metadata,'{}'::jsonb)
 FROM jsonb_to_recordset(COALESCE(p_files,'[]'::jsonb)) AS x(sha256 text,filename text,size_bytes bigint,rows_read integer,rows_saved integer,metadata jsonb);
 GET DIAGNOSTICS v_ledger_rows=ROW_COUNT;
 INSERT INTO stock_daily(upload_run_id,trade_date,stock_code,company_name,open_price,high_price,low_price,close_price,volume,value,frequency,foreign_sell,foreign_buy,bid_price_1,bid_volume_1,ask_price_1,ask_volume_1,bid_price_2,bid_volume_2,ask_price_2,ask_volume_2,bid_price_3,bid_volume_3,ask_price_3,ask_volume_3,bid_price_4,bid_volume_4,ask_price_4,ask_volume_4,bid_price_5,bid_volume_5,ask_price_5,ask_volume_5,raw_data)
 SELECT v_run_id,x.trade_date,x.stock_code,x.company_name,x.open_price,x.high_price,x.low_price,x.close_price,x.volume,x.value,x.frequency,x.foreign_sell,x.foreign_buy,x.bid_price_1,x.bid_volume_1,x.ask_price_1,x.ask_volume_1,x.bid_price_2,x.bid_volume_2,x.ask_price_2,x.ask_volume_2,x.bid_price_3,x.bid_volume_3,x.ask_price_3,x.ask_volume_3,x.bid_price_4,x.bid_volume_4,x.ask_price_4,x.ask_volume_4,x.bid_price_5,x.bid_volume_5,x.ask_price_5,x.ask_volume_5,x.raw_data
 FROM jsonb_to_recordset(COALESCE(p_daily,'[]'::jsonb)) AS x(trade_date date,stock_code text,company_name text,open_price double precision,high_price double precision,low_price double precision,close_price double precision,volume double precision,value double precision,frequency double precision,foreign_sell double precision,foreign_buy double precision,bid_price_1 double precision,bid_volume_1 double precision,ask_price_1 double precision,ask_volume_1 double precision,bid_price_2 double precision,bid_volume_2 double precision,ask_price_2 double precision,ask_volume_2 double precision,bid_price_3 double precision,bid_volume_3 double precision,ask_price_3 double precision,ask_volume_3 double precision,bid_price_4 double precision,bid_volume_4 double precision,ask_price_4 double precision,ask_volume_4 double precision,bid_price_5 double precision,bid_volume_5 double precision,ask_price_5 double precision,ask_volume_5 double precision,raw_data jsonb)
 ON CONFLICT DO NOTHING;
 GET DIAGNOSTICS v_daily_rows=ROW_COUNT;
 PERFORM set_config('app.canonical_promotion','1',true);
 INSERT INTO canonical_stock_daily SELECT * FROM stock_daily WHERE upload_run_id=v_run_id;
 INSERT INTO orderbook_snapshot(upload_run_id,stock_daily_id,snapshot_date,snapshot_time,stock_code,bid_price_1,bid_volume_1,ask_price_1,ask_volume_1,bid_price_2,bid_volume_2,ask_price_2,ask_volume_2,bid_price_3,bid_volume_3,ask_price_3,ask_volume_3,bid_price_4,bid_volume_4,ask_price_4,ask_volume_4,bid_price_5,bid_volume_5,ask_price_5,ask_volume_5,raw_data)
 SELECT v_run_id,sd.id,x.snapshot_date,x.snapshot_time,x.stock_code,x.bid_price_1,x.bid_volume_1,x.ask_price_1,x.ask_volume_1,x.bid_price_2,x.bid_volume_2,x.ask_price_2,x.ask_volume_2,x.bid_price_3,x.bid_volume_3,x.ask_price_3,x.ask_volume_3,x.bid_price_4,x.bid_volume_4,x.ask_price_4,x.ask_volume_4,x.bid_price_5,x.bid_volume_5,x.ask_price_5,x.ask_volume_5,x.raw_data
 FROM jsonb_to_recordset(COALESCE(p_orderbook,'[]'::jsonb)) AS x(snapshot_date date,snapshot_time time,stock_code text,bid_price_1 double precision,bid_volume_1 double precision,ask_price_1 double precision,ask_volume_1 double precision,bid_price_2 double precision,bid_volume_2 double precision,ask_price_2 double precision,ask_volume_2 double precision,bid_price_3 double precision,bid_volume_3 double precision,ask_price_3 double precision,ask_volume_3 double precision,bid_price_4 double precision,bid_volume_4 double precision,ask_price_4 double precision,ask_volume_4 double precision,bid_price_5 double precision,bid_volume_5 double precision,ask_price_5 double precision,ask_volume_5 double precision,raw_data jsonb)
 LEFT JOIN stock_daily sd ON sd.upload_run_id=v_run_id AND sd.trade_date=x.snapshot_date AND sd.stock_code=x.stock_code
 ON CONFLICT DO NOTHING;
 GET DIAGNOSTICS v_orderbook_rows=ROW_COUNT;
 PERFORM set_config('app.canonical_promotion','0',true);
 RETURN jsonb_build_object('saved',true,'duplicate',false,'upload_run_id',v_run_id,'ledger_rows',v_ledger_rows,'daily_rows',v_daily_rows,'orderbook_rows',v_orderbook_rows);
EXCEPTION WHEN unique_violation THEN
 SELECT id INTO v_existing FROM upload_runs WHERE batch_key=v_batch_key LIMIT 1;
 IF v_existing IS NOT NULL THEN RETURN jsonb_build_object('saved',true,'duplicate',true,'upload_run_id',v_existing,'ledger_rows',0,'daily_rows',0,'orderbook_rows',0); END IF;
 RAISE;
END;
$$;

GRANT EXECUTE ON FUNCTION public.persist_upload_batch(jsonb,jsonb,jsonb,jsonb) TO service_role;
