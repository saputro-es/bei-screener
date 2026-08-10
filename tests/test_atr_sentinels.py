import numpy as np
import pandas as pd

from modules.analysis import add_indicators


def test_atr_ignores_zero_ohlc_sentinel_rows():
    dates = pd.date_range("2026-07-01", periods=15, freq="B")
    rows = []
    for i, date in enumerate(dates):
        close = 100 + i
        rows.append({
            "trade_date": date,
            "stock_code": "AAA",
            "close_price": close,
            "high_price": close + 2,
            "low_price": close - 2,
            "volume": 1000,
        })

    # BEI may use 0/0 for an inactive row. It must not create a huge TR.
    rows[7]["high_price"] = 0
    rows[7]["low_price"] = 0

    result = add_indicators(pd.DataFrame(rows)).sort_values("trade_date")
    final_atr = float(result.iloc[-1]["atr14"])

    # The ATR must remain close to the normal 4-point range, not jump toward
    # the previous close because of the zero sentinel.
    assert np.isfinite(final_atr)
    assert 3.5 < final_atr < 5.0
