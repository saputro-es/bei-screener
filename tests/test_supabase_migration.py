from pathlib import Path
import re


ROOT = Path(__file__).resolve().parents[1]
MIGRATION = ROOT / "supabase" / "migrations" / "20260808000000_create_historical_bei_screener.sql"


def _sql() -> str:
    assert MIGRATION.is_file()
    return MIGRATION.read_text(encoding="utf-8")


def test_migration_file_exists_and_is_idempotent():
    sql = _sql()
    lower = sql.lower()
    assert "create extension if not exists" in lower
    assert lower.count("create table if not exists") >= 5
    assert lower.count("create index if not exists") >= 10
    assert "create or replace view latest_stock_daily" in lower
    assert "create or replace view latest_orderbook_snapshot" in lower


def test_required_tables_and_columns_exist():
    sql = _sql().lower()
    for table in (
        "upload_runs",
        "upload_ledger",
        "stock_daily",
        "orderbook_snapshot",
        "technical_indicator_snapshot",
    ):
        assert f"create table if not exists {table}" in sql

    required_stock = (
        "trade_date", "stock_code", "company_name", "open_price", "high_price",
        "low_price", "close_price", "volume", "value", "frequency",
        "foreign_sell", "foreign_buy", "net_foreign_buy", "raw_data", "created_at",
    )
    for column in required_stock:
        assert re.search(rf"\b{re.escape(column)}\b", sql)


def test_orderbook_levels_one_to_five_exist():
    sql = _sql().lower()
    for level in range(1, 6):
        for prefix in ("bid_price_", "bid_volume_", "ask_price_", "ask_volume_"):
            assert f"{prefix}{level}" in sql


def test_upload_ledger_metadata_and_sha_index_exist():
    sql = _sql().lower()
    for column in (
        "sha256", "filename", "size_bytes", "rows_read", "rows_saved",
        "uploaded_at", "metadata", "upload_run_id",
    ):
        assert re.search(rf"\b{re.escape(column)}\b", sql)
    assert "ux_upload_ledger_sha256" in sql


def test_technical_indicators_match_analysis_implementation():
    sql = _sql().lower()
    for column in (
        "sma20", "sma50", "sma200", "volume_ma20", "volume_ratio",
        "rsi14", "atr14",
    ):
        assert re.search(rf"\b{re.escape(column)}\b", sql)


def test_latest_views_exist_and_use_deterministic_latest_order():
    sql = _sql().lower()
    assert "create or replace view latest_stock_daily" in sql
    assert "create or replace view latest_orderbook_snapshot" in sql
    assert "distinct on (trade_date, stock_code)" in sql
    assert "distinct on (snapshot_date, snapshot_time, stock_code)" in sql
    assert "created_at desc, id desc" in sql


def test_rls_and_schema_stage_read_policies_exist_without_public_write_policies():
    sql = _sql().lower()
    for table in (
        "upload_runs", "upload_ledger", "stock_daily",
        "orderbook_snapshot", "technical_indicator_snapshot",
    ):
        assert f"alter table {table} enable row level security" in sql
    assert "create policy" in sql
    assert "for select using (false)" in sql
    assert "for insert" not in sql
    assert "for update" not in sql
    assert "for delete" not in sql


def test_historical_foreign_keys_restrict_deletes():
    sql = _sql().lower()
    assert sql.count("on delete restrict") >= 6
    assert "references upload_runs(id) on delete restrict" in sql
    assert "references stock_daily(id) on delete restrict" in sql


def test_migration_has_no_destructive_sql():
    sql = _sql().lower()
    assert not re.search(r"\bdrop\b", sql)
    assert not re.search(r"\btruncate\b", sql)
    assert not re.search(r"\bdelete\s+from\b", sql)
    assert not re.search(r"\bon\s+delete\s+cascade\b", sql)
