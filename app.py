import streamlit as st
import pandas as pd

from modules.database import database_info, load_recent, save_dataframe
from modules.analysis import prepare, screen

st.set_page_config(page_title="BEI Screener V3", page_icon="📈", layout="wide")
st.title("📈 BEI Screener V3")
st.caption("Automatic Indonesia Stock Screener — upload, store, screen, inspect")

with st.sidebar:
    st.header("⚙️ Filter")
    threshold = st.number_input("Minimum % Net Buy", min_value=0.0, max_value=100.0, value=65.0, step=1.0)
    st.caption("Saham dengan % Net Buy di bawah threshold tidak masuk hasil utama.")

info = database_info()
c1, c2, c3 = st.columns(3)
c1.metric("Rows SQLite", info["total_rows"])
c2.metric("Stocks", info["total_stocks"])
c3.metric("Trading Days", info["total_days"])

st.divider()
st.subheader("📂 Upload File Ringkasan Saham")
uploaded_files = st.file_uploader("Pilih satu atau banyak file Excel", type=["xlsx"], accept_multiple_files=True)

if uploaded_files:
    total_saved = 0
    for file in uploaded_files:
        try:
            df = pd.read_excel(file)
            saved = save_dataframe(df, file.name)
            total_saved += saved
            st.success(f"✅ {file.name}: {saved} baris disimpan ke SQLite")
        except Exception as exc:
            st.error(f"❌ {file.name}: {exc}")
    if total_saved:
        st.rerun()

raw = load_recent()
if raw.empty:
    st.info("Belum ada data. Upload file Excel untuk mulai membangun database.")
    st.stop()

st.subheader("🔍 Hasil Screening")
try:
    result = screen(raw, threshold=threshold)
    if result.empty:
        st.warning("Belum ada saham yang memenuhi threshold % Net Buy.")
    else:
        st.success(f"Ditemukan {len(result)} saham dengan % Net Buy ≥ {threshold:.0f}%")
        st.dataframe(result, use_container_width=True, hide_index=True)

        st.subheader("📊 Ringkasan 3 Hari Net Buy")
        cols = [c for c in ["Kode", "% Net Buy", "NB D-2", "NB D-1", "NB D0", "Harga", "Perubahan 5D %", "RSI14", "Trend", "Volume/Avg20"] if c in result.columns]
        st.dataframe(result[cols], use_container_width=True, hide_index=True)
except Exception as exc:
    st.error(f"Gagal menganalisis data: {exc}")
    st.write("Kolom yang tersedia:", raw.columns.tolist())

with st.expander("🗃️ Data SQLite terbaru"):
    st.dataframe(raw, use_container_width=True, hide_index=True)
