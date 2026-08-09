from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
RPC_MIGRATION = ROOT / "supabase" / "migrations" / "20260809000000_add_historical_persistence_rpc.sql"


def test_rpc_migration_exists_and_is_non_destructive():
    sql = RPC_MIGRATION.read_text(encoding="utf-8").lower()
    assert "create or replace function persist_bei_historical_batch" in sql
    assert "security definer" in sql
    assert "on conflict (upload_run_id,trade_date,stock_code) do update" in sql
    assert "on conflict (upload_run_id,snapshot_date,snapshot_time,stock_code) do update" in sql
    assert "on conflict (upload_run_id,trade_date,stock_code) do update" in sql
    assert "revoke all on function" in sql
    assert "grant execute on function" in sql
    assert "drop " not in sql
    assert "truncate " not in sql
    assert "delete from " not in sql


def test_rpc_is_restricted_to_server_role():
    sql = RPC_MIGRATION.read_text(encoding="utf-8").lower()
    assert "from public" in sql
    assert "from anon" in sql
    assert "from authenticated" in sql
    assert "to service_role" in sql


def test_rpc_covers_all_historical_payloads():
    sql = RPC_MIGRATION.read_text(encoding="utf-8").lower()
    for payload in ("p_upload_ledger", "p_stock_daily", "p_orderbook", "p_technical"):
        assert payload in sql
    for table in ("upload_runs", "upload_ledger", "stock_daily", "orderbook_snapshot", "technical_indicator_snapshot"):
        assert f"insert into {table}" in sql
