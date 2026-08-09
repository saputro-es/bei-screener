from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
MIGRATION = ROOT / "supabase" / "migrations" / "20260809000003_harden_upload_idempotency.sql"


def _sql() -> str:
    assert MIGRATION.is_file()
    return MIGRATION.read_text(encoding="utf-8").lower()


def test_batch_key_is_unique_and_rpc_is_idempotent():
    sql = _sql()
    assert "add column if not exists batch_key text" in sql
    assert "ux_upload_runs_batch_key" in sql
    assert "on conflict (batch_key) do nothing" in sql
    assert "duplicate" in sql


def test_rpc_rejects_empty_or_invalid_payloads():
    sql = _sql()
    assert "at least one upload file is required" in sql
    assert "at least one valid daily row is required" in sql
    assert "invalid batch_key" in sql
    assert "invalid file metadata or duplicate upload hash detected" in sql
    assert "no valid daily rows supplied" in sql


def test_rpc_is_non_public():
    sql = _sql()
    assert "revoke all on function public.persist_upload_batch" in sql
    assert "from public" in sql
    assert "from anon" in sql
    assert "from authenticated" in sql
    assert "grant execute" in sql
    assert "to service_role" in sql
