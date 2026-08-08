import pandas as pd
import streamlit as st
from pathlib import Path
from datetime import datetime

UPLOAD_FOLDER = Path("database")
UPLOAD_FOLDER.mkdir(exist_ok=True)


def upload_excel():
    st.subheader("📂 Upload Data Harian")

    file = st.file_uploader("Pilih file Excel", type=["xlsx", "xls"])

    if file is not None:
        today = datetime.now().strftime("%Y-%m-%d")
        filename = UPLOAD_FOLDER / f"{today}.xlsx"

        with open(filename, "wb") as f:
            f.write(file.getbuffer())

        df = pd.read_excel(filename)

        st.success(f"File berhasil disimpan: {filename.name}")
        st.dataframe(df.head())
        return df

    return None
