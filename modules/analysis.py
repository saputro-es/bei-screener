from __future__ import annotations

import numpy as np
import pandas as pd

HORIZONS = (3, 5, 10, 20, 60, 100, 200)


def _rsi(series: pd.Series, period: int = 14) -> pd.Series:
    delta = pd.to_numeric(series, errors="coerce").diff()
    gain = delta.clip(lower=0)
    loss = -delta.clip(upper=0)
    avg_gain = gain.ewm(alpha=1 / period, adjust=False, min_periods=period).mean()
    avg_loss = loss.ewm(alpha=1 / period, adjust=False, min_periods=period).mean()
    rs = avg_gain / avg_loss.replace(0, np.nan)
    return 100 - (100 / (1 + rs))


def _atr_group(group: pd.DataFrame, period: int = 14) -> pd.Series:
    high = pd.to_numeric(group["high_price"], errors="coerce")
    low = pd.to_numeric(group["low_price"], errors="coerce")
    close = pd.to_numeric(group["close_price"], errors="coerce")
    prev_close = close.shift(1)
    tr = pd.concat([high - low, (high - prev_close).abs(), (low - prev_close).abs()], axis=1).max(axis=1)
    return tr.rolling(period, min_periods=5).mean().set_axis(group.index)


def add_indicators(df: pd.DataFrame) -> pd.DataFrame:
    if df.empty:
        return df.copy()
    data = df.copy()
    for col in ["close_price", "volume", "high_price", "low_price"]:
        if col not in data:
            data[col] = np.nan
    data["trade_date"] = pd.to_datetime(data["trade_date"], errors="coerce")
    data = data.sort_values(["stock_code", "trade_date"]).copy()
    groups = data.groupby("stock_code", group_keys=False)
    for period in (20, 50, 200):
        data[f"sma{period}"] = groups["close_price"].transform(lambda s, p=period: s.rolling(p, min_periods=max(5, min(p, 20))).mean())
    data["rsi14"] = groups["close_price"].transform(_rsi)
    data["volume_ma20"] = groups["volume"].transform(lambda s: s.rolling(20, min_periods=5).mean())
    data["volume_ratio"] = data["volume"] / data["volume_ma20"].replace(0, np.nan)
    atr_parts = [_atr_group(group) for _, group in data.groupby("stock_code", sort=False)]
    data["atr14"] = pd.concat(atr_parts).sort_index() if atr_parts else np.nan
    return data.reset_index(drop=True)


def accumulation_horizons(df: pd.DataFrame, horizons: tuple[int, ...] = HORIZONS) -> pd.DataFrame:
    if df.empty:
        return pd.DataFrame()
    data = df.copy()
    data["trade_date"] = pd.to_datetime(data["trade_date"], errors="coerce")
    for col in ("foreign_buy", "foreign_sell"):
        if col not in data:
            data[col] = 0.0
        data[col] = pd.to_numeric(data[col], errors="coerce").fillna(0.0)
    data = data.dropna(subset=["stock_code", "trade_date"]).sort_values(["stock_code", "trade_date"])

    rows: list[dict] = []
    for code, group in data.groupby("stock_code"):
        group = group.drop_duplicates("trade_date", keep="last")
        row: dict = {"stock_code": code, "latest_date": group["trade_date"].max()}
        for days in horizons:
            recent = group.tail(days)
            buy = recent["foreign_buy"].sum()
            sell = recent["foreign_sell"].sum()
            total = buy + sell
            row[f"days_available_{days}d"] = len(recent)
            row[f"net_buy_{days}d"] = buy - sell
            row[f"net_buy_pct_{days}d"] = buy / total * 100 if total > 0 else np.nan
        rows.append(row)
    return pd.DataFrame(rows)


def three_day_accumulation(df: pd.DataFrame) -> pd.DataFrame:
    """Backward-compatible 3D view; the primary engine now uses all seven horizons."""
    data = accumulation_horizons(df, (3,))
    if data.empty:
        return data
    return data.rename(columns={"days_available_3d": "days_available"})


def _horizon_strength(row: pd.Series) -> tuple[float, int, int]:
    score = 0.0
    available = 0
    strong = 0
    weights = {3: 2.0, 5: 1.5, 10: 1.5, 20: 1.25, 60: 1.0, 100: 0.75, 200: 0.5}
    for days, weight in weights.items():
        pct = row.get(f"net_buy_pct_{days}d", np.nan)
        n = row.get(f"days_available_{days}d", 0)
        if not np.isfinite(pct) or n < days:
            continue
        available += 1
        if pct >= 75:
            score += 2.0 * weight; strong += 1
        elif pct > 65:
            score += 1.0 * weight
        elif pct >= 50:
            score += 0.25 * weight
        elif pct < 40:
            score -= 1.5 * weight
        else:
            score -= 0.5 * weight
    return score, available, strong


def classify_stock(history: pd.DataFrame, accumulation: pd.Series, orderbook: pd.Series | None = None) -> dict:
    if history.empty:
        return {"signal": "❌ BERISIKO", "reason": "Tidak ada histori harga."}
    h = history.sort_values("trade_date").iloc[-1]
    close = float(h.get("close_price", np.nan)); sma20 = float(h.get("sma20", np.nan))
    sma50 = float(h.get("sma50", np.nan)); sma200 = float(h.get("sma200", np.nan))
    rsi = float(h.get("rsi14", np.nan)); vol_ratio = float(h.get("volume_ratio", np.nan)); atr = float(h.get("atr14", np.nan))
    pct3 = float(accumulation.get("net_buy_pct_3d", np.nan))

    score, horizons_available, strong_horizons = _horizon_strength(accumulation)
    reasons: list[str] = []
    if horizons_available:
        reasons.append(f"multi-horizon aktif {horizons_available}/{len(HORIZONS)} horizon")
    if strong_horizons >= 3:
        reasons.append(f"akumulasi kuat di {strong_horizons} horizon")
    for price, ma, label in ((close, sma20, "SMA20"), (close, sma50, "SMA50"), (close, sma200, "SMA200")):
        if np.isfinite(price) and np.isfinite(ma):
            if price > ma: score += 1; reasons.append(f"harga di atas {label}")
            else: score -= 1; reasons.append(f"harga di bawah {label}")
    if np.isfinite(rsi):
        if 50 <= rsi <= 70: score += 1; reasons.append("RSI mendukung momentum")
        elif rsi > 75: score -= 1; reasons.append("RSI terlalu panas")
        elif rsi < 35: reasons.append("RSI rendah; perlu konfirmasi reversal")
    if np.isfinite(vol_ratio) and vol_ratio >= 1.5:
        score += 1; reasons.append("volume meningkat")

    ob_score = 0.0
    ob_signal = "⚪ TIDAK ADA ORDERBOOK"
    ob_metrics = {k: np.nan for k in ("book_pressure_pct", "orderbook_imbalance_pct", "spread_pct", "best_bid", "best_ask", "bid_depth_5", "ask_depth_5")}
    if orderbook is not None and not orderbook.empty:
        ob_score = float(orderbook.get("orderbook_score", 0) or 0)
        score += ob_score
        ob_signal = str(orderbook.get("orderbook_signal", ob_signal))
        for key in ob_metrics:
            value = orderbook.get(key, np.nan)
            try: ob_metrics[key] = float(value)
            except (TypeError, ValueError): pass
        if ob_score > 0: reasons.append(f"orderbook mendukung ({ob_signal})")
        elif ob_score < 0: reasons.append(f"orderbook menekan ({ob_signal})")

    if score >= 8: signal = "✅ LANJUT RALLY"
    elif score >= 3: signal = "⚠️ KONSOLIDASI / KONFIRMASI"
    else: signal = "❌ BERISIKO"

    long_pct = [accumulation.get(f"net_buy_pct_{d}d", np.nan) for d in (60, 100, 200)]
    recent_pct = [accumulation.get(f"net_buy_pct_{d}d", np.nan) for d in (3, 5, 10, 20)]
    long_mean = np.nanmean(long_pct) if any(np.isfinite(x) for x in long_pct) else np.nan
    recent_mean = np.nanmean(recent_pct) if any(np.isfinite(x) for x in recent_pct) else np.nan
    if np.isfinite(pct3) and pct3 >= 75 and np.isfinite(rsi) and rsi > 75:
        quality = "⚠️ Akumulasi kuat tetapi harga sudah panas"
    elif np.isfinite(recent_mean) and np.isfinite(long_mean) and recent_mean >= 65 and long_mean >= 60:
        quality = "✅ Akumulasi sehat lintas horizon"
    elif np.isfinite(pct3) and pct3 > 65:
        quality = "🟡 Akumulasi baru; cek konfirmasi horizon panjang"
    else:
        quality = "⚠️ Perlu konfirmasi harga/volume"

    target_low = target_high = stop = np.nan
    if np.isfinite(close):
        base_atr = atr if np.isfinite(atr) and atr > 0 else close * 0.03
        target_low, target_high, stop = close + base_atr, close + 2 * base_atr, close - 1.2 * base_atr

    return {
        "signal": signal, "quality": quality, "score": round(score, 2), "multi_horizon_score": round(score - ob_score, 2),
        "horizons_available": horizons_available, "reason": "; ".join(reasons), "rsi14": rsi,
        "sma20": sma20, "sma50": sma50, "sma200": sma200, "volume_ratio": vol_ratio, "atr14": atr,
        "orderbook_score": ob_score, "orderbook_signal": ob_signal, **ob_metrics,
        "target_low": target_low, "target_high": target_high, "stop_loss": stop,
    }


def screen(df: pd.DataFrame, threshold: float = 65.0, orderbook: pd.DataFrame | None = None) -> pd.DataFrame:
    if df.empty:
        return pd.DataFrame()
    data = add_indicators(df)
    acc = accumulation_horizons(data)
    latest = data.sort_values("trade_date").groupby("stock_code", as_index=False).tail(1)
    ob_map = orderbook.set_index("stock_code").to_dict(orient="index") if orderbook is not None and not orderbook.empty else {}
    rows: list[dict] = []
    for _, a in acc.iterrows():
        code = a["stock_code"]
        result = classify_stock(data[data["stock_code"] == code], a, pd.Series(ob_map.get(code, {})))
        row = a.to_dict()
        latest_row = latest[latest["stock_code"] == code]
        if not latest_row.empty:
            lr = latest_row.iloc[0]
            row.update({"company_name": lr.get("company_name"), "close_price": lr.get("close_price"), "volume": lr.get("volume")})
        row.update(result); rows.append(row)
    result = pd.DataFrame(rows)
    if result.empty: return result
    result = result[result["days_available_3d"] >= 3]
    result = result[result["net_buy_pct_3d"] > threshold].copy()
    return result.sort_values(["score", "net_buy_pct_3d"], ascending=[False, False]).reset_index(drop=True)
