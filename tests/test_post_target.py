import numpy as np
import pandas as pd

from modules.post_target import evaluate_target_history


def _history(n: int = 24) -> pd.DataFrame:
    dates = pd.date_range("2026-07-01", periods=n, freq="B")
    close = np.full(n, 100.0)
    high = np.full(n, 101.0)
    low = np.full(n, 99.0)
    volume = np.full(n, 1000.0)
    buy = np.full(n, 70.0)
    sell = np.full(n, 30.0)
    return pd.DataFrame(
        {
            "stock_code": "TEST",
            "trade_date": dates,
            "close_price": close,
            "high_price": high,
            "low_price": low,
            "volume": volume,
            "foreign_buy": buy,
            "foreign_sell": sell,
        }
    )


def test_target_high_hit_then_continue_is_classified_after_post_data():
    data = _history()
    # Prediction date has a valid ATR14 and NB3 > 65. With ATR=2,
    # target low/high are 102/104 and stop is 97.6.
    data.loc[15, "close_price"] = 100.0
    data.loc[16, "high_price"] = 104.0
    data.loc[16, "close_price"] = 103.0
    data.loc[17, "high_price"] = 106.0
    data.loc[17, "close_price"] = 105.0

    result = evaluate_target_history(data, threshold=65.0, target_window=5, post_window=2)
    event = result[result["prediction_date"] == pd.Timestamp("2026-07-22")].iloc[0]

    assert event["outcome"] == "🟢 TARGET HIGH HIT"
    assert event["post_status"] == "🟢 CONTINUE / BREAKOUT LANJUT"
    assert event["target_low"] == 102.0
    assert event["target_high"] == 104.0


def test_target_hit_without_followup_is_waiting_not_reversal():
    data = _history(16)
    data.loc[15, "high_price"] = 104.0
    data.loc[15, "close_price"] = 100.0

    result = evaluate_target_history(data, threshold=65.0, target_window=5, post_window=2)
    event = result[result["prediction_date"] == pd.Timestamp("2026-07-22")].iloc[0]

    assert event["outcome"] == "⏳ PENDING"
    assert event["post_status"] == ""
    assert np.isnan(event["post_last_close"])


def test_future_validation_never_changes_prediction_target():
    data = _history()
    before = evaluate_target_history(data, threshold=65.0)

    extended = pd.concat(
        [
            data,
            pd.DataFrame(
                {
                    "stock_code": ["TEST"],
                    "trade_date": [pd.Timestamp("2026-08-04")],
                    "close_price": [120.0],
                    "high_price": [121.0],
                    "low_price": [119.0],
                    "volume": [1000.0],
                    "foreign_buy": [70.0],
                    "foreign_sell": [30.0],
                }
            ),
        ],
        ignore_index=True,
    )
    after = evaluate_target_history(extended, threshold=65.0)
    before_event = before[before["prediction_date"] == pd.Timestamp("2026-07-22")].iloc[0]
    after_event = after[after["prediction_date"] == pd.Timestamp("2026-07-22")].iloc[0]

    assert before_event["prediction_close"] == after_event["prediction_close"]
    assert before_event["target_low"] == after_event["target_low"]
    assert before_event["target_high"] == after_event["target_high"]
    assert before_event["stop_loss"] == after_event["stop_loss"]
