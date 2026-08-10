-- Multi-file uploads can legitimately take longer than the project's
-- default 2-minute PostgreSQL statement timeout. Keep the longer timeout
-- scoped to this atomic persistence RPC only; do not relax the global timeout.
ALTER FUNCTION public.persist_upload_batch(jsonb, jsonb, jsonb, jsonb)
SET statement_timeout = '15min';
