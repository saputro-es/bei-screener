create or replace function public.repair_historical_missing_fields(p_daily jsonb, p_orderbook jsonb)
returns jsonb
language plpgsql
security definer
set search_path = public, pg_temp
as $$
declare
  v_daily_updated integer := 0;
  v_orderbook_updated integer := 0;
begin
  if jsonb_typeof(coalesce(p_daily, '[]'::jsonb)) <> 'array' then
    raise exception 'Daily repair payload must be an array';
  end if;
  if jsonb_typeof(coalesce(p_orderbook, '[]'::jsonb)) <> 'array' then
    raise exception 'Orderbook repair payload must be an array';
  end if;

  with incoming as (
    select *
    from jsonb_to_recordset(p_daily) as d(
      trade_date date,
      stock_code text,
      company_name text,
      open_price double precision,
      high_price double precision,
      low_price double precision,
      close_price double precision,
      volume double precision,
      value double precision,
      frequency double precision,
      foreign_sell double precision,
      foreign_buy double precision,
      bid_price_1 double precision,
      bid_volume_1 double precision,
      ask_price_1 double precision,
      ask_volume_1 double precision,
      bid_price_2 double precision,
      bid_volume_2 double precision,
      ask_price_2 double precision,
      ask_volume_2 double precision,
      bid_price_3 double precision,
      bid_volume_3 double precision,
      ask_price_3 double precision,
      ask_volume_3 double precision,
      bid_price_4 double precision,
      bid_volume_4 double precision,
      ask_price_4 double precision,
      ask_volume_4 double precision,
      bid_price_5 double precision,
      bid_volume_5 double precision,
      ask_price_5 double precision,
      ask_volume_5 double precision,
      raw_data jsonb
    )
    where trade_date is not null and nullif(btrim(stock_code), '') is not null
  )
  update public.stock_daily s
  set
    company_name = coalesce(s.company_name, i.company_name),
    open_price = coalesce(s.open_price, i.open_price),
    high_price = coalesce(s.high_price, i.high_price),
    low_price = coalesce(s.low_price, i.low_price),
    close_price = coalesce(s.close_price, i.close_price),
    volume = coalesce(s.volume, i.volume),
    value = coalesce(s.value, i.value),
    frequency = coalesce(s.frequency, i.frequency),
    foreign_sell = coalesce(s.foreign_sell, i.foreign_sell),
    foreign_buy = coalesce(s.foreign_buy, i.foreign_buy),
    bid_price_1 = coalesce(s.bid_price_1, i.bid_price_1),
    bid_volume_1 = coalesce(s.bid_volume_1, i.bid_volume_1),
    ask_price_1 = coalesce(s.ask_price_1, i.ask_price_1),
    ask_volume_1 = coalesce(s.ask_volume_1, i.ask_volume_1),
    bid_price_2 = coalesce(s.bid_price_2, i.bid_price_2),
    bid_volume_2 = coalesce(s.bid_volume_2, i.bid_volume_2),
    ask_price_2 = coalesce(s.ask_price_2, i.ask_price_2),
    ask_volume_2 = coalesce(s.ask_volume_2, i.ask_volume_2),
    bid_price_3 = coalesce(s.bid_price_3, i.bid_price_3),
    bid_volume_3 = coalesce(s.bid_volume_3, i.bid_volume_3),
    ask_price_3 = coalesce(s.ask_price_3, i.ask_price_3),
    ask_volume_3 = coalesce(s.ask_volume_3, i.ask_volume_3),
    bid_price_4 = coalesce(s.bid_price_4, i.bid_price_4),
    bid_volume_4 = coalesce(s.bid_volume_4, i.bid_volume_4),
    ask_price_4 = coalesce(s.ask_price_4, i.ask_price_4),
    ask_volume_4 = coalesce(s.ask_volume_4, i.ask_volume_4),
    bid_price_5 = coalesce(s.bid_price_5, i.bid_price_5),
    bid_volume_5 = coalesce(s.bid_volume_5, i.bid_volume_5),
    ask_price_5 = coalesce(s.ask_price_5, i.ask_price_5),
    ask_volume_5 = coalesce(s.ask_volume_5, i.ask_volume_5),
    raw_data = case when s.raw_data is null then i.raw_data else s.raw_data end
  from incoming i
  where s.trade_date = i.trade_date and s.stock_code = btrim(i.stock_code)
    and (
      s.company_name is null or s.open_price is null or s.high_price is null or s.low_price is null
      or s.close_price is null or s.volume is null or s.value is null or s.frequency is null
      or s.foreign_sell is null or s.foreign_buy is null or s.bid_price_1 is null or s.bid_volume_1 is null
      or s.ask_price_1 is null or s.ask_volume_1 is null or s.bid_price_2 is null or s.bid_volume_2 is null
      or s.ask_price_2 is null or s.ask_volume_2 is null or s.bid_price_3 is null or s.bid_volume_3 is null
      or s.ask_price_3 is null or s.ask_volume_3 is null or s.bid_price_4 is null or s.bid_volume_4 is null
      or s.ask_price_4 is null or s.ask_volume_4 is null or s.bid_price_5 is null or s.bid_volume_5 is null
      or s.ask_price_5 is null or s.ask_volume_5 is null or s.raw_data is null
    );
  get diagnostics v_daily_updated = row_count;

  with incoming as (
    select *
    from jsonb_to_recordset(p_orderbook) as o(
      snapshot_date date,
      snapshot_time time,
      stock_code text,
      bid_price_1 double precision,
      bid_volume_1 double precision,
      ask_price_1 double precision,
      ask_volume_1 double precision,
      bid_price_2 double precision,
      bid_volume_2 double precision,
      ask_price_2 double precision,
      ask_volume_2 double precision,
      bid_price_3 double precision,
      bid_volume_3 double precision,
      ask_price_3 double precision,
      ask_volume_3 double precision,
      bid_price_4 double precision,
      bid_volume_4 double precision,
      ask_price_4 double precision,
      ask_volume_4 double precision,
      bid_price_5 double precision,
      bid_volume_5 double precision,
      ask_price_5 double precision,
      ask_volume_5 double precision,
      raw_data jsonb
    )
    where snapshot_date is not null and nullif(btrim(stock_code), '') is not null
  )
  update public.orderbook_snapshot o
  set
    bid_price_1 = coalesce(o.bid_price_1, i.bid_price_1), bid_volume_1 = coalesce(o.bid_volume_1, i.bid_volume_1),
    ask_price_1 = coalesce(o.ask_price_1, i.ask_price_1), ask_volume_1 = coalesce(o.ask_volume_1, i.ask_volume_1),
    bid_price_2 = coalesce(o.bid_price_2, i.bid_price_2), bid_volume_2 = coalesce(o.bid_volume_2, i.bid_volume_2),
    ask_price_2 = coalesce(o.ask_price_2, i.ask_price_2), ask_volume_2 = coalesce(o.ask_volume_2, i.ask_volume_2),
    bid_price_3 = coalesce(o.bid_price_3, i.bid_price_3), bid_volume_3 = coalesce(o.bid_volume_3, i.bid_volume_3),
    ask_price_3 = coalesce(o.ask_price_3, i.ask_price_3), ask_volume_3 = coalesce(o.ask_volume_3, i.ask_volume_3),
    bid_price_4 = coalesce(o.bid_price_4, i.bid_price_4), bid_volume_4 = coalesce(o.bid_volume_4, i.bid_volume_4),
    ask_price_4 = coalesce(o.ask_price_4, i.ask_price_4), ask_volume_4 = coalesce(o.ask_volume_4, i.ask_volume_4),
    bid_price_5 = coalesce(o.bid_price_5, i.bid_price_5), bid_volume_5 = coalesce(o.bid_volume_5, i.bid_volume_5),
    ask_price_5 = coalesce(o.ask_price_5, i.ask_price_5), ask_volume_5 = coalesce(o.ask_volume_5, i.ask_volume_5),
    raw_data = case when o.raw_data is null then i.raw_data else o.raw_data end
  from incoming i
  where o.snapshot_date = i.snapshot_date
    and o.snapshot_time = coalesce(i.snapshot_time, '00:00:00'::time)
    and o.stock_code = btrim(i.stock_code)
    and (
      o.bid_price_1 is null or o.bid_volume_1 is null or o.ask_price_1 is null or o.ask_volume_1 is null
      or o.bid_price_2 is null or o.bid_volume_2 is null or o.ask_price_2 is null or o.ask_volume_2 is null
      or o.bid_price_3 is null or o.bid_volume_3 is null or o.ask_price_3 is null or o.ask_volume_3 is null
      or o.bid_price_4 is null or o.bid_volume_4 is null or o.ask_price_4 is null or o.ask_volume_4 is null
      or o.bid_price_5 is null or o.bid_volume_5 is null or o.ask_price_5 is null or o.ask_volume_5 is null
      or o.raw_data is null
    );
  get diagnostics v_orderbook_updated = row_count;

  return jsonb_build_object('daily_updated', v_daily_updated, 'orderbook_updated', v_orderbook_updated);
end;
$$;

grant execute on function public.repair_historical_missing_fields(jsonb, jsonb) to service_role;
