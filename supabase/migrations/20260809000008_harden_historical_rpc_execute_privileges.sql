revoke execute on function public.repair_historical_missing_fields(jsonb, jsonb) from public, anon, authenticated;
grant execute on function public.repair_historical_missing_fields(jsonb, jsonb) to service_role;
revoke execute on function public.persist_bei_historical_batch(uuid, jsonb, jsonb, jsonb, jsonb) from public, anon, authenticated;
grant execute on function public.persist_bei_historical_batch(uuid, jsonb, jsonb, jsonb, jsonb) to service_role;
revoke execute on function public.persist_upload_batch(jsonb, jsonb, jsonb, jsonb) from public, anon, authenticated;
grant execute on function public.persist_upload_batch(jsonb, jsonb, jsonb, jsonb) to service_role;
