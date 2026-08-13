from __future__ import annotations

from io import BytesIO

import pandas as pd
import streamlit as st

from modules.analysis import HORIZONS, screen
from modules.database import DAILY_ORDERBOOK_COLUMNS, database_info, load_data, normalize_dataframe
from modules.dominance import thirty_day_dominance
from modules.historical_repair import repair_frames
from modules.orderbook import summarize_orderbook
from modules.persistence import backup_database, config as persistence_config, restore_if_needed, status as persistence_status
from modules.post_target import evaluate_target_history
from modules.remote_sync import sync_local_from_supabase
from modules.upload import MAX_FILES_PER_BATCH, existing_hashes, save_upload_batch, sha256_bytes

st.set_page_config(page_title="BEI Screener V4", page_icon="📈", layout="wide")


def _fmt(value, decimals: int = 0) -> str:
    try:
        if pd.isna(value):
            return "-"
        return f"{float(value):,.{decimals}f}"
    except (TypeError, ValueError):
        return "-"


def _format_trade_date_display(data: pd.DataFrame) -> pd.DataFrame:
    if data is None or data.empty or "trade_date" not in data.columns:
        return data.copy() if data is not None else pd.DataFrame()
    display = data.copy()
    parsed = pd.to_datetime(display["trade_date"], errors="coerce", format="%Y-%m-%d")
    display["trade_date"] = parsed.dt.strftime("%Y-%m-%d")
    return display


def _persistence_summary(persistence_info: dict[str, object]) -> str:
    supabase_ok = bool(persistence_info.get("supabase_reachable"))
    github_ok = bool(persistence_info.get("github_remote_available"))
    if supabase_ok and github_ok:
        return "🟢 Primary Supabase aktif + secondary GitHub recovery snapshot tersedia"
    if supabase_ok:
        return "🟢 Primary Supabase aktif | secondary GitHub recovery snapshot belum dikonfigurasi"
    if github_ok:
        return "🟡 Secondary GitHub recovery snapshot tersedia | primary Supabase belum terverifikasi"
    return "🔴 Penyimpanan durable belum terverifikasi"


def _backup_confirmation(backup_result: dict[str, object]) -> str:
    backend = str(backup_result.get("backend", ""))
    rows = int(backup_result.get("rows", 0) or 0)
    if backend == "supabase":
        return f"Primary Supabase tersimpan dan terverifikasi ({rows:,} baris). Secondary GitHub recovery snapshot tidak dikonfigurasi."
    if backend == "github":
        size_mb = int(backup_result.get("asset_size", 0) or 0) / 1024 / 1024
        return f"Primary Supabase tersimpan; secondary GitHub recovery snapshot berhasil ({size_mb:.2f} MB)."
    return "Penyimpanan durable berhasil dikonfirmasi."


def _embedded_orderbook(data: pd.DataFrame) -> pd.DataFrame:
    required = {"trade_date", "stock_code", *DAILY_ORDERBOOK_COLUMNS}
    if data.empty or not required.issubset(data.columns):
        return pd.DataFrame()
    available = data[["trade_date", "stock_code"] + DAILY_ORDERBOOK_COLUMNS].copy()
    available = available.rename(columns={"trade_date": "snapshot_date"})
    available["snapshot_time"] = "00:00:00"
    available = available[["snapshot_date", "snapshot_time", "stock_code"] + DAILY_ORDERBOOK_COLUMNS]
    mask = available[DAILY_ORDERBOOK_COLUMNS].notna().any(axis=1)
    return available.loc[mask].copy()


def _orderbook_completeness(data: pd.DataFrame) -> dict[str, int]:
    if data is None or data.empty:
        return {f"l{level}": 0 for level in range(1, 6)}
    result: dict[str, int] = {}
    for level in range(1, 6):
        columns = [f"bid_price_{level}", f"bid_volume_{level}", f"ask_price_{level}", f"ask_volume_{level}"]
        result[f"l{level}"] = int(data[columns].notna().all(axis=1).sum()) if all(c in data.columns for c in columns) else 0
    return result


def _safe_orderbook_table(orderbook: pd.DataFrame) -> pd.DataFrame:
    if orderbook is None or orderbook.empty:
        return pd.DataFrame()
    table = orderbook.copy()
    required_columns = {
        "stock_code": "",
        "orderbook_status": "⚪ SCHEMA TIDAK TERSEDIA",
        "orderbook_signal": "⚪ DATA TIDAK CUKUP",
        "book_pressure_pct": float("nan"),
        "orderbook_imbalance_pct": float("nan"),
        "best_bid": float("nan"),
        "best_ask": float("nan"),
        "spread": float("nan"),
        "spread_pct": float("nan"),
    }
    for column, default in required_columns.items():
        if column not in table.columns:
            table[column] = default
    return table


def _orderbook_sort_key(table: pd.DataFrame) -> pd.DataFrame:
    table = _safe_orderbook_table(table)
    if table.empty:
        return table
    sort_cols = [c for c in ["orderbook_status", "book_pressure_pct"] if c in table.columns]
    if not sort_cols:
        return table
    return table.sort_values(sort_cols, ascending=[True] * len(sort_cols), na_position="last")


st.title("📈 BEI Screener — Multi-Horizon Accumulation + Bid/Offer")
st.caption("Blueprint: Net Buy 3D → 5D → 10D → 20D → 60D → 100D → 200D + technicals + available Bid/Offer snapshot")

try:
    restore_result = restore_if_needed()
except Exception as exc:
    restore_result = {"restored": False, "error": str(exc)}

if not st.session_state.get("canonical_sync_checked"):
    try:
        sync_result = sync_local_from_supabase(force=True)
    except Exception as exc:
        sync_result = {"synced": False, "reason": "sync_error", "error": str(exc)}
    st.session_state.canonical_sync_checked = True
    st.session_state.canonical_sync_result = sync_result
else:
    sync_result = st.session_state.get("canonical_sync_result", {"synced": False, "reason": "already_checked"})

if sync_result.get("synced"):
    st.info(f"🔄 Histori lokal diselaraskan dengan sumber kanonik: {int(sync_result.get('rows', 0)):,} baris | tanggal terakhir {sync_result.get('latest_date', '-')}")
elif sync_result.get("reason") == "sync_error":
    st.error("⚠️ Sumber kanonik tidak dapat diverifikasi. Analisis baru dikunci agar aplikasi tidak menampilkan angka dari data lokal yang mungkin stale. " + f"Detail: {sync_result.get('error', '-')}")
    st.stop()

info = database_info()
persistence_cfg = persistence_config()
persistence_info = persistence_status()
with st.sidebar:
    st.header("⚙️ Pengaturan")
    threshold = st.number_input("Filter Net Buy 3D (%)", min_value=0.0, max_value=100.0, value=65.0, step=1.0)
    st.write(f"📦 Database: {info['total_rows']:,} baris")
    st.write(f"🏷️ Saham: {info['total_stocks']:,}")
    st.write(f"📅 Hari: {info['total_days']:,}")
    st.write(f"📖 Baris dengan field Bid/Offer: {info['orderbook_rows']:,}")
    st.divider()
    st.subheader("💾 Penyimpanan durable")
    if not persistence_cfg["enabled"]:
        st.error("Belum aktif. Upload dikunci agar data tidak hilang saat redeploy.")
        st.caption("Tambahkan SUPABASE_SECRET_KEY untuk primary Supabase, atau GITHUB_TOKEN untuk secondary recovery snapshot.")
    elif restore_result.get("restored"):
        st.success(f"Database dipulihkan: {int(restore_result.get('rows', 0)):,} baris")
        st.caption(_persistence_summary(persistence_info))
    elif restore_result.get("error"):
        st.error(f"Gagal memulihkan storage: {restore_result['error']}")
    else:
        st.success(_persistence_summary(persistence_info))

if "upload_notice" in st.session_state:
    upload_notice = st.session_state.pop("upload_notice")
    if upload_notice["kind"] == "success":
        st.success(upload_notice["message"])
    elif upload_notice["kind"] == "info":
        st.info(upload_notice["message"])
    else:
        st.error(upload_notice["message"])

st.subheader("📂 Upload data BEI")
st.caption(
    f"Maksimal {MAX_FILES_PER_BATCH} file per batch. File yang sudah pernah masuk akan dilewati otomatis berdasarkan SHA-256, "
    "kecuali jika dipilih ulang untuk memperbaiki field historis yang sebelumnya kosong. "
    "Data hanya dianggap selesai setelah primary durable store berhasil; jika GitHub dikonfigurasi, recovery snapshot sekunder juga dibuat."
)

if not persistence_cfg["enabled"]:
    st.warning("🔒 Upload sementara dikunci. Kita tidak akan mengulangi kejadian data hilang: aktifkan Persistent Storage terlebih dahulu.")

if "upload_generation" not in st.session_state:
    st.session_state.upload_generation = 0
upload_key = f"daily_upload_{st.session_state.upload_generation}"

files = st.file_uploader(
    "Pilih satu atau beberapa file Ringkasan Saham BEI",
    type=["xlsx", "xls"],
    accept_multiple_files=True,
    key=upload_key,
    disabled=not persistence_cfg["enabled"],
    help=f"Pilih hingga {MAX_FILES_PER_BATCH} file. File lama yang dipilih ulang akan masuk mode repair, bukan membuat upload ledger baru.",
)

if files:
    st.success(f"📎 {len(files)} file siap diproses: " + ", ".join(file.name for file in files))

submitted = st.button("🚀 Proses Upload", type="primary", use_container_width=True, disabled=not persistence_cfg["enabled"] or not files)

if submitted:
    if not files:
        st.warning("Pilih minimal satu file Excel terlebih dahulu.")
        st.stop()
    if len(files) > MAX_FILES_PER_BATCH:
        st.error(f"❌ Terlalu banyak file: {len(files)}. Maksimal {MAX_FILES_PER_BATCH} file per batch.")
        st.stop()

    file_entries = [(file, sha256_bytes(file.getvalue())) for file in files]
    already_uploaded = existing_hashes(sha for _, sha in file_entries)
    new_entries = [(file, file_sha) for file, file_sha in file_entries if file_sha not in already_uploaded]
    if already_uploaded:
        st.info(f"♻️ {len(already_uploaded)} file sudah ada. File akan diverifikasi dan diperbaiki hanya pada field historis yang kosong; ledger dan jumlah upload tidak bertambah.")

    entries_to_read = new_entries if new_entries else file_entries
    all_frames: list[pd.DataFrame] = []
    file_records: list[dict] = []
    progress = st.progress(0, text=f"Membaca 0/{len(entries_to_read)} file...")

    for index, (file, file_sha) in enumerate(entries_to_read, start=1):
        try:
            raw = pd.read_excel(BytesIO(file.getvalue()))
            normalized = normalize_dataframe(raw)
            if normalized.empty:
                raise ValueError("File tidak berisi baris data.")
            all_frames.append(normalized)
            completeness = _orderbook_completeness(normalized)
            file_records.append({"sha256": file_sha, "filename": file.name, "size_bytes": len(file.getvalue()), "rows_read": len(normalized), "rows_saved": len(normalized)})
            st.success(f"✅ {file.name}: {len(normalized):,} baris | L1 lengkap: {completeness['l1']:,} | L2: {completeness['l2']:,} | L3: {completeness['l3']:,} | L4: {completeness['l4']:,} | L5: {completeness['l5']:,}")
            if any(completeness[f"l{level}"] < len(normalized) for level in range(1, 6)):
                st.caption("ℹ️ Level Bid/Offer yang tidak tersedia dibiarkan kosong; aplikasi tidak mengisi atau mengestimasi angka yang tidak ada di file sumber.")
        except Exception as exc:
            st.error(f"❌ {file.name}: {exc}")
        finally:
            progress.progress(index / len(entries_to_read), text=f"Membaca {index}/{len(entries_to_read)} file...")

    if all_frames:
        try:
            with st.spinner("💾 Menyimpan dan memverifikasi batch..."):
                if already_uploaded and not new_entries:
                    repair_result = repair_frames(all_frames)
                    result = save_upload_batch(all_frames, file_records)
                    backup_result = backup_database()
                    message = f"🔧 Historical repair selesai: {repair_result['daily_updated']:,} field-row diperiksa/diperbaiki dan {repair_result['orderbook_updated']:,} snapshot diperiksa/diperbaiki. Ledger tidak bertambah. {_backup_confirmation(backup_result)}"
                    st.session_state.upload_notice = {"kind": "success", "message": message}
                else:
                    result = save_upload_batch(all_frames, file_records)
                    backup_result = backup_database()
                    message = f"💾 Selesai dan aman: {result['files_saved']} file | {result['rows_saved']:,} baris unik disimpan/di-update | {result['orderbook_rows']:,} snapshot orderbook | {_backup_confirmation(backup_result)}"
                    st.session_state.upload_notice = {"kind": "success", "message": message}
            progress.empty()
            st.session_state.upload_generation += 1
            st.rerun()
        except Exception as exc:
            progress.empty()
            st.session_state.upload_notice = {"kind": "error", "message": "❌ Batch belum dianggap selesai karena persistence/backup gagal. Data tidak akan kami anggap aman sebelum primary durable store berhasil: " + str(exc)}
            st.rerun()

st.divider()
data = load_data()
orderbook_raw = _embedded_orderbook(data)
orderbook = _safe_orderbook_table(summarize_orderbook(orderbook_raw))

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
latest_date = pd.to_datetime(data["trade_date"], errors="coerce", format="%Y-%m-%d").max()
latest_date_display = latest_date.strftime("%Y-%m-%d") if pd.notna(latest_date) else "-"
st.write(f"Data terakhir: **{latest_date_display}** | {len(data):,} baris | Snapshot Bid/Offer: **{len(orderbook):,} saham**")

if len(data["trade_date"].unique()) < 200:
    days_available = int(data["trade_date"].nunique())
    st.warning(f"⏳ Histori saat ini baru **{days_available}/200 hari bursa**. RSI14/SMA20/SMA50/SMA200/Volume20/ATR14 yang belum memenuhi window akan sengaja tetap kosong — aplikasi tidak mengarang angka. Upload histori berikutnya untuk mengaktifkan teknikal penuh.")

screened = screen(data, threshold=threshold, orderbook=orderbook)
st.subheader(f"🔥 Kandidat: Net Buy 3D > {threshold:.0f}% + Multi-Horizon 3D–200D")

if screened.empty:
    st.warning("Belum ada saham yang lolos. Pastikan minimal 3 hari data Foreign Buy/Sell tersedia.")
else:
    display = screened.copy()
    for days in HORIZONS:
        display[f"NB {days}D %"] = display[f"net_buy_pct_{days}d"].round(2)
    display["RSI14"] = display["rsi14"].round(1)
    display["SMA20"] = display["sma20"].round(0)
    display["SMA50"] = display["sma50"].round(0)
    display["SMA200"] = display["sma200"].round(0)
    display["Vol Ratio"] = display["volume_ratio"].round(2)
    display["OB Pressure %"] = display["book_pressure_pct"].round(2) if "book_pressure_pct" in display else pd.NA
    display["OB Imbalance %"] = display["orderbook_imbalance_pct"].round(2) if "orderbook_imbalance_pct" in display else pd.NA
    display["Score"] = display["score"].round(2)
    display["Target Low"] = display["target_low"].round(0)
    display["Target High"] = display["target_high"].round(0)
    display["Stop Loss"] = display["stop_loss"].round(0)
    cols = ["stock_code", "company_name", "as_of_date", "close_price"] + [f"NB {d}D %" for d in HORIZONS] + ["signal", "quality", "Score", "technical_status", "RSI14", "SMA20", "SMA50", "SMA200", "Vol Ratio", "OB Pressure %", "OB Imbalance %", "orderbook_signal", "orderbook_status", "Target Low", "Target High", "Stop Loss"]
    cols = [c for c in cols if c in display.columns]
    candidate_config = {
        "stock_code": st.column_config.TextColumn("Stock", pinned=True),
        "company_name": st.column_config.TextColumn("Company", pinned=True),
        "as_of_date": st.column_config.TextColumn("Data per", help="Tanggal perdagangan terakhir yang menjadi sumber Close dan indikator kandidat."),
        "close_price": st.column_config.NumberColumn("Close", format="%.0f"),
    }
    st.dataframe(display[cols], use_container_width=True, hide_index=True, column_config={k: v for k, v in candidate_config.items() if k in cols})

    st.subheader("🎯 Detail kandidat")
    for _, row in screened.head(100).iterrows():
        with st.expander(f"{row['stock_code']} — {row.get('signal', '-')} | 3D {row.get('net_buy_pct_3d', float('nan')):.2f}% | Score {row.get('score', 0):.2f}"):
            st.caption(f"**Data per: {pd.Timestamp(row.get('as_of_date')).strftime('%Y-%m-%d') if pd.notna(row.get('as_of_date')) else '-'}** — Close dan seluruh indikator di bawah berasal dari histori sampai tanggal ini.")
            c1, c2, c3, c4, c5 = st.columns(5)
            c1.metric("Close", _fmt(row.get("close_price")))
            c2.metric("RSI14", _fmt(row.get("rsi14"), 1))
            c3.metric("SMA200", _fmt(row.get("sma200")))
            c4.metric("Vol Ratio", _fmt(row.get("volume_ratio"), 2))
            c5.metric("OB Pressure", _fmt(row.get("book_pressure_pct"), 1))
            st.info(f"**Technical readiness:** {row.get('technical_status', '-')}")
            horizon_cols = st.columns(len(HORIZONS))
            for col, days in zip(horizon_cols, HORIZONS):
                value = row.get(f"net_buy_pct_{days}d")
                available = row.get(f"days_available_{days}d", 0)
                col.metric(f"NB {days}D", _fmt(value, 1), f"{int(available)}/{days} hari" if pd.notna(value) else "-")
            st.write(f"**Kualitas akumulasi:** {row.get('quality', '-')}")
            st.write(f"**Bid/Offer:** {row.get('orderbook_signal', '⚪ Tidak ada')} | Status: {row.get('orderbook_status', '-')} | Pressure {_fmt(row.get('book_pressure_pct'), 2)}% | Imbalance {_fmt(row.get('orderbook_imbalance_pct'), 2)}%")
            st.write(f"**Alasan:** {row.get('reason', '-')}")
            st.write(f"**Target 1 minggu (indikatif, berbasis ATR14 aktual):** {_fmt(row.get('target_low'))} — {_fmt(row.get('target_high'))} | **Stop loss:** {_fmt(row.get('stop_loss'))}")

st.divider()
st.subheader("🎯 Post-Target Analysis & Validation")
st.caption("Setiap target historis dihitung hanya dari data pada tanggal prediksi. Data setelahnya dipakai khusus untuk mengukur hasil: Target Low/High hit, stop, volume saat target, rejection, lalu CONTINUE / CONSOLIDATION / REVERSAL. Jika data lanjutan belum tersedia, status tetap menunggu — tidak ada angka yang diisi.")
try:
    target_events = evaluate_target_history(data, threshold=threshold, target_window=5, post_window=3)
except Exception as exc:
    target_events = pd.DataFrame()
    st.error(f"Post-target validation gagal dihitung: {exc}")

if target_events.empty:
    st.info("Belum ada event target yang dapat divalidasi. Dibutuhkan ATR14 + Net Buy 3D > threshold pada tanggal prediksi.")
else:
    completed = target_events[target_events["validation_complete"]]
    high_hits = target_events[target_events["hit_type"] == "HIGH"]
    continue_hits = target_events[target_events["post_status"].str.startswith("🟢", na=False)]
    consolidation_hits = target_events[target_events["post_status"].str.startswith("🟡", na=False)]
    reversal_hits = target_events[target_events["post_status"].str.startswith("🔴", na=False)]
    m1, m2, m3, m4, m5 = st.columns(5)
    m1.metric("Event prediksi", f"{len(target_events):,}")
    m2.metric("Target High hit", f"{len(high_hits):,}")
    m3.metric("Continue", f"{len(continue_hits):,}")
    m4.metric("Konsolidasi", f"{len(consolidation_hits):,}")
    m5.metric("Reversal/Koreksi", f"{len(reversal_hits):,}")
    st.caption(f"Validasi penuh 5 hari: {len(completed):,}/{len(target_events):,} event. Event terbaru yang belum punya cukup data tetap ditandai PENDING.")

    validation_display = target_events.copy()
    validation_display["Prediction"] = validation_display["prediction_date"].dt.strftime("%Y-%m-%d")
    validation_display["Hit Date"] = validation_display["hit_date"].dt.strftime("%Y-%m-%d")
    validation_display["Close"] = validation_display["prediction_close"].round(0)
    validation_display["NB 3D %"] = validation_display["nb3_pct"].round(2)
    validation_display["Target Low"] = validation_display["target_low"].round(0)
    validation_display["Target High"] = validation_display["target_high"].round(0)
    validation_display["Stop"] = validation_display["stop_loss"].round(0)
    validation_display["Hit Volume Ratio"] = validation_display["hit_volume_ratio"].round(2)
    validation_display["Hit RSI14"] = validation_display["hit_rsi14"].round(1)
    validation_display["Close Location %"] = validation_display["hit_close_location_pct"].round(1)
    validation_display["Post Last Close"] = validation_display["post_last_close"].round(0)
    validation_cols = [
        "stock_code", "Prediction", "Close", "NB 3D %", "Target Low", "Target High", "Stop",
        "outcome", "Hit Date", "Hit Volume Ratio", "Hit RSI14", "Close Location %",
        "volume_confirmation", "rejection", "post_status", "Post Last Close", "validation_complete",
    ]
    validation_cols = [c for c in validation_cols if c in validation_display.columns]
    st.dataframe(validation_display[validation_cols].head(200), use_container_width=True, hide_index=True)

    latest_events = target_events.sort_values(["prediction_date", "stock_code"], ascending=[False, True]).groupby("stock_code", as_index=False).head(1)
    st.write("**Event terbaru per saham**")
    for _, event in latest_events.head(50).iterrows():
        status = event.get("post_status") or event.get("outcome") or "⏳ PENDING"
        st.write(f"**{event['stock_code']}** — prediksi {pd.Timestamp(event['prediction_date']).strftime('%Y-%m-%d')} | target {_fmt(event['target_low'])}–{_fmt(event['target_high'])} | {status}")

st.divider()
st.subheader("🔎 Detail histori harga")
selected = st.selectbox("Pilih saham", sorted(data["stock_code"].dropna().unique()))

# Keep the manual selector alphabetical. The new section below is independent:
# it ranks stocks by aggregate foreign-buy dominance over the latest 30 trading
# sessions. The 50% rule is applied to the full 30-day aggregate, not every day.
dominance_30d = thirty_day_dominance(data, days=30, threshold=50.0)
st.subheader("🔥 Dominasi Foreign Buy 30 Hari Perdagangan")
st.caption("Filter ini TIDAK mensyaratkan Net Buy ≥50% setiap hari. Saham lolos jika akumulasi Foreign Buy / (Foreign Buy + Foreign Sell) selama 30 hari perdagangan terakhir ≥50%. Kolom hari dominan hanya informasi tambahan.")

if dominance_30d.empty:
    st.info("Belum ada saham yang memenuhi 30 hari perdagangan lengkap dengan data Foreign Buy/Sell.")
else:
    dominance_display = dominance_30d.copy()
    dominance_display["Dominasi 30D %"] = dominance_display["dominance_30d_pct"].round(2)
    dominance_display["Hari ≥50%"] = dominance_display["dominant_days_30d"]
    dominance_display["Dominasi Harian %"] = dominance_display["dominant_days_pct"].round(1)
    dominance_display["Net Buy 30D"] = dominance_display["net_buy_30d"].round(0)
    dominance_display["Close"] = dominance_display["close_price"].round(0)
    dominance_display["Volume"] = dominance_display["volume"].round(0)
    dominance_display["Data per"] = pd.to_datetime(dominance_display["as_of_date"], errors="coerce").dt.strftime("%Y-%m-%d")
    dominance_cols = [
        "stock_code", "company_name", "Data per", "Close", "Volume",
        "Dominasi 30D %", "Hari ≥50%", "Dominasi Harian %", "Net Buy 30D",
    ]
    dominance_cols = [c for c in dominance_cols if c in dominance_display.columns]
    st.dataframe(
        dominance_display[dominance_cols].head(200),
        use_container_width=True,
        hide_index=True,
        column_config={
            "stock_code": st.column_config.TextColumn("Stock", pinned=True),
            "company_name": st.column_config.TextColumn("Company", pinned=True),
            "Dominasi 30D %": st.column_config.NumberColumn("Dominasi 30D", format="%.2f%%"),
            "Dominasi Harian %": st.column_config.NumberColumn("Hari Dominan", format="%.1f%%"),
            "Net Buy 30D": st.column_config.NumberColumn("Net Buy 30D", format="%.0f"),
        },
    )
    st.caption(f"🟢 {len(dominance_30d):,} saham lolos. Ranking diurutkan dari dominasi agregat 30D tertinggi; bukan berdasarkan abjad.")

stock_history = data[data["stock_code"] == selected].sort_values("trade_date", ascending=False)
stock_history = _format_trade_date_display(stock_history)
st.dataframe(stock_history, use_container_width=True, hide_index=True, column_config={"trade_date": st.column_config.TextColumn("trade_date", help="Format tanggal standar: YYYY-MM-DD")})

st.subheader("📖 Bid/Offer terbaru dari file BEI")
if orderbook.empty:
    st.info("File BEI belum menyediakan level Bid/Offer yang dapat dibaca.")
else:
    safe_orderbook = _orderbook_sort_key(orderbook)
    latest_completeness = _orderbook_completeness(data[data["trade_date"] == latest_date])
    st.caption("Hanya level yang benar-benar tersedia di file sumber yang dihitung. Level yang tidak tersedia tetap kosong dan tidak pernah diisi dengan angka estimasi.")
    completeness_cols = st.columns(5)
    latest_total = len(data[data["trade_date"] == latest_date])
    for index, level in enumerate(range(1, 6)):
        completeness_cols[index].metric(f"L{level} lengkap", f"{latest_completeness[f'l{level}']:,}/{latest_total:,}")
    orderbook_config = {
        "stock_code": st.column_config.TextColumn("Stock", pinned=True),
        "best_bid": st.column_config.NumberColumn("Best Bid", format="%.0f"),
        "best_ask": st.column_config.NumberColumn("Best Ask", format="%.0f"),
        "spread": st.column_config.NumberColumn("Spread", format="%.0f"),
        "spread_pct": st.column_config.NumberColumn("Spread %", format="%.2f%%"),
        "bid_depth_5": st.column_config.NumberColumn("Bid Depth Available", format="%.0f"),
        "ask_depth_5": st.column_config.NumberColumn("Offer Depth Available", format="%.0f"),
        "book_pressure_pct": st.column_config.NumberColumn("Bid Pressure %", format="%.2f%%"),
        "orderbook_imbalance_pct": st.column_config.NumberColumn("Imbalance %", format="%.2f%%"),
    }
    st.dataframe(safe_orderbook, use_container_width=True, hide_index=True, column_config={k: v for k, v in orderbook_config.items() if k in safe_orderbook.columns})
