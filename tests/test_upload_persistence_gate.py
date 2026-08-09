import sqlite3

import pandas as pd
import pytest

from modules import upload


def _frame() -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                "trade_date": "2026-08-07",
                "stock_code": "TLKM",
                "company_name": "Telkom Indonesia",
                "close_price": 2740,
                "foreign_buy": 100,
                "foreign_sell": 40,
            }
        ]
    )


def _record() -> dict:
    return {
        "sha256": "sample-sha",
        "filename": "sample.xlsx",
        "size_bytes": 123,
        "rows_read": 1,
        "rows_saved": 1,
    }


def _init_test_db(path):
    with sqlite3.connect(path) as conn:
        conn.execute(
            "CREATE TABLE stock_daily (trade_date TEXT NOT NULL, stock_code TEXT NOT NULL, company_name TEXT, "
            "close_price REAL, foreign_sell REAL, foreign_buy REAL, raw_data TEXT, UNIQUE(trade_date, stock_code))"
        )
        conn.execute(
            "CREATE TABLE orderbook_snapshot (snapshot_date TEXT NOT NULL, snapshot_time TEXT NOT NULL, "
            "stock_code TEXT NOT NULL, UNIQUE(snapshot_date, snapshot_time, stock_code))"
        )
        conn.commit()


def _patch_minimal_sqlite(monkeypatch, db):
    monkeypatch.setattr(upload, "DATABASE_FILE", db)
    monkeypatch.setattr(upload, "init_database", lambda: _init_test_db(db))
    monkeypatch.setattr(upload, "DAILY_ORDERBOOK_COLUMNS", [])
    monkeypatch.setattr(
        upload,
        "DAILY_COLUMNS",
        ["trade_date", "stock_code", "company_name", "close_price", "foreign_sell", "foreign_buy"],
    )
    monkeypatch.setattr(upload, "ORDERBOOK_COLUMNS", ["snapshot_date", "snapshot_time", "stock_code"])


def test_supabase_failure_blocks_sqlite(monkeypatch, tmp_path):
    db = tmp_path / "bei.db"
    _patch_minimal_sqlite(monkeypatch, db)
    monkeypatch.setattr(upload, "supabase_config", lambda: {"enabled": True})
    monkeypatch.setattr(upload, "persist_upload_batch", lambda *args, **kwargs: (_ for _ in ()).throw(RuntimeError("remote write failed")))

    with pytest.raises(RuntimeError, match="remote write failed"):
        upload.save_upload_batch([_frame()], [_record()])

    assert not db.exists()


def test_supabase_success_allows_sqlite_commit(monkeypatch, tmp_path):
    db = tmp_path / "bei.db"
    _patch_minimal_sqlite(monkeypatch, db)
    monkeypatch.setattr(upload, "supabase_config", lambda: {"enabled": True})
    monkeypatch.setattr(
        upload,
        "persist_upload_batch",
        lambda *args, **kwargs: {"saved": True, "duplicate": False, "upload_run_id": "run-1"},
    )

    result = upload.save_upload_batch([_frame()], [_record()])

    assert result["supabase_saved"] is True
    assert result["files_saved"] == 1
    assert db.exists()
