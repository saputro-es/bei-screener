from __future__ import annotations

import pandas as pd
import streamlit as st

from modules.database import load_data
from modules.daily_flow import daily_net_buy_volume_matrix

st.set_page_config(page_title="Daily Net Buy", page_icon="📊", layout="wide")

st.title("📊 Daily Net Buy + Volume")
st.caption(
    "30 hari perdagangan terbaru per saham. D-1 adalah hari perdagangan terbaru yang tersedia untuk saham tersebut. "
    "Net Buy = rasio Foreign Buy terhadap Foreign Buy + Foreign Sell pada hari itu. Volume ditampilkan dalam lot. "
    "Data yang tidak tersedia dibiarkan kosong."
)

data = load_data()
if data.empty:
    st.info("Belum ada data BEI.")
    st.stop()

matrix = daily_net_buy_volume_matrix(data, days=30)
if matrix.empty:
    st.info("Belum ada data yang cukup untuk membuat Daily Matrix.")
    st.stop()

available = int(data["trade_date"].nunique())
latest = pd.to_datetime(data["trade_date"], errors="coerce").max()
latest_display = latest.strftime("%Y-%m-%d") if pd.notna(latest) else "-"

c1, c2, c3 = st.columns(3)
c1.metric("Saham", f"{len(matrix):,}")
c2.metric("Hari bursa tersedia", f"{available:,}")
c3.metric("Tanggal terbaru", latest_display)

st.warning(
    "⚠️ D-1/D-2/... mengikuti hari perdagangan yang benar-benar tersedia untuk masing-masing saham. "
    "Tidak ada tanggal atau angka yang dibuat untuk menutup kekosongan data."
)

# Keep the main table intentionally limited to Stock + daily Net Buy + daily volume.
display = {"Stock": matrix["stock_code"]}
for offset in range(1, 31):
    display[f"D-{offset} NB %"] = matrix[f"d{offset}_net_buy_pct"].round(2)
    display[f"D-{offset} Vol (lot)"] = matrix[f"d{offset}_volume_lot"].round(0)

table = pd.DataFrame(display)

column_config = {"Stock": st.column_config.TextColumn("Stock", pinned=True)}
for offset in range(1, 31):
    column_config[f"D-{offset} NB %"] = st.column_config.NumberColumn(
        f"D-{offset} NB %", format="%.2f%%", help="Net Buy harian pada hari perdagangan ke-n terbaru."
    )
    column_config[f"D-{offset} Vol (lot)"] = st.column_config.NumberColumn(
        f"D-{offset} Vol (lot)", format="%.0f", help="Total volume perdagangan hari tersebut dalam lot; kosong jika sumber tidak menyediakan volume."
    )

st.dataframe(table, use_container_width=True, hide_index=True, column_config=column_config)

st.subheader("📌 Cara membaca")
st.markdown(
    """
- **Net Buy harian** menunjukkan komposisi Foreign Buy terhadap Foreign Buy + Foreign Sell pada hari tersebut.
- **Volume** adalah total volume transaksi saham hari tersebut, dikonversi dari lembar menjadi **lot (100 lembar)**.
- **Net Buy tinggi + volume tinggi** → aktivitas beli terjadi pada aktivitas perdagangan yang besar.
- **Net Buy tinggi + volume sangat rendah** → persentasenya kuat, tetapi aktivitas saham tetap perlu diwaspadai.
- Jangan menganggap volume sebagai volume beli; volume adalah **total transaksi**.
- Nilai kosong berarti **data sumber tidak tersedia**, bukan nol dan bukan estimasi.
"""
)

st.caption("Tabel ini adalah transparansi data harian. Net Buy 3D/5D/10D/20D dan indikator teknikal tetap dihitung oleh mesin utama dengan formula masing-masing.")
