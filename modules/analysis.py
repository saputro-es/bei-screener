"""Data preparation and technical indicators for BEI Screener."""
from __future__ import annotations
import numpy as np
import pandas as pd


def prepare(df: pd.DataFrame) -> pd.DataFrame:
    x = df.copy()
    lookup = {str(c).strip().lower(): c for c in x.columns}
    aliases = {
        "stock_code": ["stock_code", "kode", "kode saham", "symbol", "ticker", "code"],
        "trade_date": ["trade_date", "date", "tanggal"],
        "price": ["price", "harga", "close", "last", "harga terakhir"],
        "volume": ["volume", "vol"],
        "net_buy_pct": ["net_buy_pct", "% net buy", "net buy %", "net buy", "accumulation", "akumulasi"],
    }
    for target, names in aliases.items():
        src = next((lookup[n] for n in names if n in lookup), None)
        x[target] = x[src] if src else np.nan
    x["stock_code"] = x["stock_code"].astype(str).str.upper().str.strip()
    x["trade_date"] = pd.to_datetime(x["trade_date"], errors="coerce")
    for c in ["price", "volume", "net_buy_pct"]:
        x[c] = pd.to_numeric(x[c], errors="coerce")
    x.loc[x["net_buy_pct"].abs() <= 1, "net_buy_pct"] *= 100
    return x.dropna(subset=["stock_code"])


def screen(df: pd.DataFrame, threshold: float = 65.0) -> pd.DataFrame:
    x = prepare(df).sort_values(["stock_code", "trade_date"])
    rows = []
    for code, g in x.groupby("stock_code", sort=False):
        g = g.dropna(subset=["price"]).copy()
        if g.empty:
            continue
        p = g["price"].astype(float)
        last = float(p.iloc[-1])
        sma20 = float(p.tail(20).mean())
        sma50 = float(p.tail(50).mean())
        change5 = float((p.iloc[-1] / p.iloc[-min(len(p), 5)] - 1) * 100) if len(p) > 1 else 0
        diff = p.diff()
        gain = diff.clip(lower=0).ewm(alpha=1/14, adjust=False).mean()
        loss = (-diff.clip(upper=0)).ewm(alpha=1/14, adjust=False).mean()
        rs = gain / loss.replace(0, np.nan)
        rsi_series = 100 - (100 / (1 + rs))
        rsi = float(rsi_series.iloc[-1]) if pd.notna(rsi_series.iloc[-1]) else 50.0
        nb = g["net_buy_pct"].dropna()
        current_nb = float(nb.iloc[-1]) if not nb.empty else np.nan
        last3 = nb.tail(3).tolist()
        last3 = ([np.nan] * (3-len(last3)) + last3)[-3:]
        vol_ratio = np.nan
        if g["volume"].notna().sum() >= 5:
            avg = g["volume"].tail(20).mean()
            if avg:
                vol_ratio = float(g["volume"].iloc[-1] / avg)
        trend = "UPTREND" if last >= sma20 >= sma50 else ("MIXED" if last >= sma20 or sma20 >= sma50 else "DOWNTREND")
        rows.append({
            "Kode": code, "% Net Buy": current_nb,
            "NB D-2": last3[0], "NB D-1": last3[1], "NB D0": last3[2],
            "Harga": last, "Perubahan 5D %": change5, "RSI14": rsi,
            "SMA20": sma20, "SMA50": sma50, "Trend": trend,
            "Volume/Avg20": vol_ratio,
        })
    out = pd.DataFrame(rows)
    if out.empty:
        return out
    return out[out["% Net Buy"] >= threshold].sort_values("% Net Buy", ascending=False).reset_index(drop=True)
