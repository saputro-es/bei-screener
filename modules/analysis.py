from __future__ import annotations

import numpy as np
import pandas as pd


def _rsi(series: pd.Series, period: int = 14) -> pd.Series:
    delta = series.diff()
    gain = delta.clip(lower=0)
    loss = -delta.clip(upper=0)
    avg_gain = gain.ewm(alpha=1 / period, adjust=False, min_periods=period).mean()
    avg_loss = loss.ewm(alpha=1 / period, adjust=False, min_periods=period).mean()
    rs = avg_gain / avg_loss.replace(0, np.nan)
    return 100 - (100 / (1 + rs))


def add_indicators(df: pd.DataFrame) -> pd.DataFrame:
    """Calculate indicators independently for every stock."""
    if df.empty:
        return df.copy()
    data = df.copy()
    for col in ["close_price", "volume", "high_price", "low_price"]:
        if col not in data:
            data[col] = np.nan
    data["trade_date"] = pd.to_datetime(data["trade_date"], errors="coerce")
    data = data.sort_values(["stock_code", "trade_date"]).copy()

    groups = data.groupby("stock_code", group_keys=False)
    data["sma20"] = groups["close_price"].transform(lambda s: s.rolling(20, min_periods=5).mean())
    data["sma50"] = groups["close_price"].transform(lambda s: s.rolling(50, min_periods=10).mean())
    data["rsi14"] = groups["close_price"].transform(_rsi)
    data["volume_ma20"] = groups["volume"].transform(lambda s: s.rolling(20, min_periods=5).mean())
    data["volume_ratio"] = data["volume"] / data["volume_ma20"].replace(0, np.nan)
    data["atr14"] = groups.apply(_atr_group).reset_index(level=0, drop=True)
    return data.reset_index(drop=True)


def _atr_group(group: pd.DataFrame) -> pd.Series:
    high = pd.to_numeric(group["high_price"], errors="coerce")
    low = pd.to_numeric(group["low_price"], errors="coerce")
    close = pd.to_numeric(group["close_price"], errors="coerce")
    prev_close = close.shift(1)
    tr = pd.concat([high - low, (high - prev_close).abs(), (low - prev_close).abs()], axis=1).max(axis=1)
    return tr.rolling(14, min_periods=5).mean().set_axis(group.index)


def three_day_accumulation(df: pd.DataFrame) -> pd.DataFrame:
    """Aggregate foreign buy/sell over the latest three trading dates per stock."""
    if df.empty:
        return pd.DataFrame()
    data = df.copy()
    for col in ["foreign_buy", "foreign_sell"]:
        if col not in data:
            data[col] = 0.0
    data["trade_date"] = pd.to_datetime(data["trade_date"], errors="coerce")
    data = data.dropna(subset=["stock_code", "trade_date"]).sort_values(["stock_code", "trade_date"])
    data["foreign_buy"] = pd.to_numeric(data["foreign_buy"], errors="coerce").fillna(0)
    data["foreign_sell"] = pd.to_numeric(data["foreign_sell"], errors="coerce").fillna(0)

    rows = []
    for code, group in data.groupby("stock_code"):
        recent = group.tail(3)
        buy = recent["foreign_buy"].sum()
        sell = recent["foreign_sell"].sum()
        total = buy + sell
        rows.append({
            "stock_code": code,
            "days_available": len(recent),
            "latest_date": recent["trade_date"].max(),
            "net_buy_3d": buy - sell,
            "net_buy_pct_3d": (buy / total * 100) if total > 0 else np.nan,
            "foreign_buy_3d": buy,
            "foreign_sell_3d": sell,
            "net_buy_pct_d1": _net_pct(recent.iloc[-1]),
            "net_buy_pct_d2": _net_pct(recent.iloc[-2]) if len(recent) >= 2 else np.nan,
            "net_buy_pct_d3": _net_pct(recent.iloc[-3]) if len(recent) >= 3 else np.nan,
        })
    return pd.DataFrame(rows)


def _net_pct(row: pd.Series) -> float:
    buy = float(row.get("foreign_buy", 0) or 0)
    sell = float(row.get("foreign_sell", 0) or 0)
    total = buy + sell
    return buy / total * 100 if total > 0 else np.nan


def classify_stock(history: pd.DataFrame, accumulation: pd.Series) -> dict:
    """Produce a transparent rule-based signal; no black-box prediction."""
    if history.empty:
        return {"signal": "❌ RISIKO", "reason": "Tidak ada histori harga."}

    h = history.sort_values("trade_date").iloc[-1]
    close = float(h.get("close_price", np.nan))
    sma20 = float(h.get("sma20", np.nan))
    sma50 = float(h.get("sma50", np.nan))
    rsi = float(h.get("rsi14", np.nan))
    vol_ratio = float(h.get("volume_ratio", np.nan))
    atr = float(h.get("atr14", np.nan))
    pct = float(accumulation.get("net_buy_pct_3d", np.nan))

    score = 0
    reasons = []
    if np.isfinite(pct):
        if pct >= 75:
            score += 2; reasons.append("akumulasi 3 hari kuat")
        elif pct > 65:
            score += 1; reasons.append("akumulasi 3 hari lolos filter")
        else:
            score -= 2
    if np.isfinite(close) and np.isfinite(sma20):
        if close > sma20: score += 1; reasons.append("harga di atas SMA20")
        else: score -= 1; reasons.append("harga di bawah SMA20")
    if np.isfinite(close) and np.isfinite(sma50):
        if close > sma50: score += 1; reasons.append("harga di atas SMA50")
        else: score -= 1; reasons.append("harga di bawah SMA50")
    if np.isfinite(rsi):
        if 50 <= rsi <= 70: score += 1; reasons.append("RSI mendukung momentum")
        elif rsi > 75: score -= 1; reasons.append("RSI terlalu panas")
        elif rsi < 35: reasons.append("RSI rendah; perlu konfirmasi")
    if np.isfinite(vol_ratio) and vol_ratio >= 1.5:
        score += 1; reasons.append("volume meningkat")

    if score >= 4:
        signal = "✅ LANJUT RALLY"
    elif score >= 1:
        signal = "⚠️ KONSOLIDASI / KONFIRMASI"
    else:
        signal = "❌ BERISIKO"

    if np.isfinite(pct) and pct >= 75 and np.isfinite(rsi) and rsi > 75:
        quality = "⚠️ Akumulasi kuat tetapi harga sudah panas"
    elif np.isfinite(pct) and pct > 65 and score >= 3:
        quality = "✅ Akumulasi relatif sehat"
    else:
        quality = "⚠️ Perlu konfirmasi harga/volume"

    target_low = target_high = stop = np.nan
    if np.isfinite(close):
        base_atr = atr if np.isfinite(atr) and atr > 0 else close * 0.03
        target_low = close + 1.0 * base_atr
        target_high = close + 2.0 * base_atr
        stop = close - 1.2 * base_atr

    return {
        "signal": signal,
        "quality": quality,
        "score": score,
        "reason": "; ".join(reasons),
        "rsi14": rsi,
        "sma20": sma20,
        "sma50": sma50,
        "volume_ratio": vol_ratio,
        "atr14": atr,
        "target_low": target_low,
        "target_high": target_high,
        "stop_loss": stop,
    }


def screen(df: pd.DataFrame, threshold: float = 65.0) -> pd.DataFrame:
    """Return one row per stock, ranked by 3-day Net Buy %, with technical context."""
    if df.empty:
        return pd.DataFrame()
    data = add_indicators(df)
    acc = three_day_accumulation(data)
    latest = data.sort_values("trade_date").groupby("stock_code", as_index=False).tail(1)

    rows = []
    for _, a in acc.iterrows():
        code = a["stock_code"]
        hist = data[data["stock_code"] == code]
        result = classify_stock(hist, a)
        row = a.to_dict()
        latest_row = latest[latest["stock_code"] == code]
        if not latest_row.empty:
            lr = latest_row.iloc[0]
            row.update({
                "company_name": lr.get("company_name"),
                "close_price": lr.get("close_price"),
                "volume": lr.get("volume"),
            })
        row.update(result)
        rows.append(row)

    result = pd.DataFrame(rows)
    if result.empty:
        return result
    result = result[result["days_available"] >= 3]
    result = result[result["net_buy_pct_3d"] > threshold].copy()
    return result.sort_values(["net_buy_pct_3d", "score"], ascending=[False, False]).reset_index(drop=True)
