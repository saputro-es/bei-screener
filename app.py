from __future__ import annotations

from io import BytesIO

import pandas as pd
import streamlit as st

from modules.analysis import screen
from modules.database import database_info, load_data, normalize_dataframe, save_dataframe

st.set_page_config(page_title="BEI Screener", page_icon="📈", layout="wide")

st.title("📈 BEI Screener — Accumulation & Rally")
st.caption("Database-backed Indonesian stock screener | Net Buy 3 hari > 65%")

# Always initialize SQLite when the app starts.
info = database_info()

with st.sidebar:
    st.header("⚙️ Pengaturan")
    threshold = st.number_input("Batas Net Buy 3 hari (%)", min_value=0.0, max_value=100.0, value=65.0, step=1.0)
    st.write(f"📦 Database: {info['total_rows']:,} baris")
    st.write(f"🏷️ Saham: {info['total_stocks']:,}")
    st.write(f"📅 Hari: {info['total_days']:,}")

st.subheader("📂 1. Upload data BEI")
files = st.file_uploader(
    "Pilih satu atau beberapa file Excel",
    type=["xlsx", "xls"],
    accept_multiple_files=True,
    help="File tidak disimpan sebagai Excel. Data langsung dinormalisasi dan disimpan ke SQLite.",
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
        uploaded = pd.concat(all_frames, ignore_index=True)
        try:
            saved = save_dataframe(uploaded)
            st.success(f"💾 {saved:,} baris berhasil disimpan/di-update ke SQLite.")
            st.rerun()
        except Exception as exc:
            st.error(f"Gagal menyimpan data: {exc}")

st.divider()

# Reload after any upload so the screen always uses the persistent database.
data = load_data()
if data.empty:
    st.info("Belum ada data. Upload data harian BEI terlebih dahulu.")
    st.markdown(
        """
### Data minimum yang dibutuhkan
- **Kode Saham** dan **Tanggal Perdagangan Terakhir**
- **Penutupan**, idealnya Open/High/Low dan Volume
- **Foreign Buy** dan **Foreign Sell** untuk analisis akumulasi

Semakin banyak hari historis yang diunggah, semakin baik indikator SMA20/SMA50, RSI14, ATR, dan analisis momentum.
"""
    )
    st.stop()

st.subheader("🗄️ Histori SQLite")
latest_date = data["trade_date"].max()
st.write(f"Data terakhir: **{latest_date}** | {len(data):,} baris")

screened = screen(data, threshold=threshold)

st.subheader(f"🔥 Saham Net Buy 3 Hari > {threshold:.0f}%")
if screened.empty:
    st.warning("Belum ada saham yang lolos filter. Pastikan histori minimal 1 hari memiliki Foreign Buy/Sell.")
else:
    display = screened.copy()
    display["Net Buy 3D %"] = display["net_buy_pct_3d"].round(2)
    display["D1 %"] = display["net_buy_pct_d1"].round(2)
    display["D2 %"] = display["net_buy_pct_d2"].round(2)
    display["D3 %"] = display["net_buy_pct_d3"].round(2)
    display["RSI14"] = display["rsi14"].round(1)
    display["Vol Ratio"] = display["volume_ratio"].round(2)
    display["Target Low"] = display["target_low"].round(0)
    display["Target High"] = display["target_high"].round(0)
    display["Stop Loss"] = display["stop_loss"].round(0)

    cols = [
        "stock_code", "company_name", "close_price", "Net Buy 3D %", "D1 %", "D2 %", "D3 %",
        "days_available", "signal", "quality", "RSI14", "sma20", "sma50", "Vol Ratio",
        "Target Low", "Target High", "Stop Loss", "reason",
    ]
    cols = [c for c in cols if c in display.columns]
    st.dataframe(display[cols], use_container_width=True, hide_index=True)

    st.subheader("🎯 Ringkasan sinyal")
    for _, row in screened.head(50).iterrows():
        with st.expander(f"{row['stock_code']} — {row.get('signal', '-') } | Net Buy 3D {row['net_buy_pct_3d']:.2f}%"):
            c1, c2, c3, c4 = st.columns(4)
            c1.metric("Close", _fmt(row.get("close_price")))
            c2.metric("RSI14", _fmt(row.get("rsi14"), 1))
            c3.metric("SMA20", _fmt(row.get("sma20")))
            c4.metric("Volume Ratio", _fmt(row.get("volume_ratio"), 2))
            st.write(f"**Kualitas akumulasi:** {row.get('quality', '-')}")
            st.write(f"**Alasan:** {row.get('reason', '-')}")
            st.write(
                f"**Target 1 minggu (indikatif):** {_fmt(row.get('target_low'))} — {_fmt(row.get('target_high'))} | "
                f"**Stop loss:** {_fmt(row.get('stop_loss'))}"
            )
            st.caption("Target/stop loss adalah rule-based estimate berbasis ATR, bukan jaminan harga.")

st.divider()
st.subheader("🔎 Detail histori")
selected = st.selectbox("Pilih saham", sorted(data["stock_code"].dropna().unique()))
stock_history = data[data["stock_code"] == selected].sort_values("trade_date", ascending=False)
st.dataframe(stock_history, use_container_width=True, hide_index=True)


def _fmt(value, decimals: int = 0) -> str:
    try:
        if pd.isna(value):
            return "-"
        return f"{float(value):,.{decimals}f}"
    except (TypeError, ValueError):
        return "-"
