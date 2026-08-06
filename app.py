import streamlit as st

# ===============================
# Konfigurasi Halaman
# ===============================
st.set_page_config(
    page_title="BEI Screener V2",
    page_icon="📈",
    layout="wide"
)

# ===============================
# Header
# ===============================
st.title("📈 BEI Screener V2")
st.markdown("### Automatic Indonesia Stock Screener")

st.divider()

# ===============================
# Sidebar
# ===============================
st.sidebar.header("⚙️ Filter")

rsi_min = st.sidebar.slider("RSI Minimum", 0, 100, 50)
rsi_max = st.sidebar.slider("RSI Maximum", 0, 100, 75)

volume_filter = st.sidebar.checkbox(
    "Volume ≥ Average 20 Hari",
    value=True
)

# ===============================
# Tombol Scan
# ===============================
if st.button("🚀 Scan Seluruh BEI"):

    st.success("Scan berhasil dijalankan.")

    st.info("Versi pertama masih berupa tampilan. Logika screening akan ditambahkan pada langkah berikutnya.")

else:

    st.warning("Tekan tombol Scan Seluruh BEI untuk memulai.")

st.divider()

# ===============================
# Area Hasil
# ===============================
st.subheader("📋 Hasil Screening")

st.write("Belum ada data.")

st.caption("BEI Screener V2 - Version 0.1")
