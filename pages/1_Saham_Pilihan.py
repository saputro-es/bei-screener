from __future__ import annotations

import numpy as np
import pandas as pd
import streamlit as st

from modules.analysis import screen
from modules.daily_flow import daily_net_buy_volume_matrix
from modules.database import load_data
from modules.orderbook import summarize_orderbook

st.set_page_config(page_title="Saham Pilihan", page_icon="🎯", layout="wide")

st.title("🎯 Saham Pilihan — Ranking Otomatis")
st.caption(
    "Tidak perlu mencari saham berdasarkan abjad. Mesin memprioritaskan saham dengan Net Buy harian konsisten >50%, "
    "volume terbaru ≥1.000 lot, lalu mengurutkannya berdasarkan kualitas akumulasi."
)

data = load_data()
if data is None or data.empty:
    st.info("Belum ada histori BEI. Upload data terlebih dahulu dari halaman utama.")
    st.stop()

required = {"stock_code", "trade_date", "foreign_buy", "foreign_sell", "volume"}
missing = sorted(required - set(data.columns))
if missing:
    st.error("Schema histori belum lengkap: " + ", ".join(missing))
    st.stop()

# Canonical daily values: D1 is the latest available trading day for each stock.
daily = daily_net_buy_volume_matrix(data, days=max(30, int(data["trade_date"].nunique())))
if daily.empty:
    st.info("Belum ada data daily Net Buy yang dapat dihitung.")
    st.stop()

# Use all available valid daily Net Buy observations for the consistency test.
nb_cols = [c for c in daily.columns if c.endswith("_net_buy_pct")]
latest_nb = daily["d1_net_buy_pct"]
latest_vol = daily["d1_volume_lot"]
valid_nb = daily[nb_cols].apply(pd.to_numeric, errors="coerce")
valid_counts = valid_nb.notna().sum(axis=1)

ranking = daily[["stock_code", "daily_days_available"]].copy()
ranking["latest_nb_pct"] = latest_nb
ranking["latest_volume_lot"] = latest_vol
ranking["valid_nb_days"] = valid_counts
ranking["avg_nb_pct"] = valid_nb.mean(axis=1, skipna=True)
ranking["min_nb_pct"] = valid_nb.min(axis=1, skipna=True)

# Current source row per stock, used for company name and latest date.
source = data.copy()
source["trade_date"] = pd.to_datetime(source["trade_date"], errors="coerce")
source = source.dropna(subset=["stock_code", "trade_date"]).sort_values("trade_date").groupby("stock_code", as_index=False).tail(1)
source = source[[c for c in ["stock_code", "company_name", "trade_date", "close_price"] if c in source.columns]]
ranking = ranking.merge(source, on="stock_code", how="left")

# Keep the existing multi-horizon analysis as a secondary quality/risk layer.
orderbook_raw = pd.DataFrame()
ob_columns = [c for c in data.columns if c.startswith(("bid_price_", "bid_volume_", "ask_price_", "ask_volume_"))]
if ob_columns:
    orderbook_raw = data[[c for c in ["trade_date", "stock_code"] + ob_columns if c in data.columns]].copy()
    if not orderbook_raw.empty:
        orderbook_raw = orderbook_raw.rename(columns={"trade_date": "snapshot_date"})
        orderbook_raw["snapshot_time"] = "00:00:00"
        orderbook_raw = orderbook_raw[[c for c in ["snapshot_date", "snapshot_time", "stock_code"] + ob_columns if c in orderbook_raw.columns]]
        orderbook_raw = orderbook_raw[orderbook_raw[ob_columns].notna().any(axis=1)]
orderbook = summarize_orderbook(orderbook_raw) if not orderbook_raw.empty else pd.DataFrame()

threshold = st.number_input("Minimal Net Buy harian (%)", min_value=0.0, max_value=100.0, value=50.0, step=1.0)
min_volume = st.number_input("Minimal volume terbaru (lot)", min_value=0, value=1000, step=100)
min_valid_days = st.number_input(
    "Minimal hari Net Buy valid",
    min_value=1,
    max_value=max(1, len(nb_cols)),
    value=min(3, max(1, len(nb_cols))),
    step=1,
)

# A stock passes only when EVERY valid daily Net Buy observation is above the
# selected threshold. Missing source values are ignored rather than fabricated.
valid_above_threshold = valid_nb.gt(threshold)
ranking["above_threshold_days"] = valid_above_threshold.sum(axis=1)
ranking["consistency_pct"] = np.where(
    ranking["valid_nb_days"] > 0,
    ranking["above_threshold_days"] / ranking["valid_nb_days"] * 100.0,
    np.nan,
)
ranking["passes_consistency"] = (
    (ranking["valid_nb_days"] >= min_valid_days)
    & (ranking["above_threshold_days"] == ranking["valid_nb_days"])
)
ranking["passes_volume"] = ranking["latest_volume_lot"] >= min_volume

candidates = ranking[ranking["passes_consistency"] & ranking["passes_volume"]].copy()

# Merge the existing screener score only for candidates. This does not change the
# existing screener logic; it adds a user-friendly selection/ranking layer.
screened = screen(data, threshold=50.0, orderbook=orderbook)
if not screened.empty:
    score_cols = [c for c in ["stock_code", "signal", "quality", "score", "technical_status", "rsi14", "target_low", "target_high", "stop_loss"] if c in screened.columns]
    candidates = candidates.merge(screened[score_cols], on="stock_code", how="left")
else:
    candidates["score"] = np.nan

candidates["score"] = pd.to_numeric(candidates.get("score"), errors="coerce")
candidates = candidates.sort_values(
    ["consistency_pct", "avg_nb_pct", "latest_volume_lot", "score"],
    ascending=[False, False, False, False],
    na_position="last",
).reset_index(drop=True)

st.subheader("🏆 Kandidat yang lolos")
st.write(
    f"**{len(candidates):,} saham** lolos dari filter: seluruh Net Buy harian yang valid > {threshold:.0f}% "
    f"+ volume terbaru ≥ {min_volume:,} lot + minimal {min_valid_days} hari valid."
)

if candidates.empty:
    st.warning("Tidak ada saham yang memenuhi filter. Turunkan minimal hari valid atau volume jika ingin memperluas kandidat.")
    st.stop()

show = candidates.copy()
show["Stock"] = show["stock_code"]
show["Company"] = show.get("company_name", "-")
show["Latest NB %"] = show["latest_nb_pct"].round(2)
show["Avg NB %"] = show["avg_nb_pct"].round(2)
show["Min NB %"] = show["min_nb_pct"].round(2)
show["Consistency"] = show["consistency_pct"].round(1)
show["Valid Days"] = show["valid_nb_days"]
show["Volume (lot)"] = show["latest_volume_lot"].round(0)
show["Score"] = show["score"].round(2)
show["Signal"] = show.get("signal", pd.Series("-", index=show.index)).fillna("-")
show["Quality"] = show.get("quality", pd.Series("-", index=show.index)).fillna("-")
cols = ["Stock", "Company", "Latest NB %", "Avg NB %", "Min NB %", "Consistency", "Valid Days", "Volume (lot)", "Score", "Signal", "Quality"]
st.dataframe(show[cols], use_container_width=True, hide_index=True)

st.divider()
st.subheader("🔎 Pilih saham untuk dianalisis")

options = candidates["stock_code"].astype(str).tolist()
lookup = candidates.set_index("stock_code")

def _label(code: str) -> str:
    row = lookup.loc[code]
    company = str(row.get("company_name") or "")
    return (
        f"{code} — {company} | NB terbaru {float(row['latest_nb_pct']):.1f}% | "
        f"rata-rata {float(row['avg_nb_pct']):.1f}% | volume {float(row['latest_volume_lot']):,.0f} lot"
    )

selected_codes = st.multiselect(
    "Pilih satu atau beberapa saham",
    options=options,
    format_func=_label,
    default=options[:1],
    max_selections=20,
    help="Daftar sudah diranking otomatis; saham tidak lagi disajikan berdasarkan abjad.",
)

if not selected_codes:
    st.info("Pilih saham di atas untuk melihat detail dan histori.")
    st.stop()

selected_data = candidates[candidates["stock_code"].isin(selected_codes)].copy()
for _, row in selected_data.iterrows():
    code = row["stock_code"]
    with st.expander(_label(code), expanded=True):
        m1, m2, m3, m4 = st.columns(4)
        m1.metric("NB terbaru", f"{row['latest_nb_pct']:.2f}%")
        m2.metric("Rata-rata NB", f"{row['avg_nb_pct']:.2f}%")
        m3.metric("Minimum NB", f"{row['min_nb_pct']:.2f}%")
        m4.metric("Konsistensi", f"{row['consistency_pct']:.1f}%")
        st.write(
            f"**Volume terbaru:** {row['latest_volume_lot']:,.0f} lot | "
            f"**Hari valid:** {int(row['valid_nb_days'])} | **Score:** {row.get('score', np.nan):.2f}"
        )
        if pd.notna(row.get("signal")):
            st.write(f"**Signal:** {row['signal']} | **Quality:** {row.get('quality', '-')}")
        if pd.notna(row.get("technical_status")):
            st.caption(str(row["technical_status"]))
        if all(pd.notna(row.get(c)) for c in ["target_low", "target_high", "stop_loss"]):
            st.write(f"**Target:** {row['target_low']:.0f}–{row['target_high']:.0f} | **Stop loss:** {row['stop_loss']:.0f}")

        history = data[data["stock_code"] == code].copy().sort_values("trade_date", ascending=False)
        history["trade_date"] = pd.to_datetime(history["trade_date"], errors="coerce").dt.strftime("%Y-%m-%d")
        display_cols = [c for c in ["trade_date", "close_price", "volume", "foreign_buy", "foreign_sell"] + ob_columns if c in history.columns]
        st.dataframe(history[display_cols].head(60), use_container_width=True, hide_index=True)
