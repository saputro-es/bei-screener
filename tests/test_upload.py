import sqlite3

import pandas as pd
import pytest

import modules.database as database
import modules.upload as upload


def _use_temp_db(monkeypatch, tmp_path):
    db_dir = tmp_path / "database"
    db_file = db_dir / "bei_screener.db"
    monkeypatch.setattr(database, "DATABASE_DIR", db_dir)
    monkeypatch.setattr(database, "DATABASE_FILE", db_file)
    monkeypatch.setattr(upload, "DATABASE_FILE", db_file)


def test_sha256_is_stable():
    assert upload.sha256_bytes(b"abc") == upload.sha256_bytes(b"abc")
    assert upload.sha256_bytes(b"abc") != upload.sha256_bytes(b"abd")


def test_bulk_upload_upserts_and_preserves_existing_non_null(monkeypatch, tmp_path):
    _use_temp_db(monkeypatch, tmp_path)
    first = pd.DataFrame({"trade_date": ["2026-07-31", "2026-07-30"], "stock_code": ["TEST", "TEST"], "close_price": [100, 98], "foreign_buy": [700, 600], "foreign_sell": [300, 400], "bid_price_1": [99, 97], "bid_volume_1": [1000, 900], "ask_price_1": [101, 100], "ask_volume_1": [800, 700]})
    result = upload.save_upload_batch([first], [{"sha256": "hash-1", "filename": "a.xlsx", "size_bytes": 10, "rows_read": 2, "rows_saved": 2}])
    assert result["rows_saved"] == 2
    assert result["orderbook_rows"] == 2

    second = pd.DataFrame({"trade_date": ["2026-07-31", "2026-07-29"], "stock_code": ["TEST", "TEST"], "close_price": [105, 97], "foreign_buy": [800, 500], "foreign_sell": [200, 500]})
    result2 = upload.save_upload_batch([second], [{"sha256": "hash-2", "filename": "b.xlsx", "size_bytes": 10, "rows_read": 2, "rows_saved": 2}])
    assert result2["rows_saved"] == 2

    with sqlite3.connect(upload.DATABASE_FILE) as conn:
        rows = conn.execute("SELECT trade_date, close_price, bid_price_1, ask_price_1 FROM stock_daily WHERE stock_code='TEST' ORDER BY trade_date DESC").fetchall()
        uploads = conn.execute("SELECT COUNT(*) FROM upload_ledger").fetchone()[0]
        orderbook = conn.execute("SELECT COUNT(*) FROM orderbook_snapshot WHERE stock_code='TEST'").fetchone()[0]

    assert rows[0] == ("2026-07-31", 105.0, 99.0, 101.0)
    assert len(rows) == 3
    assert uploads == 2
    assert orderbook == 2


def test_existing_hashes(monkeypatch, tmp_path):
    _use_temp_db(monkeypatch, tmp_path)
    upload.existing_hashes(["seed"])
    with sqlite3.connect(upload.DATABASE_FILE) as conn:
        conn.execute("INSERT INTO upload_ledger (sha256, filename, size_bytes, rows_read, rows_saved) VALUES ('known', 'known.xlsx', 1, 1, 1)")
        conn.commit()
    assert upload.existing_hashes(["known", "unknown"]) == {"known"}


def test_filename_date_prevents_iso_day_month_inversion(monkeypatch, tmp_path):
    _use_temp_db(monkeypatch, tmp_path)
    frame = pd.DataFrame({"trade_date": ["2026-06-07"], "stock_code": ["TEST"], "close_price": [100]})
    result = upload.save_upload_batch([frame], [{"sha256": "date-6", "filename": "Ringkasan Saham-20260706.xlsx", "size_bytes": 10, "rows_read": 1, "rows_saved": 1}])
    assert result["rows_saved"] == 1
    with sqlite3.connect(upload.DATABASE_FILE) as conn:
        assert conn.execute("SELECT trade_date FROM stock_daily").fetchone()[0] == "2026-07-06"


def test_filename_date_prevents_august_instead_of_july(monkeypatch, tmp_path):
    _use_temp_db(monkeypatch, tmp_path)
    frame = pd.DataFrame({"trade_date": ["2026-08-07"], "stock_code": ["TEST"], "close_price": [100]})
    upload.save_upload_batch([frame], [{"sha256": "date-8", "filename": "Ringkasan Saham-20260708.xlsx", "size_bytes": 10, "rows_read": 1, "rows_saved": 1}])
    with sqlite3.connect(upload.DATABASE_FILE) as conn:
        assert conn.execute("SELECT trade_date FROM stock_daily").fetchone()[0] == "2026-07-08"


def test_filename_date_rejects_unrelated_mismatch(monkeypatch, tmp_path):
    _use_temp_db(monkeypatch, tmp_path)
    frame = pd.DataFrame({"trade_date": ["2026-07-05"], "stock_code": ["TEST"], "close_price": [100]})
    with pytest.raises(ValueError, match="tidak cocok"):
        upload.save_upload_batch([frame], [{"sha256": "bad-date", "filename": "Ringkasan Saham-20260706.xlsx", "size_bytes": 10, "rows_read": 1, "rows_saved": 1}])


def test_filename_date_rejects_multiple_trade_dates(monkeypatch, tmp_path):
    _use_temp_db(monkeypatch, tmp_path)
    frame = pd.DataFrame({"trade_date": ["2026-07-06", "2026-07-07"], "stock_code": ["AAA", "BBB"], "close_price": [100, 101]})
    with pytest.raises(ValueError, match="tepat satu tanggal"):
        upload.save_upload_batch([frame], [{"sha256": "multi-date", "filename": "Ringkasan Saham-20260706.xlsx", "size_bytes": 10, "rows_read": 2, "rows_saved": 2}])


def test_supabase_safe_frames_preserve_validated_trade_date():
    frame = pd.DataFrame({"trade_date": ["2026-07-06"], "stock_code": ["TEST"], "close_price": [100]})
    safe = upload._supabase_safe_frames([frame])[0]
    assert isinstance(safe.loc[0, "trade_date"], pd.Timestamp)
    assert safe.loc[0, "trade_date"].strftime("%Y-%m-%d") == "2026-07-06"
    normalized = database.normalize_dataframe(safe)
    assert normalized.loc[0, "trade_date"] == "2026-07-06"
