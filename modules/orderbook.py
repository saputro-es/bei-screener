from __future__ import annotations

import numpy as np
import pandas as pd


LEVELS = range(1, 6)


def summarize_orderbook(df: pd.DataFrame) -> pd.DataFrame:
    """Summarize the latest usable five-level orderbook snapshot per stock.

    Price levels and volume levels are tracked separately. A price-only snapshot
    is valid for spread/best-price diagnostics, but it must never be treated as
    a depth/pressure snapshot when either bid or offer volumes are missing.
    """
    output_columns = [
        "stock_code", "snapshot_date", "snapshot_time", "best_bid", "best_ask", "spread", "spread_pct",
        "bid_depth_5", "ask_depth_5", "book_pressure_pct", "orderbook_imbalance_pct",
        "orderbook_signal", "orderbook_score", "price_levels_available", "bid_volume_levels",
        "ask_volume_levels", "volume_levels_complete", "orderbook_status",
    ]
    if df is None or df.empty:
        return pd.DataFrame(columns=output_columns)

    data = df.copy()
    if "snapshot_date" not in data:
        data["snapshot_date"] = pd.Timestamp.today().normalize()
    if "snapshot_time" not in data:
        data["snapshot_time"] = "00:00:00"
    data["snapshot_date"] = pd.to_datetime(data["snapshot_date"], errors="coerce")
    data["snapshot_time"] = data["snapshot_time"].astype(str)
    data["stock_code"] = data["stock_code"].astype("string").str.strip().str.upper()
    data = data.dropna(subset=["stock_code", "snapshot_date"])

    for side in ("bid", "ask"):
        for kind in ("price", "volume"):
            for level in LEVELS:
                col = f"{side}_{kind}_{level}"
                if col not in data:
                    data[col] = np.nan
                data[col] = pd.to_numeric(data[col], errors="coerce")

    price_columns = [f"{side}_price_{level}" for level in LEVELS for side in ("bid", "ask")]
    data = data[data[price_columns].notna().any(axis=1)].copy()
    if data.empty:
        return pd.DataFrame(columns=output_columns)

    data = data.sort_values(["stock_code", "snapshot_date", "snapshot_time"])
    latest = data.groupby("stock_code", as_index=False).tail(1).copy()

    bid_volume_cols = [f"bid_volume_{n}" for n in LEVELS]
    ask_volume_cols = [f"ask_volume_{n}" for n in LEVELS]
    bid_price_cols = [f"bid_price_{n}" for n in LEVELS]
    ask_price_cols = [f"ask_price_{n}" for n in LEVELS]

    latest["price_levels_available"] = latest[price_columns].notna().sum(axis=1)
    latest["bid_volume_levels"] = latest[bid_volume_cols].notna().sum(axis=1)
    latest["ask_volume_levels"] = latest[ask_volume_cols].notna().sum(axis=1)
    latest["volume_levels_complete"] = (
        (latest["bid_volume_levels"] == len(LEVELS)) & (latest["ask_volume_levels"] == len(LEVELS))
    )

    bid_depth = latest[bid_volume_cols].sum(axis=1, min_count=1)
    ask_depth = latest[ask_volume_cols].sum(axis=1, min_count=1)
    total_depth = bid_depth + ask_depth
    latest["bid_depth_5"] = bid_depth
    latest["ask_depth_5"] = ask_depth

    # Pressure/imbalance is valid only when BOTH sides contain volume data.
    # Missing offer volume must never be interpreted as zero offer volume.
    both_sides_volume = (
        latest["bid_volume_levels"].gt(0)
        & latest["ask_volume_levels"].gt(0)
        & total_depth.gt(0)
    )
    latest["book_pressure_pct"] = np.where(
        both_sides_volume, bid_depth / total_depth * 100, np.nan
    )
    latest["orderbook_imbalance_pct"] = np.where(
        both_sides_volume, (bid_depth - ask_depth) / total_depth * 100, np.nan
    )

    bid1 = latest["bid_price_1"]
    ask1 = latest["ask_price_1"]
    mid = (bid1 + ask1) / 2
    latest["spread"] = ask1 - bid1
    latest["spread_pct"] = np.where(mid > 0, (ask1 - bid1) / mid * 100, np.nan)
    latest["best_bid"] = bid1
    latest["best_ask"] = ask1

    def pressure_label(value: float) -> str:
        if not np.isfinite(value):
            return "⚪ VOLUME BID/OFFER TIDAK LENGKAP"
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
    ).astype(float)
    latest["orderbook_status"] = np.select(
        [latest["volume_levels_complete"], latest["bid_volume_levels"] + latest["ask_volume_levels"] > 0],
        ["L1-L5 PRICE + VOLUME LENGKAP", "PRICE + SEBAGIAN VOLUME"],
        default="PRICE LEVEL SAJA",
    )

    return latest[output_columns].reset_index(drop=True)
