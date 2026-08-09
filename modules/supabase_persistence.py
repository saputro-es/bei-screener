from __future__ import annotations

import os
import uuid

import pandas as pd
import requests
import streamlit as st

from .analysis import _technical_readiness, add_indicators
from .database import DAILY_ORDERBOOK_COLUMNS, load_data, normalize_dataframe

DEFAULT_TIMEOUT = 120
RPC_NAME = "persist_bei_historical_batch"


def _secret(*names: str, default: str = "") -> str:
    for name in names:
        try:
            value = st.secrets.get(name, "")
        except Exception:
            value = ""
        if value:
            return str(value).strip()
        value = os.getenv(name, "")
        if value:
            return str(value).strip()
    return default


def config() -> dict[str, object]:
    url = _secret("SUPABASE_URL")
    secret_key = _secret("SUPABASE_SECRET_KEY", "SUPABASE_SERVICE_ROLE_KEY")
    return {"enabled": bool(url and secret_key), "url": url.rstrip("/"), "key": secret_key}


def _headers(key: str) -> dict[str, str]:
    return {"apikey": key, "Authorization": f"Bearer {key}", "Content-Type": "application/json", "Accept": "application/json"}


def _json_value(value):
    if isinstance(value, pd.Timestamp):
        return value.strftime("%Y-%m-%d")
    if hasattr(value, "item"):
        value = value.item()
    try:
        if pd.isna(value):
            return None
    except (TypeError, ValueError):
        pass
    return value


def _records(frame: pd.DataFrame) -> list[dict]:
    if frame.empty:
        return []
    return [{str(key): _json_value(value) for key, value in row.items()} for row in frame.to_dict(orient="records")]


def _technical_records(normalized: pd.DataFrame, full_history: pd.DataFrame) -> list[dict]:
    if normalized.empty or full_history.empty:
        return []
    indicators = add_indicators(full_history)
    indicators["trade_date"] = pd.to_datetime(indicators["trade_date"], errors="coerce").dt.strftime("%Y-%m-%d")
    keys = normalized[["trade_date", "stock_code"]].copy()
    keys["trade_date"] = pd.to_datetime(keys["trade_date"], errors="coerce").dt.strftime("%Y-%m-%d")
    keys["stock_code"] = keys["stock_code"].astype(str).str.upper().str.strip()
    selected = indicators.merge(keys.drop_duplicates(), on=["trade_date", "stock_code"], how="inner")
    if selected.empty:
        return []
    rows: list[dict] = []
    for code, group in selected.groupby("stock_code"):
        history = full_history[full_history["stock_code"].astype(str).str.upper().str.strip() == code]
        history_days, technical_status = _technical_readiness(history)
        for _, row in group.sort_values("trade_date").iterrows():
            rows.append({
                "trade_date": row.get("trade_date"), "stock_code": code,
                "sma20": row.get("sma20"), "sma50": row.get("sma50"), "sma200": row.get("sma200"),
                "volume_ma20": row.get("volume_ma20"), "volume_ratio": row.get("volume_ratio"),
                "rsi14": row.get("rsi14"), "atr14": row.get("atr14"),
                "horizons_available": None, "history_days": history_days, "technical_status": technical_status,
            })
    return _records(pd.DataFrame(rows))


def _rpc(payload: dict) -> dict:
    cfg = config()
    if not cfg["enabled"]:
        raise RuntimeError("Supabase belum dikonfigurasi. Tambahkan SUPABASE_URL dan SUPABASE_SECRET_KEY ke Streamlit Secrets.")
    response = requests.post(
        f"{cfg['url']}/rest/v1/rpc/{RPC_NAME}",
        headers=_headers(str(cfg["key"])), json=payload, timeout=DEFAULT_TIMEOUT,
    )
    if response.status_code >= 400:
        raise RuntimeError(f"Supabase RPC {response.status_code}: {response.text[:1500]}")
    data = response.json()
    if isinstance(data, list) and data:
        return data[0] if isinstance(data[0], dict) else {"result": data[0]}
    return data if isinstance(data, dict) else {"result": data}


def persist_historical_batch(frames: list[pd.DataFrame], file_records: list[dict]) -> dict[str, object]:
    """Persist each uploaded file as an idempotent historical run in Supabase."""
    if not frames:
        return {"enabled": config()["enabled"], "files": 0, "stock_rows": 0, "orderbook_rows": 0, "technical_rows": 0}
    if len(frames) != len(file_records):
        raise ValueError("Jumlah frame upload dan file_records tidak sama.")
    if not config()["enabled"]:
        raise RuntimeError("Supabase historical persistence belum aktif.")

    full_history = load_data()
    totals = {"enabled": True, "files": 0, "stock_rows": 0, "orderbook_rows": 0, "technical_rows": 0}
    for frame, record in zip(frames, file_records):
        normalized = normalize_dataframe(frame).dropna(subset=["trade_date", "stock_code"])
        normalized = normalized.drop_duplicates(subset=["trade_date", "stock_code"], keep="last")
        if normalized.empty:
            continue
        sha = str(record["sha256"])
        run_id = str(uuid.uuid5(uuid.NAMESPACE_URL, f"bei-screener-upload:{sha}"))
        ob = normalized[["trade_date", "stock_code"] + DAILY_ORDERBOOK_COLUMNS].copy().rename(columns={"trade_date": "snapshot_date"})
        ob["snapshot_time"] = "00:00:00"
        ob = ob[["snapshot_date", "snapshot_time", "stock_code"] + DAILY_ORDERBOOK_COLUMNS]
        ob = ob[ob[DAILY_ORDERBOOK_COLUMNS].notna().any(axis=1)]
        result = _rpc({
            "p_upload_run_id": run_id,
            "p_upload_ledger": [{
                "sha256": sha, "filename": record.get("filename", ""),
                "size_bytes": int(record.get("size_bytes", 0)),
                "rows_read": int(record.get("rows_read", len(normalized))),
                "rows_saved": int(record.get("rows_saved", len(normalized))),
                "metadata": {"source": "streamlit_upload"},
            }],
            "p_stock_daily": _records(normalized),
            "p_orderbook": _records(ob),
            "p_technical": _technical_records(normalized, full_history),
        })
        totals["files"] += 1
        totals["stock_rows"] += int(result.get("stock_rows", 0))
        totals["orderbook_rows"] += int(result.get("orderbook_rows", 0))
        totals["technical_rows"] += int(result.get("technical_rows", 0))
    return totals


def status() -> dict[str, object]:
    cfg = config()
    result: dict[str, object] = {"enabled": cfg["enabled"], "configured": cfg["enabled"], "remote_available": False}
    if not cfg["enabled"]:
        return result
    try:
        response = requests.get(
            f"{cfg['url']}/rest/v1/stock_daily?select=id&limit=1",
            headers=_headers(str(cfg["key"])), timeout=30,
        )
        if response.status_code >= 400:
            raise RuntimeError(f"HTTP {response.status_code}: {response.text[:500]}")
        result["remote_available"] = True
    except Exception as exc:
        result["error"] = str(exc)
    return result
