from __future__ import annotations

import numpy as np
import pandas as pd

from modules.analysis import add_indicators


def _nb3_pct(group: pd.DataFrame) -> pd.Series:
    buy = pd.to_numeric(group["foreign_buy"], errors="coerce")
    sell = pd.to_numeric(group["foreign_sell"], errors="coerce")
    total = buy + sell
    return buy.rolling(3, min_periods=3).sum().div(
        total.rolling(3, min_periods=3).sum().replace(0, np.nan)
    ).mul(100)


def evaluate_target_history(
    df: pd.DataFrame,
    threshold: float = 65.0,
    target_window: int = 5,
    post_window: int = 3,
) -> pd.DataFrame:
    """Validate historical ATR targets without leaking future data into predictions.

    Target/stop values are calculated only from the prediction-date row. Future
    OHLC is used only in explicit outcome columns, so later uploads can validate
    old predictions without changing the original prediction inputs.
    """
    if df is None or df.empty:
        return pd.DataFrame()
    if target_window < 1 or post_window < 1:
        raise ValueError("target_window dan post_window harus >= 1")

    data = add_indicators(df)
    for col in ("high_price", "low_price", "close_price", "volume"):
        if col not in data:
            data[col] = np.nan
        data[col] = pd.to_numeric(data[col], errors="coerce")
    for col in ("foreign_buy", "foreign_sell"):
        if col not in data:
            data[col] = np.nan
        data[col] = pd.to_numeric(data[col], errors="coerce")
    data["trade_date"] = pd.to_datetime(data["trade_date"], errors="coerce")
    data = data.dropna(subset=["stock_code", "trade_date"]).sort_values(
        ["stock_code", "trade_date"]
    )

    events: list[dict] = []
    for code, raw_group in data.groupby("stock_code", sort=True):
        group = raw_group.drop_duplicates("trade_date", keep="last").reset_index(drop=True)
        group["nb3_pct"] = _nb3_pct(group)
        for i, row in group.iterrows():
            close = row.get("close_price", np.nan)
            atr = row.get("atr14", np.nan)
            nb3 = row.get("nb3_pct", np.nan)
            if not (
                np.isfinite(close)
                and np.isfinite(atr)
                and atr > 0
                and np.isfinite(nb3)
                and nb3 > threshold
            ):
                continue

            target_low = close + atr
            target_high = close + (2.0 * atr)
            stop = close - (1.2 * atr)
            future = group.iloc[i + 1 : i + 1 + target_window].copy()
            complete_window = len(future) >= target_window

            low_hits = future.index[future["high_price"].ge(target_low)].tolist()
            high_hits = future.index[future["high_price"].ge(target_high)].tolist()
            stop_hits = future.index[future["low_price"].le(stop)].tolist()

            low_hit_idx = low_hits[0] if low_hits else None
            high_hit_idx = high_hits[0] if high_hits else None
            stop_hit_idx = stop_hits[0] if stop_hits else None

            outcome = "⏳ PENDING"
            hit_type = ""
            hit_idx = None
            if high_hit_idx is not None:
                outcome = "🟢 TARGET HIGH HIT"
                hit_type = "HIGH"
                hit_idx = high_hit_idx
            elif low_hit_idx is not None:
                outcome = "🟡 TARGET LOW HIT"
                hit_type = "LOW"
                hit_idx = low_hit_idx
            elif complete_window:
                outcome = "⚪ TARGET NOT HIT"
                hit_type = "NONE"

            if stop_hit_idx is not None and hit_idx is not None:
                if stop_hit_idx < hit_idx:
                    outcome = "🔴 STOP BEFORE TARGET"
                    hit_type = "STOP_FIRST"
                elif stop_hit_idx == hit_idx:
                    outcome = "🟠 TARGET/STOP SAME DAY — ORDER UNKNOWN"
                    hit_type = "AMBIGUOUS"
            elif stop_hit_idx is not None and complete_window and hit_idx is None:
                outcome = "🔴 STOP LOSS HIT"
                hit_type = "STOP"

            hit_row = group.loc[hit_idx] if hit_idx is not None else None
            hit_date = hit_row["trade_date"] if hit_row is not None else pd.NaT

            post_status = ""
            post_max_high = post_min_low = post_last_close = np.nan
            hit_volume_ratio = hit_rsi14 = close_location_pct = np.nan
            volume_confirmation = ""
            rejection = ""
            if hit_row is not None:
                high = hit_row.get("high_price", np.nan)
                low = hit_row.get("low_price", np.nan)
                hit_close = hit_row.get("close_price", np.nan)
                hit_volume_ratio = hit_row.get("volume_ratio", np.nan)
                hit_rsi14 = hit_row.get("rsi14", np.nan)
                if np.isfinite(high) and np.isfinite(low) and high > low and np.isfinite(hit_close):
                    close_location_pct = (hit_close - low) / (high - low) * 100
                    if close_location_pct >= 70:
                        rejection = "CLOSE DEKAT HIGH"
                    elif close_location_pct <= 40:
                        rejection = "REJECTION KUAT"
                    else:
                        rejection = "CLOSE DI TENGAH RANGE"
                if np.isfinite(hit_volume_ratio):
                    volume_confirmation = "VOLUME KONFIRMASI" if hit_volume_ratio >= 1.5 else "VOLUME BELUM KUAT"

                if hit_type == "HIGH":
                    post = group.iloc[hit_idx + 1 : hit_idx + 1 + post_window].copy()
                    if post.empty:
                        post_status = "⏳ TARGET HIGH HIT — MENUNGGU DATA LANJUTAN"
                    else:
                        post_max_high = pd.to_numeric(post["high_price"], errors="coerce").max()
                        post_min_low = pd.to_numeric(post["low_price"], errors="coerce").min()
                        post_last_close = post["close_price"].iloc[-1]
                        post_close_above_high = post["close_price"].gt(target_high).any()
                        post_stop = post["low_price"].le(stop).any()
                        if post_stop or (np.isfinite(post_last_close) and post_last_close < target_low):
                            post_status = "🔴 REVERSAL / KOREKSI BERISIKO"
                        elif post_close_above_high:
                            post_status = "🟢 CONTINUE / BREAKOUT LANJUT"
                        else:
                            post_status = "🟡 KONSOLIDASI SETELAH TARGET"

            events.append(
                {
                    "stock_code": code,
                    "prediction_date": row["trade_date"],
                    "nb3_pct": nb3,
                    "prediction_close": close,
                    "atr14": atr,
                    "target_low": target_low,
                    "target_high": target_high,
                    "stop_loss": stop,
                    "target_window_days": target_window,
                    "validation_complete": complete_window,
                    "outcome": outcome,
                    "hit_type": hit_type,
                    "hit_date": hit_date,
                    "hit_volume_ratio": hit_volume_ratio,
                    "hit_rsi14": hit_rsi14,
                    "hit_close_location_pct": close_location_pct,
                    "volume_confirmation": volume_confirmation,
                    "rejection": rejection,
                    "post_status": post_status,
                    "post_max_high": post_max_high,
                    "post_min_low": post_min_low,
                    "post_last_close": post_last_close,
                    "post_window_days": post_window,
                }
            )

    result = pd.DataFrame(events)
    if result.empty:
        return result
    return result.sort_values(["prediction_date", "stock_code"], ascending=[False, True]).reset_index(drop=True)
