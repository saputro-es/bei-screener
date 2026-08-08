from __future__ import annotations

from io import BytesIO

import pandas as pd
import streamlit as st

from modules.analysis import HORIZONS, screen
from modules.database import (
    database_info,
    load_data,
    load_orderbook,
    normalize_dataframe,
    normalize_orderbook_dataframe,
    save_dataframe,
    save_orderbook,
)
from modules.orderbook import summarize_orderbook

st.set_page_config(page_title="BEI Screener V4", page_icon="📈", layout="wide")


def _fmt(value, decimals: int = 0) -> str:
    try:
        if pd.isna(value):
            return "-"
        return f"{float(value):,.{decimals}f}"
    except (TypeError, ValueError):
        return "-"


st.title("📈 BEI Screener — Multi-Horizon Accumulation + Orderbook")
st.caption("Blueprint: Net Buy 3D → 5D → 10D → 20D → 60D → 100D → 200D + technicals + orderbook")

info = database_info()

with st.sidebar:
    st.header("⚙️ Pengaturan")
    threshold = st.number_input("Filter Net Buy 3D (%)", min_value=0.0, max_value=100.0, value=65.0, step=1.0)
    st.write(f"📦 Database: {info['total_rows']:,} baris")
    st.write(f"🏷️ Saham: {info['total_stocks']:,}")
    st.write(f"📅 Hari: {info['total_days']:,}")
    st.write(f"📖 Orderbook: {info['orderbook_rows']:,} snapshot")

st.subheader("📂 1. Upload data harian BEI")
files = st.file_uploader(
    "Pilih satu atau beberapa file Excel harga/foreign flow",
    type=["xlsx", "xls"],
    accept_multiple_files=True,
    key="daily_upload",
    help="Data dinormalisasi dan disimpan permanen ke SQLite berdasarkan (tanggal, kode saham).",
)

if files:
    all_frames: list[pd.DataFrame] = []
    for file in files:
        try:
            raw = pd.read_excel(BytesIO(file.getvalue()))
            normalized = normalize_dataframe(raw)
            normalized["source_file"] = file.name
            all_frames.append(normalized)
            st.success(f"✅ {file.name}: {len(normalized):,} baris")
        except Exception as exc:
            st.error(f"❌ {file.name}: {exc}")
    if all_frames:
        try:
            saved = save_dataframe(pd.concat(all_frames, ignore_index=True))
            st.success(f"💾 {saved:,} baris harian berhasil disimpan/di-update ke SQLite.")
            st.rerun()
        except Exception as exc:
            st.error(f"Gagal menyimpan data harian: {exc}")

st.subheader("📖 2. Upload Orderbook")
ob_files = st.file_uploader(
    "Pilih satu atau beberapa file Excel orderbook",
    type=["xlsx", "xls"],
    accept_multiple_files=True,
    key="orderbook_upload",
    help="Bisa berisi Bid/Offer level 1–5. Minimal Kode Saham + Bid/Offer terbaik atau volume Bid/Offer.",
)

if ob_files:
    ob_frames: list[pd.DataFrame] = []
    for file in ob_files:
        try:
            raw = pd.read_excel(BytesIO(file.getvalue()))
            normalized = normalize_orderbook_dataframe(raw)
            ob_frames.append(normalized)
            st.success(f"✅ Orderbook {file.name}: {len(normalized):,} snapshot")
        except Exception as exc:
            st.error(f"❌ Orderbook {file.name}: {exc}")
    if ob_frames:
        try:
            saved = save_orderbook(pd.concat(ob_frames, ignore_index=True))
            st.success(f"💾 {saved:,} snapshot orderbook berhasil disimpan ke SQLite.")
            st.rerun()
        except Exception as exc:
            st.error(f"Gagal menyimpan orderbook: {exc}")

st.divider()
data = load_data()
orderbook_raw = load_orderbook(latest_only=True)
orderbook = summarize_orderbook(orderbook_raw)

if data.empty:
    st.info("Belum ada data harian. Upload histori BEI terlebih dahulu.")
    st.markdown("""
### Data minimum
- Kode Saham + Tanggal
- Penutupan
- Foreign Buy + Foreign Sell

### Untuk kualitas penuh blueprint
Upload **≥200 hari bursa** agar horizon 200D benar-benar aktif, serta upload orderbook level 1–5 jika tersedia.
""")
    st.stop()

st.subheader("🗄️ Histori SQLite")
latest_date = data["trade_date"].max()
st.write(f"Data terakhir: **{latest_date}** | {len(data):,} baris | Orderbook aktif: **{len(orderbook):,} saham**")

screened = screen(data, threshold=threshold, orderbook=orderbook)
st.subheader(f"🔥 Kandidat: Net Buy 3D > {threshold:.0f}% + Multi-Horizon 3D–200D")

if screened.empty:
    st.warning("Belum ada saham yang lolos. Pastikan minimal 3 hari data Foreign Buy/Sell tersedia.")
else:
    display = screened.copy()
    for days in HORIZONS:
        display[f"NB {days}D %"] = display[f"net_buy_pct_{days}d"].round(2)
    display["RSI14"] = display["rsi14"].round(1)
    display["Vol Ratio"] = display["volume_ratio"].round(2)
    display["OB Pressure %"] = display["book_pressure_pct"].round(2) if "book_pressure_pct" in display else pd.NA
    display["Score"] = display["score"].round(2)
    display["Target Low"] = display["target_low"].round(0)
    display["Target High"] = display["target_high"].round(0)
    display["Stop Loss"] = display["stop_loss"].round(0)

    cols = ["stock_code", "company_name", "close_price"] + [f"NB {d}D %" for d in HORIZONS] + [
        "signal", "quality", "Score", "RSI14", "Vol Ratio", "OB Pressure %", "orderbook_signal",
        "Target Low", "Target High", "Stop Loss",
    ]
    cols = [c for c in cols if c in display.columns]
    st.dataframe(display[cols], use_container_width=True, hide_index=True)

    st.subheader("🎯 Detail kandidat")
    for _, row in screened.head(100).iterrows():
        with st.expander(f"{row['stock_code']} — {row.get('signal', '-')} | 3D {row.get('net_buy_pct_3d', float('nan')):.2f}% | Score {row.get('score', 0):.2f}"):
            c1, c2, c3, c4, c5 = st.columns(5)
            c1.metric("Close", _fmt(row.get("close_price")))
            c2.metric("RSI14", _fmt(row.get("rsi14"), 1))
            c3.metric("SMA200", _fmt(row.get("sma200")))
            c4.metric("Vol Ratio", _fmt(row.get("volume_ratio"), 2))
            c5.metric("OB Pressure", _fmt(row.get("book_pressure_pct"), 1))

            horizon_cols = st.columns(len(HORIZONS))
            for col, days in zip(horizon_cols, HORIZONS):
                value = row.get(f"net_buy_pct_{days}d")
                available = row.get(f"days_available_{days}d", 0)
                col.metric(f"NB {days}D", _fmt(value, 1), f"{int(available)}/{days} hari" if pd.notna(value) else "-")

            st.write(f"**Kualitas akumulasi:** {row.get('quality', '-')}")
            st.write(f"**Orderbook:** {row.get('orderbook_signal', '⚪ Tidak ada')} | Score {row.get('orderbook_score', 0):.1f}")
            st.write(f"**Alasan:** {row.get('reason', '-')}")
            st.write(f"**Target 1 minggu (indikatif):** {_fmt(row.get('target_low'))} — {_fmt(row.get('target_high'))} | **Stop loss:** {_fmt(row.get('stop_loss'))}")

st.divider()
st.subheader("🔎 Detail histori harga")
selected = st.selectbox("Pilih saham", sorted(data["stock_code"].dropna().unique()))
stock_history = data[data["stock_code"] == selected].sort_values("trade_date", ascending=False)
st.dataframe(stock_history, use_container_width=True, hide_index=True)

st.subheader("📖 Orderbook terbaru")
if orderbook.empty:
    st.info("Belum ada snapshot orderbook. Upload data orderbook untuk mengaktifkan tekanan Bid/Offer.")
else:
    st.dataframe(orderbook.sort_values("book_pressure_pct", ascending=False), use_container_width=True, hide_index=True)
