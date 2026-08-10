from __future__ import annotations

import pandas as pd

from modules.analysis import accumulation_horizons, screen


def test_missing_foreign_flow_does_not_become_zero_activity():
    dates = pd.date_range("2026-07-01", periods=3, freq="B")
    data = pd.DataFrame({
        "trade_date": dates,
        "stock_code": ["AAA"] * 3,
        "close_price": [100, 101, 102],
        "foreign_buy": [1000, None, 1000],
        "foreign_sell": [0, 0, 0],
    })
    result = accumulation_horizons(data, (3,))
    row = result.iloc[0]
    assert pd.isna(row["net_buy_pct_3d"])


def test_target_stop_are_not_fabricated_without_atr14():
    dates = pd.date_range("2026-07-01", periods=7, freq="B")
    data = pd.DataFrame({
        "trade_date": dates,
        "stock_code": ["AAA"] * 7,
        "close_price": [100, 101, 102, 103, 104, 105, 106],
        "high_price": [101, 102, 103, 104, 105, 106, 107],
        "low_price": [99, 100, 101, 102, 103, 104, 105],
        "volume": [1000] * 7,
        "foreign_buy": [1000] * 7,
        "foreign_sell": [0] * 7,
    })
    result = screen(data, threshold=65)
    assert not result.empty
    assert result["target_low"].isna().all()
    assert result["target_high"].isna().all()
    assert result["stop_loss"].isna().all()


def test_screen_exposes_latest_trade_date_as_as_of_date():
    dates = pd.date_range("2026-07-01", periods=3, freq="B")
    data = pd.DataFrame({
        "trade_date": dates,
        "stock_code": ["AAA"] * 3,
        "close_price": [100, 101, 102],
        "foreign_buy": [1000] * 3,
        "foreign_sell": [0] * 3,
    })
    result = screen(data, threshold=65)
    assert result.iloc[0]["as_of_date"] == pd.Timestamp("2026-07-03")
    assert result.iloc[0]["close_price"] == 102
