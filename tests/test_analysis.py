import sqlite3

import numpy as np
import pandas as pd

import modules.database as db
from modules.analysis import screen, three_day_accumulation
from modules.database import normalize_dataframe


def sample_data(days=25):
    dates = pd.date_range("2026-07-01", periods=days, freq="B")
    rows = []
    for code, base in [("AAA", 1000), ("BBB", 2000)]:
        for i, date in enumerate(dates):
            close = base + i * 5
            rows.append({
                "Tanggal Perdagangan Terakhir": date,
                "Kode Saham": code,
                "Nama Perusahaan": code,
                "Open Price": close - 5,
                "Tertinggi": close + 10,
                "Terendah": close - 10,
                "Penutupan": close,
                "Volume": 100000 + i * 1000,
                "Foreign Buy": 7000 if i >= days - 3 else 5000,
                "Foreign Sell": 3000 if i >= days - 3 else 5000,
            })
    return pd.DataFrame(rows)


def test_normalize_dataframe_creates_canonical_columns():
    data = normalize_dataframe(sample_data(3))
    assert {"trade_date", "stock_code", "close_price", "foreign_buy", "foreign_sell"}.issubset(data.columns)
    assert data["stock_code"].tolist()[0] == "AAA"
    assert data["trade_date"].iloc[0] == "2026-07-01"


def test_three_day_accumulation_uses_latest_three_days():
    data = normalize_dataframe(sample_data(5))
    result = three_day_accumulation(data)
    aaa = result[result["stock_code"] == "AAA"].iloc[0]
    assert aaa["days_available"] == 3
    assert np.isclose(aaa["net_buy_pct_3d"], 70.0)


def test_screen_filters_above_threshold():
    data = normalize_dataframe(sample_data())
    result = screen(data, threshold=65)
    assert set(result["stock_code"]) == {"AAA", "BBB"}
    assert (result["net_buy_pct_3d"] > 65).all()
    assert result.iloc[0]["net_buy_pct_3d"] >= result.iloc[-1]["net_buy_pct_3d"]
    assert "signal" in result.columns
    assert "target_low" in result.columns
    assert "stop_loss" in result.columns


def test_legacy_sqlite_schema_is_migrated(tmp_path, monkeypatch):
    db_path = tmp_path / "legacy.db"
    monkeypatch.setattr(db, "DATABASE_FILE", db_path)
    with sqlite3.connect(db_path) as conn:
        conn.execute(
            "CREATE TABLE stock_daily (id INTEGER PRIMARY KEY, upload_date TEXT, source_file TEXT, stock_code TEXT, stock_name TEXT, trade_date TEXT, price REAL, volume REAL, net_buy_pct REAL)"
        )
        conn.execute("INSERT INTO stock_daily (upload_date, source_file, stock_code, stock_name, trade_date, price) VALUES ('2026-08-01','a.xlsx','AAA','Alpha','2026-08-01',1000)")
        conn.execute("INSERT INTO stock_daily (upload_date, source_file, stock_code, stock_name, trade_date, price) VALUES ('2026-08-01','b.xlsx','AAA','Alpha','2026-08-01',1001)")
        conn.commit()

    db.init_database()
    with sqlite3.connect(db_path) as conn:
        columns = {row[1] for row in conn.execute("PRAGMA table_info(stock_daily)")}
        count = conn.execute("SELECT COUNT(*) FROM stock_daily WHERE trade_date='2026-08-01' AND stock_code='AAA'").fetchone()[0]
        close = conn.execute("SELECT close_price FROM stock_daily WHERE trade_date='2026-08-01' AND stock_code='AAA'").fetchone()[0]
    assert {"close_price", "foreign_buy", "foreign_sell", "raw_data"}.issubset(columns)
    assert count == 1
    assert close == 1001
