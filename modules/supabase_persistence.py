from __future__ import annotations

import json
import os
from collections.abc import Iterable

import pandas as pd
import requests
import streamlit as st

from .database import DAILY_ORDERBOOK_COLUMNS, normalize_dataframe

DEFAULT_SUPABASE_URL = "https://kgaxmrzyuzajeeuaatcb.supabase.co"
RPC_PATH = "/rest/v1/rpc/persist_upload_batch"
TIMEOUT_SECONDS = 120


def _secret(name: str, default: str = "") -> str:
    try:
        value = st.secrets.get(name, default)
    except Exception:
        value = os.getenv(name, default)
    return str(value).strip()


def config() -> dict[str, str | bool]:
    url = _secret("SUPABASE_URL", DEFAULT_SUPABASE_URL).rstrip("/")
    key = _secret("SUPABASE_SECRET_KEY") or _secret("SUPABASE_SERVICE_ROLE_KEY")
    return {"enabled": bool(url and key), "url": url, "key": key}


def _headers(key: str) -> dict[str, str]:
    return {
        "apikey": key,
        "Authorization": f"Bearer {key}",
        "Content-Type": "application/json",
        "Accept": "application/json",
        "User-Agent": "bei-screener-supabase-persistence",
    }


def _json_default(value):
    if value is None:
        return None
    if isinstance(value, pd.Timestamp):
        return value.isoformat()
    if hasattr(value, "item"):
        try:
            return value.item()
        except Exception:
            pass
    return str(value)


def _json_safe(value):
    return json.loads(json.dumps(value, ensure_ascii=False, default=_json_default))


def _row_to_json(row: pd.Series) -> dict:
    payload = {}
    for key, value in row.items():
        try:
            if pd.isna(value):
                value = None
        except (TypeError, ValueError):
            pass
        payload[str(key)] = value
    return _json_safe(payload)


def _post_rpc(payload: dict) -> dict:
    cfg = config()
    if not cfg["enabled"]:
        raise RuntimeError(
            "Supabase historical persistence belum dikonfigurasi. "
            "Tambahkan SUPABASE_SECRET_KEY ke Streamlit Secrets."
        )
    response = requests.post(
        f"{cfg['url']}{RPC_PATH}",
        headers=_headers(str(cfg["key"])),
        json=payload,
        timeout=TIMEOUT_SECONDS,
    )
    if response.status_code >= 400:
        raise RuntimeError(f"Supabase RPC {response.status_code}: {response.text[:2000]}")
    body = response.json()
    if isinstance(body, list) and body and isinstance(body[0], dict):
        return body[0]
    if not isinstance(body, dict):
        raise RuntimeError("Supabase RPC mengembalikan format yang tidak dikenal.")
    return body


def _existing_remote_hashes(hashes: list[str]) -> set[str]:
    """Return upload hashes already committed in Supabase."""
    cfg = config()
    values = sorted({str(value) for value in hashes if value})
    if not cfg["enabled"] or not values:
        return set()
    response = requests.get(
        f"{cfg['url']}/rest/v1/upload_ledger",
        headers=_headers(str(cfg["key"])),
        params={"select": "sha256", "sha256": f"in.({','.join(values)})"},
        timeout=30,
    )
    if response.status_code >= 400:
        raise RuntimeError(f"Supabase upload ledger {response.status_code}: {response.text[:2000]}")
    body = response.json()
    return {str(item["sha256"]) for item in body if isinstance(item, dict) and item.get("sha256")}


def status() -> dict[str, object]:
    cfg = config()
    result: dict[str, object] = {
        "enabled": bool(cfg["enabled"]),
        "configured": bool(cfg["enabled"]),
        "url": cfg["url"],
        "reachable": False,
        "historical_rows": 0,
    }
    if not cfg["enabled"]:
        result["reason"] = "secret_missing"
        return result
    try:
        response = requests.get(
            f"{cfg['url']}/rest/v1/stock_daily",
            headers={**_headers(str(cfg["key"])), "Prefer": "count=exact"},
            params={"select": "id", "limit": 1},
            timeout=30,
        )
        if response.status_code >= 400:
            raise RuntimeError(f"Supabase {response.status_code}: {response.text[:1000]}")
        content_range = response.headers.get("Content-Range", "")
        if "/" in content_range:
            try:
                result["historical_rows"] = int(content_range.rsplit("/", 1)[1])
            except ValueError:
                pass
        result["reachable"] = True
    except Exception as exc:
        result["error"] = str(exc)
    return result


def _daily_payload(frames: Iterable[pd.DataFrame]) -> list[dict]:
    data = pd.concat(list(frames), ignore_index=True) if frames else pd.DataFrame()
    data = normalize_dataframe(data)
    if data.empty:
        return []
    data = data.dropna(subset=["trade_date", "stock_code"]).copy()
    data = data.drop_duplicates(subset=["trade_date", "stock_code"], keep="last")
    columns = [
        "trade_date", "stock_code", "company_name", "open_price", "high_price", "low_price",
        "close_price", "volume", "value", "frequency", "foreign_sell", "foreign_buy",
        *DAILY_ORDERBOOK_COLUMNS,
    ]
    rows: list[dict] = []
    for _, row in data[columns].iterrows():
        item = _row_to_json(row)
        item["raw_data"] = _row_to_json(row)
        rows.append(item)
    return rows


def _orderbook_payload(daily_rows: list[dict]) -> list[dict]:
    rows: list[dict] = []
    for daily in daily_rows:
        levels = {column: daily.get(column) for column in DAILY_ORDERBOOK_COLUMNS}
        if not any(value is not None for value in levels.values()):
            continue
        item = {
            "snapshot_date": daily.get("trade_date"),
            "snapshot_time": "00:00:00",
            "stock_code": daily.get("stock_code"),
            **levels,
        }
        item["raw_data"] = _json_safe(item)
        rows.append(item)
    return rows


def persist_upload_batch(frames: list[pd.DataFrame], file_records: list[dict]) -> dict[str, object]:
    """Persist one upload batch to Supabase before local completion is recorded."""
    daily = _daily_payload(frames)
    orderbook = _orderbook_payload(daily)
    files = [
        {
            "sha256": str(record["sha256"]),
            "filename": str(record["filename"]),
            "size_bytes": int(record.get("size_bytes", 0)),
            "rows_read": int(record.get("rows_read", 0)),
            "rows_saved": int(record.get("rows_saved", 0)),
            "metadata": _json_safe(record.get("metadata", {})),
        }
        for record in file_records
    ]

    remote_hashes = _existing_remote_hashes([item["sha256"] for item in files])
    if remote_hashes:
        if len(remote_hashes) == len(files):
            return {
                "saved": True,
                "duplicate": True,
                "upload_run_id": None,
                "ledger_rows": 0,
                "daily_rows": 0,
                "orderbook_rows": 0,
            }
        raise RuntimeError(
            "Batch upload sebagian sudah tercatat di Supabase. "
            "Pisahkan file yang sudah pernah berhasil dari file baru sebelum retry."
        )

    result = _post_rpc(
        {
            "p_run": {
                "source": "app_upload",
                "note": f"BEI batch: {len(files)} file(s), {len(daily)} unique daily row(s)",
            },
            "p_files": files,
            "p_daily": daily,
            "p_orderbook": orderbook,
        }
    )
    return {
        "saved": True,
        "duplicate": False,
        "upload_run_id": result.get("upload_run_id"),
        "ledger_rows": int(result.get("ledger_rows", 0)),
        "daily_rows": int(result.get("daily_rows", 0)),
        "orderbook_rows": int(result.get("orderbook_rows", 0)),
    }
