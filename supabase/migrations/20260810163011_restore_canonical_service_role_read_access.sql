-- The canonical analysis baseline remains immutable: service_role may read it,
-- but write privileges are intentionally not restored here.
grant select on table public.canonical_stock_daily to service_role;
grant select on table public.canonical_orderbook_snapshot to service_role;
