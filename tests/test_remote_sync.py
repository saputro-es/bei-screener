import sqlite3

import modules.database as database
import modules.remote_sync as remote_sync


def test_sync_replaces_stale_local_trade_dates(monkeypatch, tmp_path):
    db_dir = tmp_path / "database"
    db_file = db_dir / "bei_screener.db"
    monkeypatch.setattr(database, "DATABASE_DIR", db_dir)
    monkeypatch.setattr(database, "DATABASE_FILE", db_file)
    monkeypatch.setattr(remote_sync, "DATABASE_FILE", db_file)

    database.init_database()
    with sqlite3.connect(db_file) as conn:
        conn.execute(
            "INSERT INTO stock_daily (trade_date, stock_code, close_price) VALUES (?, ?, ?)",
            ("2026-10-07", "AADI", 100),
        )
        conn.commit()

    daily = [{
        "id": 1,
        "trade_date": "2026-07-31",
        "stock_code": "AADI",
        "company_name": "Adaro Andalan Indonesia",
        "close_price": 101,
    }]
    orderbook = []
    monkeypatch.setattr(remote_sync, "_remote_signature", lambda cfg: (1, "2026-07-31"))
    monkeypatch.setattr(remote_sync, "_fetch_all", lambda cfg, table: daily if table == "stock_daily" else orderbook)

    result = remote_sync.sync_local_from_supabase()

    assert result["synced"] is True
    with sqlite3.connect(db_file) as conn:
        row = conn.execute("SELECT trade_date, stock_code, close_price FROM stock_daily").fetchone()
    assert row == ("2026-07-31", "AADI", 101.0)
