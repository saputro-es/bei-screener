import streamlit as st
import pandas as pd

st.set_page_config(
    page_title="BEI Screener V3",
    page_icon="📈",
    layout="wide"
)

st.title("📈 BEI Screener V3")

st.write("Automatic Indonesia Stock Screener")

st.divider()

st.subheader("📂 Upload File Ringkasan Saham")

uploaded_files = st.file_uploader(
    "Pilih satu atau banyak file Excel",
    type=["xlsx"],
    accept_multiple_files=True
)

if uploaded_files:

    st.success(f"Berhasil mengunggah {len(uploaded_files)} file")

    daftar_data = []

    for file in uploaded_files:

        df = pd.read_excel(file)

        st.write(f"✅ {file.name}")

        st.write(df.head())

        daftar_data.append(df)

    data_gabungan = pd.concat(daftar_data, ignore_index=True)

    st.divider()

    st.subheader("Data Gabungan")

    st.write(data_gabungan)

    st.write(f"Jumlah baris : {len(data_gabungan)}")

else:

    st.info("Silakan upload file Ringkasan Saham.")
