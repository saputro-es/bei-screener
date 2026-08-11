from __future__ import annotations

import numpy as np
import pandas as pd


def daily_net_buy_matrix(df: pd.DataFrame, days: int = 30) -> pd.DataFrame:
    """Return daily Net Buy percentages by stock, newest trading day first.

    The daily value uses the same definition as the screener's Net Buy metric:
    foreign_buy / (foreign_buy + foreign_sell) * 100. Missing or zero totals
    remain NaN; no value is fabricated. D-1 is the latest trading date present
    in the supplied dataset, D-2 the previous distinct trading date, etc.
    """
    if days < 1:
        raise ValueError("days harus >= 1")
    if df is None or df.empty:
        return pd.DataFrame(columns=["stock_code"] + [f"D-{i}" for i in range(1, days + 1)])

    required = {"stock_code", "trade_date", "foreign_buy", "foreign_sell"}
    missing = required.difference(df.columns)
    if missing:
        raise ValueError(f"Kolom wajib tidak tersedia: {', '.join(sorted(missing))}")

    data = df[["stock_code", "trade_date", "foreign_buy", "foreign_sell"]].copy()
    data["trade_date"] = pd.to_datetime(data["trade_date"], errors="coerce")
    data["foreign_buy"] = pd.to_numeric(data["foreign_buy"], errors="coerce")
    data["foreign_sell"] = pd.to_numeric(data["foreign_sell"], errors="coerce")
    data = data.dropna(subset=["stock_code", "trade_date"])
    data = data.sort_values(["stock_code", "trade_date"])
    data = data.drop_duplicates(["stock_code", "trade_date"], keep="last")

    total = data["foreign_buy"] + data["foreign_sell"]
    data["net_buy_pct"] = np.where(total > 0, data["foreign_buy"] / total * 100.0, np.nan)

    dates = sorted(data["trade_date"].drop_duplicates(), reverse=True)[:days]
    if not dates:
        return pd.DataFrame(columns=["stock_code"] + [f"D-{i}" for i in range(1, days + 1)])

    pivot = data[data["trade_date"].isin(dates)].pivot(index="stock_code", columns="trade_date", values="net_buy_pct")
    pivot = pivot.reindex(columns=dates)
    pivot.columns = [f"D-{i}" for i in range(1, len(dates) + 1)]
    pivot = pivot.reset_index()

    # Always expose the requested 30-day schema; unavailable history stays blank.
    for i in range(len(dates) + 1, days + 1):
        pivot[f"D-{i}"] = np.nan
    return pivot[["stock_code"] + [f"D-{i}" for i in range(1, days + 1)]]
