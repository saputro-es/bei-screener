from __future__ import annotations

import numpy as np
import pandas as pd


LEVELS = range(1, 6)


def summarize_orderbook(df: pd.DataFrame) -> pd.DataFrame:
    """Convert raw orderbook levels into one latest-snapshot signal per stock."""
    if df is None or df.empty:
        return pd.DataFrame(columns=["stock_code"])

    data = df.copy()
    data["snapshot_date"] = pd.to_datetime(data["snapshot_date"], errors="coerce")
    data["snapshot_time"] = data["snapshot_time"].astype(str)
    data = data.dropna(subset=["stock_code", "snapshot_date"])
    data = data.sort_values(["stock_code", "snapshot_date", "snapshot_time"])
    latest = data.groupby("stock_code", as_index=False).tail(1).copy()

    for side in ("bid", "ask"):
        for kind in ("price", "volume"):
            for level in LEVELS:
                col = f"{side}_{kind}_{level}"
                if col not in latest:
                    latest[col] = np.nan
                latest[col] = pd.to_numeric(latest[col], errors="coerce")

    bid_depth = latest[[f"bid_volume_{n}" for n in LEVELS]].sum(axis=1, min_count=1)
    ask_depth = latest[[f"ask_volume_{n}" for n in LEVELS]].sum(axis=1, min_count=1)
    total_depth = bid_depth + ask_depth
    latest["bid_depth_5"] = bid_depth
    latest["ask_depth_5"] = ask_depth
    latest["book_pressure_pct"] = np.where(total_depth > 0, bid_depth / total_depth * 100, np.nan)
    latest["orderbook_imbalance_pct"] = np.where(total_depth > 0, (bid_depth - ask_depth) / total_depth * 100, np.nan)

    bid1 = latest["bid_price_1"]
    ask1 = latest["ask_price_1"]
    mid = (bid1 + ask1) / 2
    latest["spread"] = ask1 - bid1
    latest["spread_pct"] = np.where(mid > 0, (ask1 - bid1) / mid * 100, np.nan)
    latest["best_bid"] = bid1
    latest["best_ask"] = ask1

    def pressure_label(value: float) -> str:
        if not np.isfinite(value):
            return "⚪ DATA KOSONG"
        if value >= 65:
            return "🟢 BID DOMINAN"
        if value >= 55:
            return "🟢 BID CENDERUNG DOMINAN"
        if value <= 35:
            return "🔴 OFFER DOMINAN"
        if value <= 45:
            return "🟠 OFFER CENDERUNG DOMINAN"
        return "🟡 SEIMBANG"

    latest["orderbook_signal"] = latest["book_pressure_pct"].map(pressure_label)
    latest["orderbook_score"] = np.select(
        [latest["book_pressure_pct"] >= 65, latest["book_pressure_pct"] >= 55,
         latest["book_pressure_pct"] <= 35, latest["book_pressure_pct"] <= 45],
        [2, 1, -2, -1], default=0,
    )

    return latest[[
        "stock_code", "snapshot_date", "snapshot_time", "best_bid", "best_ask", "spread", "spread_pct",
        "bid_depth_5", "ask_depth_5", "book_pressure_pct", "orderbook_imbalance_pct",
        "orderbook_signal", "orderbook_score",
    ]].reset_index(drop=True)
