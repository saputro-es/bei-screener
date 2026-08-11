from __future__ import annotations

import numpy as np
import pandas as pd


def daily_net_buy_volume_matrix(df: pd.DataFrame, days: int = 30) -> pd.DataFrame:
    """Return one row per stock with D1..D{days} daily Net Buy and volume.

    D1 is the latest available trading date for that stock, D2 the previous
    available trading date, etc. The Net Buy percentage is computed from that
    day's foreign_buy / foreign_sell only. Volume is the raw daily traded
    volume converted from shares to IDX lots (100 shares per lot).

    Missing source fields remain NaN. Missing trading days are not fabricated
    and do not shift another calendar date into a missing slot.
    """
    if df is None or df.empty:
        return pd.DataFrame()
    if days < 1:
        raise ValueError("days harus >= 1")

    data = df.copy()
    for col in ("foreign_buy", "foreign_sell", "volume"):
        if col not in data:
            data[col] = np.nan
        data[col] = pd.to_numeric(data[col], errors="coerce")
    data["trade_date"] = pd.to_datetime(data["trade_date"], errors="coerce")
    data["stock_code"] = data["stock_code"].astype("string").str.strip().str.upper()
    data = data.dropna(subset=["stock_code", "trade_date"]).copy()
    data = data.sort_values(["stock_code", "trade_date"])
    data = data.drop_duplicates(["stock_code", "trade_date"], keep="last")

    rows: list[dict[str, object]] = []
    for code, group in data.groupby("stock_code", sort=True):
        group = group.sort_values("trade_date").tail(days).iloc[::-1].reset_index(drop=True)
        row: dict[str, object] = {"stock_code": str(code), "daily_days_available": len(group)}
        for offset in range(days):
            prefix = f"d{offset + 1}"
            if offset >= len(group):
                row[f"{prefix}_date"] = pd.NaT
                row[f"{prefix}_net_buy_pct"] = np.nan
                row[f"{prefix}_volume_lot"] = np.nan
                continue
            item = group.iloc[offset]
            buy = item.get("foreign_buy", np.nan)
            sell = item.get("foreign_sell", np.nan)
            total = buy + sell if pd.notna(buy) and pd.notna(sell) else np.nan
            row[f"{prefix}_date"] = item["trade_date"]
            row[f"{prefix}_net_buy_pct"] = (buy / total * 100.0) if pd.notna(total) and total > 0 else np.nan
            volume = item.get("volume", np.nan)
            row[f"{prefix}_volume_lot"] = (volume / 100.0) if pd.notna(volume) and volume >= 0 else np.nan
        rows.append(row)

    return pd.DataFrame(rows)


def daily_matrix_display(df: pd.DataFrame, days: int = 30) -> pd.DataFrame:
    """Compact UI table: stock code + daily Net Buy % + volume in lots only."""
    matrix = daily_net_buy_volume_matrix(df, days=days)
    if matrix.empty:
        return matrix
    display: dict[str, pd.Series] = {"Stock": matrix["stock_code"]}
    for offset in range(1, days + 1):
        prefix = f"D-{offset}"
        display[f"{prefix} NB %"] = matrix[f"d{offset}_net_buy_pct"].round(2)
        display[f"{prefix} Vol (lot)"] = matrix[f"d{offset}_volume_lot"].round(0)
    return pd.DataFrame(display)
