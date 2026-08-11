import numpy as np
import pandas as pd

from modules.daily_flow import daily_matrix_display, daily_net_buy_volume_matrix


def _rows():
    dates = pd.date_range("2026-08-03", periods=4, freq="B")
    return pd.DataFrame(
        {
            "stock_code": ["LABS"] * 4,
            "trade_date": dates,
            "foreign_buy": [60, 20, 30, 70],
            "foreign_sell": [40, 80, 70, 30],
            "volume": [6500, 4800, 7200, 10000],
        }
    )


def test_daily_matrix_is_latest_first_and_volume_is_lots():
    result = daily_net_buy_volume_matrix(_rows(), days=30).iloc[0]
    assert result["d1_date"] == pd.Timestamp("2026-08-06")
    assert result["d1_net_buy_pct"] == 70.0
    assert result["d1_volume_lot"] == 100.0
    assert result["d2_net_buy_pct"] == 30.0
    assert result["d2_volume_lot"] == 72.0
    assert result["d4_net_buy_pct"] == 60.0
    assert result["d4_volume_lot"] == 65.0
    assert pd.isna(result["d5_date"])
    assert pd.isna(result["d5_net_buy_pct"])
    assert pd.isna(result["d5_volume_lot"])


def test_daily_net_buy_uses_canonical_non_signed_percentage():
    result = daily_net_buy_volume_matrix(
        pd.DataFrame(
            {
                "stock_code": ["TEST"],
                "trade_date": [pd.Timestamp("2026-08-06")],
                "foreign_buy": [1],
                "foreign_sell": [99],
                "volume": [100],
            }
        ),
        days=1,
    ).iloc[0]
    assert result["d1_net_buy_pct"] == 1.0
    assert 0.0 <= result["d1_net_buy_pct"] <= 100.0


def test_display_has_only_stock_and_daily_net_buy_volume_lot_pairs():
    display = daily_matrix_display(_rows(), days=3)
    assert list(display.columns) == [
        "Stock",
        "D-1 NB %",
        "D-1 Vol (lot)",
        "D-2 NB %",
        "D-2 Vol (lot)",
        "D-3 NB %",
        "D-3 Vol (lot)",
    ]
    assert display.loc[0, "Stock"] == "LABS"
    assert display.loc[0, "D-1 Vol (lot)"] == 100.0


def test_missing_source_values_are_not_fabricated():
    data = _rows()
    data.loc[3, "foreign_sell"] = np.nan
    data.loc[3, "volume"] = np.nan
    result = daily_net_buy_volume_matrix(data, days=4).iloc[0]
    assert pd.isna(result["d1_net_buy_pct"])
    assert pd.isna(result["d1_volume_lot"])
    assert result["d2_net_buy_pct"] == 30.0


def test_duplicate_date_keeps_last_source_row():
    data = pd.concat(
        [_rows(), _rows().iloc[[3]].assign(foreign_buy=80, foreign_sell=20, volume=12000)],
        ignore_index=True,
    )
    result = daily_net_buy_volume_matrix(data, days=1).iloc[0]
    assert result["d1_net_buy_pct"] == 80.0
    assert result["d1_volume_lot"] == 120.0
