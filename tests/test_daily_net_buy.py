import pandas as pd

from modules.daily_net_buy import daily_net_buy_matrix


def test_daily_matrix_is_newest_first_and_keeps_missing_blank():
    data = pd.DataFrame(
        {
            "stock_code": ["AAA", "AAA", "AAA", "BBB"],
            "trade_date": pd.to_datetime(["2026-08-06", "2026-08-07", "2026-08-10", "2026-08-10"]),
            "foreign_buy": [10, 20, 30, 0],
            "foreign_sell": [10, 20, 10, 0],
        }
    )
    result = daily_net_buy_matrix(data, days=4).set_index("stock_code")
    assert result.loc["AAA", "D-1"] == 75.0
    assert result.loc["AAA", "D-2"] == 50.0
    assert result.loc["AAA", "D-3"] == 50.0
    assert pd.isna(result.loc["AAA", "D-4"])
    assert pd.isna(result.loc["BBB", "D-1"])


def test_duplicate_date_uses_last_row_and_does_not_create_fake_day():
    data = pd.DataFrame(
        {
            "stock_code": ["AAA", "AAA", "AAA"],
            "trade_date": pd.to_datetime(["2026-08-10", "2026-08-10", "2026-08-07"]),
            "foreign_buy": [90, 20, 10],
            "foreign_sell": [10, 20, 10],
        }
    )
    result = daily_net_buy_matrix(data, days=2).set_index("stock_code")
    assert result.loc["AAA", "D-1"] == 50.0
    assert result.loc["AAA", "D-2"] == 50.0
