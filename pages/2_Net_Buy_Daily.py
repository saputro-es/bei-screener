from __future__ import annotations

import pandas as pd
import streamlit as st

from modules.daily_net_buy import daily_net_buy_matrix
from modules.database import load_data

st.set_page_config(page_title="Net Buy Daily — BEI Screener", page_icon="📊", layout="wide")

st.title("📊 Net Buy Harian — 30 Hari Bursa")
st.caption(
    "Tabel transparansi Net Buy harian. Hanya kode saham + persentase per hari. "
    "D-1 adalah hari perdagangan terbaru yang tersedia, D-2 hari sebelumnya, dst."
)

try:
    data = load_data()
except Exception as exc:
    st.error(f"Gagal membaca data canonical: {exc}")
    st.stop()

if data.empty:
    st.info("Belum ada data. Upload histori BEI terlebih dahulu.")
    st.stop()

trade_dates = pd.to_datetime(data["trade_date"], errors="coerce").dropna().drop_duplicates().sort_values(ascending=False)

st.write(f"**Data terakhir:** {trade_dates.iloc[0].strftime('%Y-%m-%d')} | **Hari perdagangan tersedia:** {len(trade_dates)}")
if len(trade_dates) < 30:
    st.warning(
        f"⏳ Histori baru {len(trade_dates)}/30 hari perdagangan. Kolom D-{len(trade_dates) + 1} sampai D-30 akan tetap kosong. "
        "Tidak ada angka yang diestimasi."
    )

matrix = daily_net_buy_matrix(data, days=30)

# Display-only formatting: preserve NaN as blank and avoid adding Company Name.
display = matrix.copy()
for column in display.columns[1:]:
    display[column] = display[column].map(lambda value: "" if pd.isna(value) else f"{float(value):.2f}%")

st.subheader("Net Buy per hari")
st.dataframe(
    display,
    use_container_width=True,
    hide_index=True,
    height=680,
    column_config={"stock_code": st.column_config.TextColumn("Stock", pinned=True)},
)

st.caption(
    "Definisi daily Net Buy: Foreign Buy ÷ (Foreign Buy + Foreign Sell) × 100. "
    "Ini adalah data harian, bukan rata-rata 3D/5D/10D/20D. Agregat Net Buy tetap dihitung oleh mesin screener dengan formula horizon-nya masing-masing. "
    "Jika data buy/sell hari tertentu tidak tersedia atau totalnya nol, nilainya dibiarkan kosong."
)
