from __future__ import annotations

import pandas as pd
import streamlit as st

from modules.database import load_data

st.set_page_config(page_title="Daily Net Buy + Volume", page_icon="📊", layout="wide")

st.title("📊 Daily Net Buy + Volume")
st.caption("Kode saham saja • Net Buy dan volume harian • data yang tidak tersedia tetap kosong")

# Load the same canonical/local dataset used by the main screener.
data = load_data()

if data is None or data.empty:
    st.info("Belum ada histori BEI. Upload data terlebih dahulu dari halaman utama.")
    st.stop()

required = {"stock_code", "trade_date"}
missing = sorted(required - set(data.columns))
if missing:
    st.error("Schema histori belum lengkap: " + ", ".join(missing))
    st.stop()

work = data.copy()
work["trade_date"] = pd.to_datetime(work["trade_date"], errors="coerce")
work = work.dropna(subset=["stock_code", "trade_date"])

# Find the normalized Net Buy field without fabricating one when the source does not
# contain enough information. Prefer an already calculated field, then derive it only
# from actual foreign buy/sell columns when both exist.
net_buy_candidates = [
    "net_buy_pct", "net_buy_3d_pct", "net_buy_pct_3d", "net_buy", "net_buy_3d",
]
net_col = next((c for c in net_buy_candidates if c in work.columns), None)

if net_col is None:
    buy_candidates = ["foreign_buy", "foreign_buy_value", "foreign_buy_volume", "foreign_buy_lot"]
    sell_candidates = ["foreign_sell", "foreign_sell_value", "foreign_sell_volume", "foreign_sell_lot"]
    buy_col = next((c for c in buy_candidates if c in work.columns), None)
    sell_col = next((c for c in sell_candidates if c in work.columns), None)
    if buy_col and sell_col:
        buy = pd.to_numeric(work[buy_col], errors="coerce")
        sell = pd.to_numeric(work[sell_col], errors="coerce")
        total = buy + sell
        work["_net_buy_pct"] = ((buy - sell) / total * 100).where(total.ne(0))
        net_col = "_net_buy_pct"

# Volume is kept in the source unit. The application explicitly labels it as LOT only
# when the normalized source column says it is lot-based; otherwise it is not guessed.
volume_candidates = [
    ("volume_lot", "Volume (lot)"),
    ("volume_lots", "Volume (lot)"),
    ("volume", "Volume (source unit)"),
    ("total_volume", "Volume (source unit)"),
]
volume_col = next(((c, label) for c, label in volume_candidates if c in work.columns), None)

if net_col is None and volume_col is None:
    st.warning("Histori tersedia, tetapi field Net Buy dan Volume harian belum tersedia di data sumber. Tidak ada angka yang diestimasi.")
    st.stop()

latest = work["trade_date"].max()
trading_dates = sorted(work.loc[work["trade_date"] <= latest, "trade_date"].drop_duplicates(), reverse=True)[:30]

if not trading_dates:
    st.info("Belum ada tanggal perdagangan yang valid.")
    st.stop()

# Build one row per stock. D1 is the latest trading day, D2 the previous trading day,
# etc. This is based on actual dates present in the uploaded BEI history, not calendar days.
stocks = sorted(work["stock_code"].astype(str).str.upper().unique())
rows: list[dict[str, object]] = []
for stock in stocks:
    item: dict[str, object] = {"Stock": stock}
    stock_data = work[work["stock_code"].astype(str).str.upper().eq(stock)]
    for idx, day in enumerate(trading_dates, start=1):
        day_data = stock_data[stock_data["trade_date"].eq(day)]
        if day_data.empty:
            item[f"D{idx} NB %"] = pd.NA
            if volume_col:
                item[f"D{idx} Vol"] = pd.NA
            continue
        record = day_data.iloc[-1]
        item[f"D{idx} NB %"] = pd.to_numeric(record.get(net_col), errors="coerce") if net_col else pd.NA
        if volume_col:
            item[f"D{idx} Vol"] = pd.to_numeric(record.get(volume_col[0]), errors="coerce")
    rows.append(item)

table = pd.DataFrame(rows)

# Keep the table compact by showing the most recent 30 trading sessions as paired
# Net Buy % / Volume columns. Missing source values remain blank.
for col in table.columns:
    if col != "Stock":
        table[col] = pd.to_numeric(table[col], errors="coerce")

st.write(f"Data sampai **{latest.strftime('%Y-%m-%d')}** • {len(trading_dates)} hari bursa tersedia")
st.caption("D1 = hari bursa terbaru. D2 = satu hari bursa sebelumnya. Tidak ada angka pengganti untuk data BEI yang kosong.")

if net_col is None:
    st.info("⚪ Net Buy harian belum tersedia dari schema sumber; kolom Net Buy dibiarkan tidak dibuat.")
if volume_col is None:
    st.info("⚪ Volume harian belum tersedia dari schema sumber; kolom Volume dibiarkan tidak dibuat.")
elif volume_col[1] != "Volume (lot)":
    st.info("ℹ️ Unit volume mengikuti unit asli field sumber dan sengaja tidak dikonversi menjadi lot tanpa dasar data.")

st.dataframe(
    table,
    use_container_width=True,
    hide_index=True,
    column_config={
        "Stock": st.column_config.TextColumn("Stock", width="small"),
        **{
            c: st.column_config.NumberColumn(
                c,
                format="%.2f" if "NB %" in c else "%.0f",
                width="small",
            )
            for c in table.columns if c != "Stock"
        },
    },
)
