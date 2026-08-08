from __future__ import annotations

from io import BytesIO

import pandas as pd
import streamlit as st

from modules.analysis import HORIZONS, screen
from modules.database import DAILY_ORDERBOOK_COLUMNS, database_info, load_data, normalize_dataframe
from modules.orderbook import summarize_orderbook
from modules.upload import MAX_FILES_PER_BATCH, existing_hashes, save_upload_batch, sha256_bytes

st.set_page_config(page_title="BEI Screener V4", page_icon="📈", layout="wide")


def _fmt(value, decimals: int = 0) -> str:
    try:
        if pd.isna(value):
            return "-"
        return f"{float(value):,.{decimals}f}"
    except (TypeError, ValueError):
        return "-"


def _embedded_orderbook(data: pd.DataFrame) -> pd.DataFrame:
    """Build the latest five-level orderbook snapshot from the canonical BEI dataset."""
    required = {"trade_date", "stock_code", *DAILY_ORDERBOOK_COLUMNS}
    if data.empty or not required.issubset(data.columns):
        return pd.DataFrame()
    available = data[["trade_date", "stock_code"] + DAILY_ORDERBOOK_COLUMNS].copy()
    available = available.rename(columns={"trade_date": "snapshot_date"})
    available["snapshot_time"] = "00:00:00"
    available = available[["snapshot_date", "snapshot_time", "stock_code"] + DAILY_ORDERBOOK_COLUMNS]
    available = available[available[DAILY_ORDERBOOK_COLUMNS].notna().any(axis=1)]
    return available


st.title("📈 BEI Screener — Multi-Horizon Accumulation + Bid/Offer")
st.caption("Blueprint: Net Buy 3D → 5D → 10D → 20D → 60D → 100D → 200D + technicals + five-level Bid/Offer snapshot")

info = database_info()
with st.sidebar:
    st.header("⚙️ Pengaturan")
    threshold = st.number_input("Filter Net Buy 3D (%)", min_value=0.0, max_value=100.0, value=65.0, step=1.0)
    st.write(f"📦 Database: {info['total_rows']:,} baris")
    st.write(f"🏷️ Saham: {info['total_stocks']:,}")
    st.write(f"📅 Hari: {info['total_days']:,}")
    st.write(f"📖 Bid/Offer: {info['orderbook_rows']:,} baris")

st.subheader("📂 Upload data BEI")
st.caption(f"Maksimal {MAX_FILES_PER_BATCH} file per batch. File yang sudah pernah masuk akan dilewati otomatis berdasarkan SHA-256.")

if "upload_generation" not in st.session_state:
    st.session_state.upload_generation = 0
upload_key = f"daily_upload_{st.session_state.upload_generation}"

files = st.file_uploader(
    "Pilih satu atau beberapa file Ringkasan Saham BEI",
    type=["xlsx", "xls"],
    accept_multiple_files=True,
    key=upload_key,
    help="Pilih hingga 20 file. Data semua file diproses lalu ditulis ke SQLite dalam satu transaksi bulk.",
)

if files:
    if len(files) > MAX_FILES_PER_BATCH:
        st.error(f"❌ Terlalu banyak file: {len(files)}. Maksimal {MAX_FILES_PER_BATCH} file per batch.")
        st.stop()

    file_hashes = {file.name: sha256_bytes(file.getvalue()) for file in files}
    already_uploaded = existing_hashes(file_hashes.values())
    new_files = [file for file in files if file_hashes[file.name] not in already_uploaded]

    if already_uploaded:
        st.info(f"♻️ {len(already_uploaded)} file sudah ada di database dan tidak akan diproses ulang.")

    if not new_files:
        st.success("Semua file yang dipilih sudah pernah diimpor. Tidak ada pekerjaan database yang diulang.")
        st.session_state.upload_generation += 1
        st.rerun()

    all_frames: list[pd.DataFrame] = []
    file_records: list[dict] = []
    progress = st.progress(0, text=f"Membaca 0/{len(new_files)} file...")

    for index, file in enumerate(new_files, start=1):
        try:
            raw = pd.read_excel(BytesIO(file.getvalue()))
            normalized = normalize_dataframe(raw)
            if normalized.empty:
                raise ValueError("File tidak berisi baris data.")
            all_frames.append(normalized)
            ob_count = int(normalized[["bid_price_1", "bid_volume_1", "ask_price_1", "ask_volume_1"]].notna().all(axis=1).sum())
            level_count = int(normalized[DAILY_ORDERBOOK_COLUMNS].notna().any(axis=1).sum())
            file_records.append({
                "sha256": file_hashes[file.name],
                "filename": file.name,
                "size_bytes": len(file.getvalue()),
                "rows_read": len(normalized),
                "rows_saved": len(normalized),
            })
            st.success(f"✅ {file.name}: {len(normalized):,} baris | Bid/Offer L1 lengkap: {ob_count:,} | Orderbook L1-L5 tersedia: {level_count:,}")
        except Exception as exc:
            st.error(f"❌ {file.name}: {exc}")
        finally:
            progress.progress(index / len(new_files), text=f"Membaca {index}/{len(new_files)} file...")

    if all_frames:
        try:
            with st.spinner("💾 Menulis batch ke SQLite secara bulk..."):
                result = save_upload_batch(all_frames, file_records)
            progress.empty()
            st.success(
                f"💾 Selesai: {result['files_saved']} file | "
                f"{result['rows_saved']:,} baris unik disimpan/di-update | "
                f"{result['orderbook_rows']:,} snapshot orderbook tersimpan."
            )
            # Reset uploader so Streamlit does not re-submit the same files on rerun.
            st.session_state.upload_generation += 1
            st.rerun()
        except Exception as exc:
            progress.empty()
            st.error(f"❌ Gagal menyimpan batch. Tidak ada commit parsial: {exc}")

st.divider()
data = load_data()
orderbook_raw = _embedded_orderbook(data)
orderbook = summarize_orderbook(orderbook_raw)

if data.empty:
    st.info("Belum ada data. Upload histori BEI terlebih dahulu.")
    st.markdown("""
### Data minimum
- Kode Saham + Tanggal
- Penutupan
- Foreign Buy + Foreign Sell

### Untuk kualitas penuh blueprint
Upload **≥200 hari bursa** agar horizon 200D aktif. Jika file BEI menyertakan Bid/Offer level 1-5, semuanya otomatis digunakan sebagai orderbook snapshot; tidak perlu upload orderbook kedua.
""")
    st.stop()

st.subheader("🗄️ Histori SQLite")
latest_date = data["trade_date"].max()
st.write(f"Data terakhir: **{latest_date}** | {len(data):,} baris | Bid/Offer aktif: **{len(orderbook):,} saham**")

screened = screen(data, threshold=threshold, orderbook=orderbook)
st.subheader(f"🔥 Kandidat: Net Buy 3D > {threshold:.0f}% + Multi-Horizon 3D–200D")

if screened.empty:
    st.warning("Belum ada saham yang lolos. Pastikan minimal 3 hari data Foreign Buy/Sell tersedia.")
else:
    display = screened.copy()
    for days in HORIZONS:
        display[f"NB {days}D %"] = display[f"net_buy_pct_{days}d"].round(2)
    display["RSI14"] = display["rsi14"].round(1)
    display["Vol Ratio"] = display["volume_ratio"].round(2)
    display["OB Pressure %"] = display["book_pressure_pct"].round(2) if "book_pressure_pct" in display else pd.NA
    display["OB Imbalance %"] = display["orderbook_imbalance_pct"].round(2) if "orderbook_imbalance_pct" in display else pd.NA
    display["Score"] = display["score"].round(2)
    display["Target Low"] = display["target_low"].round(0)
    display["Target High"] = display["target_high"].round(0)
    display["Stop Loss"] = display["stop_loss"].round(0)

    cols = ["stock_code", "company_name", "close_price"] + [f"NB {d}D %" for d in HORIZONS] + [
        "signal", "quality", "Score", "RSI14", "Vol Ratio", "OB Pressure %", "OB Imbalance %", "orderbook_signal",
        "Target Low", "Target High", "Stop Loss",
    ]
    cols = [c for c in cols if c in display.columns]
    st.dataframe(display[cols], use_container_width=True, hide_index=True)

    st.subheader("🎯 Detail kandidat")
    for _, row in screened.head(100).iterrows():
        with st.expander(f"{row['stock_code']} — {row.get('signal', '-')} | 3D {row.get('net_buy_pct_3d', float('nan')):.2f}% | Score {row.get('score', 0):.2f}"):
            c1, c2, c3, c4, c5 = st.columns(5)
            c1.metric("Close", _fmt(row.get("close_price")))
            c2.metric("RSI14", _fmt(row.get("rsi14"), 1))
            c3.metric("SMA200", _fmt(row.get("sma200")))
            c4.metric("Vol Ratio", _fmt(row.get("volume_ratio"), 2))
            c5.metric("OB Pressure", _fmt(row.get("book_pressure_pct"), 1))

            horizon_cols = st.columns(len(HORIZONS))
            for col, days in zip(horizon_cols, HORIZONS):
                value = row.get(f"net_buy_pct_{days}d")
                available = row.get(f"days_available_{days}d", 0)
                col.metric(f"NB {days}D", _fmt(value, 1), f"{int(available)}/{days} hari" if pd.notna(value) else "-")

            st.write(f"**Kualitas akumulasi:** {row.get('quality', '-')}")
            st.write(f"**Bid/Offer:** {row.get('orderbook_signal', '⚪ Tidak ada')} | Pressure {row.get('book_pressure_pct', float('nan')):.2f}% | Imbalance {row.get('orderbook_imbalance_pct', float('nan')):.2f}%")
            st.write(f"**Alasan:** {row.get('reason', '-')}")
            st.write(f"**Target 1 minggu (indikatif):** {_fmt(row.get('target_low'))} — {_fmt(row.get('target_high'))} | **Stop loss:** {_fmt(row.get('stop_loss'))}")

st.divider()
st.subheader("🔎 Detail histori harga")
selected = st.selectbox("Pilih saham", sorted(data["stock_code"].dropna().unique()))
stock_history = data[data["stock_code"] == selected].sort_values("trade_date", ascending=False)
st.dataframe(stock_history, use_container_width=True, hide_index=True)

st.subheader("📖 Bid/Offer terbaru dari file BEI")
if orderbook.empty:
    st.info("File BEI belum menyediakan Bid/Offer yang lengkap.")
else:
    st.dataframe(orderbook.sort_values("book_pressure_pct", ascending=False), use_container_width=True, hide_index=True)
