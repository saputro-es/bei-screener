import sqlite3

import numpy as np
import pandas as pd

import modules.database as db
from modules.analysis import HORIZONS, accumulation_horizons, screen, three_day_accumulation
from modules.database import normalize_dataframe
from modules.orderbook import summarize_orderbook


def sample_data(days=220):
    dates = pd.date_range("2026-01-01", periods=days, freq="B")
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
                "Foreign Buy": 7000 if i >= days - 20 else 5000,
                "Foreign Sell": 3000 if i >= days - 20 else 5000,
            })
    return pd.DataFrame(rows)


def test_normalize_dataframe_creates_canonical_columns():
    data = normalize_dataframe(sample_data(3))
    assert {"trade_date", "stock_code", "close_price", "foreign_buy", "foreign_sell"}.issubset(data.columns)
    assert data["stock_code"].tolist()[0] == "AAA"
    assert data["trade_date"].iloc[0] == "2026-01-01"


def test_three_day_accumulation_uses_latest_three_days():
    data = normalize_dataframe(sample_data(5))
    result = three_day_accumulation(data)
    aaa = result[result["stock_code"] == "AAA"].iloc[0]
    assert aaa["days_available"] == 3
    assert np.isclose(aaa["net_buy_pct_3d"], 70.0)


def test_multi_horizon_has_all_blueprint_windows():
    data = normalize_dataframe(sample_data(220))
    result = accumulation_horizons(data)
    aaa = result[result["stock_code"] == "AAA"].iloc[0]
    expected = {3: 70.0, 5: 70.0, 10: 70.0, 20: 70.0, 60: 56.6666667, 100: 54.0, 200: 52.0}
    for days in HORIZONS:
        assert aaa[f"days_available_{days}d"] == days
        assert np.isclose(aaa[f"net_buy_pct_{days}d"], expected[days])


def test_screen_filters_3d_but_scores_long_horizons():
    data = normalize_dataframe(sample_data())
    result = screen(data, threshold=65)
    assert set(result["stock_code"]) == {"AAA", "BBB"}
    assert (result["net_buy_pct_3d"] > 65).all()
    for days in HORIZONS:
        assert f"net_buy_pct_{days}d" in result.columns
    assert "sma200" in result.columns
    assert "score" in result.columns
    assert "target_low" in result.columns
    assert "stop_loss" in result.columns


def test_orderbook_pressure_is_computed():
    raw = pd.DataFrame([
        {"Tanggal": "2026-08-07", "Waktu": "09:30:00", "Kode Saham": "AAA",
         "Bid Price 1": 1000, "Bid Volume 1": 900, "Ask Price 1": 1005, "Ask Volume 1": 100,
         "Bid Price 2": 995, "Bid Volume 2": 500, "Ask Price 2": 1010, "Ask Volume 2": 100},
    ])
    normalized = db.normalize_orderbook_dataframe(raw)
    result = summarize_orderbook(normalized)
    row = result.iloc[0]
    assert row["book_pressure_pct"] > 80
    assert row["orderbook_score"] == 2
    assert row["best_bid"] == 1000
    assert row["best_ask"] == 1005


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
        ob_table = conn.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='orderbook_snapshot'").fetchone()
    assert {"close_price", "foreign_buy", "foreign_sell", "raw_data"}.issubset(columns)
    assert count == 1
    assert close == 1001
    assert ob_table is not None
