import numpy as np
import pandas as pd

from modules.analysis import screen, three_day_accumulation
from modules.database import normalize_dataframe


def sample_data(days=25):
    dates = pd.date_range("2026-07-01", periods=days, freq="B")
    rows = []
    for code, base in [("AAA", 1000), ("BBB", 2000)]:
        for i, date in enumerate(dates):
            close = base + i * 5
            rows.append(
                {
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
                }
            )
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
