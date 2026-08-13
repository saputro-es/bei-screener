from __future__ import annotations

import numpy as np
import pandas as pd


def thirty_day_dominance(
    df: pd.DataFrame,
    days: int = 30,
    threshold: float = 50.0,
) -> pd.DataFrame:
    """Rank stocks by aggregate foreign-buy dominance over the last trading days.

    The 50% threshold applies to the aggregate 30-trading-day buy share, not to
    every individual day. Missing foreign buy/sell values make the window
    invalid; no values are synthesized. A secondary metric counts how many of
    the 30 sessions individually had buy share >= threshold, but that count is
    descriptive only and is not the pass/fail rule.
    """
    if df is None or df.empty:
        return pd.DataFrame()

    data = df.copy()
    for col in ("foreign_buy", "foreign_sell"):
        if col not in data.columns:
            data[col] = np.nan
        data[col] = pd.to_numeric(data[col], errors="coerce")
    data["trade_date"] = pd.to_datetime(data["trade_date"], errors="coerce")
    data = data.dropna(subset=["stock_code", "trade_date"])
    data = data.sort_values(["stock_code", "trade_date"])

    rows: list[dict] = []
    for code, group in data.groupby("stock_code", sort=True):
        group = group.drop_duplicates("trade_date", keep="last").tail(days).copy()
        available = len(group)
        if available < days:
            continue
        if group[["foreign_buy", "foreign_sell"]].isna().any().any():
            continue

        buy = float(group["foreign_buy"].sum())
        sell = float(group["foreign_sell"].sum())
        total = buy + sell
        if total <= 0:
            continue

        daily_total = group["foreign_buy"] + group["foreign_sell"]
        daily_pct = group["foreign_buy"].div(daily_total.replace(0, np.nan)) * 100
        dominant_days = int((daily_pct >= threshold).sum())
        dominance_pct = buy / total * 100
        net_buy = buy - sell

        latest = group.iloc[-1]
        rows.append(
            {
                "stock_code": code,
                "company_name": latest.get("company_name"),
                "as_of_date": latest["trade_date"],
                "close_price": pd.to_numeric(latest.get("close_price"), errors="coerce"),
                "volume": pd.to_numeric(latest.get("volume"), errors="coerce"),
                "days_available_30d": available,
                "foreign_buy_30d": buy,
                "foreign_sell_30d": sell,
                "net_buy_30d": net_buy,
                "dominance_30d_pct": dominance_pct,
                "dominant_days_30d": dominant_days,
                "dominant_days_pct": dominant_days / days * 100,
            }
        )

    result = pd.DataFrame(rows)
    if result.empty:
        return result

    result = result[result["dominance_30d_pct"] >= threshold].copy()
    result["dominance_gap_pct"] = result["dominance_30d_pct"] - threshold
    return result.sort_values(
        ["dominance_30d_pct", "dominant_days_30d", "net_buy_30d"],
        ascending=[False, False, False],
    ).reset_index(drop=True)
