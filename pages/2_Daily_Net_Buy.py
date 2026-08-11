from __future__ import annotations

import pandas as pd
import streamlit as st

from modules.daily_flow import daily_matrix_display
from modules.database import load_data

st.set_page_config(page_title="Daily Net Buy + Volume", page_icon="📊", layout="wide")

st.title("📊 Daily Net Buy + Volume")
st.caption("Kode saham saja • Net Buy harian mengikuti formula utama • volume dalam lot • data yang tidak tersedia tetap kosong")

data = load_data()

if data is None or data.empty:
    st.info("Belum ada histori BEI. Upload data terlebih dahulu dari halaman utama.")
    st.stop()

required = {"stock_code", "trade_date"}
missing = sorted(required - set(data.columns))
if missing:
    st.error("Schema histori belum lengkap: " + ", ".join(missing))
    st.stop()

# Use the same canonical daily-flow calculation everywhere. The main screener's
# Net Buy convention is buy / (buy + sell) * 100, so D1..D30 must not use a
# separate signed formula such as (buy - sell) / (buy + sell).
table = daily_matrix_display(data, days=30)

if table.empty:
    st.info("Belum ada baris histori yang dapat dihitung.")
    st.stop()

latest = pd.to_datetime(data["trade_date"], errors="coerce").max()
latest_text = latest.strftime("%Y-%m-%d") if pd.notna(latest) else "-"

st.write(f"Data sampai **{latest_text}**")
st.caption(
    "D1 = hari perdagangan terbaru yang tersedia untuk masing-masing saham; "
    "D2 = hari perdagangan sebelumnya, dan seterusnya. "
    "Net Buy = Foreign Buy / (Foreign Buy + Foreign Sell) × 100. "
    "Volume = volume sumber (lembar) / 100 = lot. Data yang kosong tetap kosong."
)

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
            for c in table.columns
            if c != "Stock"
        },
    },
)
