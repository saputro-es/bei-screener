import streamlit as st
import pandas as pd
import numpy as np

st.set_page_config(
    page_title="BEI Screener V3",
    page_icon="📈",
    layout="wide"
)

st.title("📈 BEI Screener V3")
st.caption("Automatic Indonesia Stock Screener")

st.divider()

st.subheader("📂 Upload Data Saham")
uploaded_files = st.file_uploader(
    "Pilih 1 atau beberapa file Excel",
    type=["xlsx"],
    accept_multiple_files=True
)

if uploaded_files:

    frames = []

    for file in uploaded_files:
        try:
            df = pd.read_excel(file)
            df.columns = [str(c).strip() for c in df.columns]
            frames.append(df)
            st.success(f"✅ {file.name} — {len(df)} baris")
        except Exception as e:
            st.error(f"Gagal membaca {file.name}: {e}")

    if frames:

        data = pd.concat(frames, ignore_index=True)

        # --------------------------------------------------
        # DETEKSI KOLOM OTOMATIS
        # --------------------------------------------------

        def find_col(names):
            for name in names:
                for col in data.columns:
                    if str(col).lower().strip() == name.lower():
                        return col
            for name in names:
                for col in data.columns:
                    if name.lower() in str(col).lower():
                        return col
            return None

        kode_col = find_col([
            "Kode Saham", "Kode", "Ticker", "Symbol"
        ])

        nama_col = find_col([
            "Nama Perusahaan", "Nama", "Company"
        ])

        close_col = find_col([
            "Penutupan", "Close", "Closing"
        ])

        open_col = find_col([
            "Open Price", "Open"
        ])

        high_col = find_col([
            "Tertinggi", "High"
        ])

        low_col = find_col([
            "Terendah", "Low"
        ])

        volume_col = find_col([
            "Volume"
        ])

        foreign_buy_col = find_col([
            "Foreign Buy", "Foreign Buy Volume",
            "Foreign Buy Value", "Asing Buy"
        ])

        foreign_sell_col = find_col([
            "Foreign Sell", "Foreign Sell Volume",
            "Foreign Sell Value", "Asing Sell"
        ])

        # --------------------------------------------------
        # DATA GABUNGAN
        # --------------------------------------------------

        st.subheader("📊 Data Gabungan")
        st.dataframe(
            data,
            use_container_width=True,
            height=450
        )

        st.write(f"Jumlah saham/data: **{len(data)}**")

        # --------------------------------------------------
        # HITUNG NET BUY %
        # --------------------------------------------------

        if foreign_buy_col and foreign_sell_col:

            buy = pd.to_numeric(
                data[foreign_buy_col], errors="coerce"
            ).fillna(0)

            sell = pd.to_numeric(
                data[foreign_sell_col], errors="coerce"
            ).fillna(0)

            total = buy + sell

            data["Net Buy %"] = np.where(
                total > 0,
                (buy / total) * 100,
                np.nan
            )

            data["Net Buy Value"] = buy - sell

            # --------------------------------------------------
            # FILTER > 65%
            # --------------------------------------------------

            hasil = data[data["Net Buy %"] > 65].copy()

            hasil = hasil.sort_values(
                "Net Buy %",
                ascending=False
            )

            st.divider()
            st.subheader("🔥 SAHAM LOLOS FILTER NET BUY > 65%")

            if len(hasil) == 0:
                st.warning(
                    "Tidak ada saham dengan Net Buy > 65%."
                )
            else:

                kolom_tampil = []

                for c in [
                    kode_col,
                    nama_col,
                    close_col,
                    volume_col,
                    foreign_buy_col,
                    foreign_sell_col,
                    "Net Buy %",
                    "Net Buy Value"
                ]:
                    if c and c in hasil.columns:
                        kolom_tampil.append(c)

                st.dataframe(
                    hasil[kolom_tampil],
                    use_container_width=True,
                    height=600
                )

                # --------------------------------------------------
                # KATEGORI SINYAL
                # --------------------------------------------------

                hasil["Sinyal"] = np.where(
                    hasil["Net Buy %"] >= 75,
                    "✅ KUAT / POTENSI RALLY",
                    np.where(
                        hasil["Net Buy %"] >= 65,
                        "⚠️ AKUMULASI / PERLU KONFIRMASI",
                        "❌ RISIKO"
                    )
                )

                st.subheader("🎯 HASIL SCREENING")

                ringkas = []

                for _, row in hasil.iterrows():

                    kode = (
                        row[kode_col]
                        if kode_col
                        else "-"
                    )

                    nama = (
                        row[nama_col]
                        if nama_col
                        else "-"
                    )

                    netbuy = row["Net Buy %"]

                    signal = row["Sinyal"]

                    ringkas.append({
                        "Kode": kode,
                        "Perusahaan": nama,
                        "Net Buy %": round(netbuy, 2),
                        "Sinyal": signal
                    })

                st.dataframe(
                    pd.DataFrame(ringkas),
                    use_container_width=True
                )

        else:

            st.warning(
                "⚠️ Kolom Foreign Buy dan Foreign Sell belum ditemukan."
            )

            st.info(
                "Data yang tersedia belum cukup untuk menghitung "
                "Net Buy %. Silakan upload file yang memiliki "
                "kolom Foreign Buy dan Foreign Sell."
            )

        # --------------------------------------------------
        # DAFTAR KOLOM
        # --------------------------------------------------

        with st.expander("🔎 Lihat nama semua kolom yang terbaca"):
            for i, col in enumerate(data.columns):
                st.write(f"{i}: `{col}`")

else:

    st.info(
        "📁 Silakan upload file Excel data saham terlebih dahulu."
    )

    st.markdown("""
### Cara kerja

1. Upload 1 atau beberapa file Excel.
2. Sistem menggabungkan seluruh data.
3. Sistem mendeteksi kolom saham secara otomatis.
4. Sistem menghitung **Net Buy %**.
5. Hanya saham **> 65%** yang ditampilkan.
6. Saham diurutkan dari Net Buy terbesar.
7. Sistem memberikan klasifikasi:
   - ✅ Potensi Rally
   - ⚠️ Akumulasi / perlu konfirmasi
   - ❌ Risiko
""")
