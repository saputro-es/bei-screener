from __future__ import annotations

import hashlib
import json
import os
import sqlite3
from collections.abc import Iterable

import pandas as pd
import requests
import streamlit as st

from .database import DAILY_ORDERBOOK_COLUMNS, DATABASE_FILE, init_database, save_dataframe, normalize_dataframe

DEFAULT_SUPABASE_URL = "https://kgaxmrzyuzajeeuaatcb.supabase.co"
RPC_PATH = "/rest/v1/rpc/persist_upload_batch"
TIMEOUT_SECONDS = 120
PAGE_SIZE = 1000


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
    try:
        response = requests.post(
            f"{cfg['url']}{RPC_PATH}",
            headers=_headers(str(cfg["key"])),
            json=payload,
            timeout=TIMEOUT_SECONDS,
        )
    except requests.RequestException as exc:
        raise RuntimeError(f"Supabase RPC network error: {exc}") from exc
    if response.status_code >= 400:
        raise RuntimeError(f"Supabase RPC {response.status_code}: {response.text[:2000]}")
    try:
        body = response.json()
    except ValueError as exc:
        raise RuntimeError("Supabase RPC mengembalikan respons non-JSON.") from exc
    if isinstance(body, list) and body and isinstance(body[0], dict):
        return body[0]
    if not isinstance(body, dict):
        raise RuntimeError("Supabase RPC mengembalikan format yang tidak dikenal.")
    return body


def _existing_remote_hashes(hashes: list[str]) -> set[str]:
    """Return upload hashes already committed in Supabase."""
    cfg = config()
    values = sorted({str(value).lower() for value in hashes if value})
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
    return {str(item["sha256"]).lower() for item in body if isinstance(item, dict) and item.get("sha256")}


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


def _batch_key(file_records: list[dict]) -> str:
    hashes = sorted(str(record["sha256"]).strip().lower() for record in file_records)
    if not hashes or any(len(value) != 64 for value in hashes):
        raise ValueError("SHA-256 file tidak valid.")
    return hashlib.sha256("\n".join(hashes).encode("utf-8")).hexdigest()


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
    if not frames or not file_records:
        raise ValueError("Upload batch kosong.")
    if len(file_records) > 20:
        raise ValueError("Maksimal 20 file per batch.")

    daily = _daily_payload(frames)
    if not daily:
        raise ValueError("Tidak ada baris BEI valid yang dapat disimpan ke Supabase.")
    orderbook = _orderbook_payload(daily)
    files = [
        {
            "sha256": str(record["sha256"]).strip().lower(),
            "filename": str(record["filename"]).strip(),
            "size_bytes": int(record.get("size_bytes", 0)),
            "rows_read": int(record.get("rows_read", 0)),
            "rows_saved": int(record.get("rows_saved", 0)),
            "metadata": _json_safe(record.get("metadata", {})),
        }
        for record in file_records
    ]
    batch_key = _batch_key(files)

    remote_hashes = _existing_remote_hashes([item["sha256"] for item in files])
    if len(remote_hashes) == len(files):
        return {
            "saved": True,
            "duplicate": True,
            "upload_run_id": None,
            "ledger_rows": 0,
            "daily_rows": 0,
            "orderbook_rows": 0,
        }
    if remote_hashes:
        raise RuntimeError(
            "Sebagian file batch sudah tercatat di Supabase. "
            "Pisahkan file lama dan file baru sebelum retry agar tidak terjadi partial batch."
        )

    result = _post_rpc(
        {
            "p_run": {
                "source": "app_upload",
                "batch_key": batch_key,
                "note": f"BEI batch: {len(files)} file(s), {len(daily)} unique daily row(s)",
            },
            "p_files": files,
            "p_daily": daily,
            "p_orderbook": orderbook,
        }
    )
    return {
        "saved": True,
        "duplicate": bool(result.get("duplicate")),
        "upload_run_id": result.get("upload_run_id"),
        "ledger_rows": int(result.get("ledger_rows", 0)),
        "daily_rows": int(result.get("daily_rows", 0)),
        "orderbook_rows": int(result.get("orderbook_rows", 0)),
    }


def _fetch_remote_daily() -> pd.DataFrame:
    cfg = config()
    if not cfg["enabled"]:
        raise RuntimeError("Supabase belum dikonfigurasi.")
    rows: list[dict] = []
    offset = 0
    columns = "trade_date,stock_code,company_name,open_price,high_price,low_price,close_price,volume,value,frequency,foreign_sell,foreign_buy," + ",".join(DAILY_ORDERBOOK_COLUMNS) + ",raw_data"
    while True:
        response = requests.get(
            f"{cfg['url']}/rest/v1/stock_daily",
            headers=_headers(str(cfg["key"])),
            params={
                "select": columns,
                "order": "trade_date.asc,stock_code.asc,id.asc",
                "limit": PAGE_SIZE,
                "offset": offset,
            },
            timeout=60,
        )
        if response.status_code >= 400:
            raise RuntimeError(f"Supabase restore {response.status_code}: {response.text[:2000]}")
        page = response.json()
        if not isinstance(page, list):
            raise RuntimeError("Supabase restore mengembalikan format yang tidak dikenal.")
        rows.extend(page)
        if len(page) < PAGE_SIZE:
            break
        offset += PAGE_SIZE
    return pd.DataFrame(rows)


def restore_from_supabase_if_needed() -> dict[str, object]:
    """Rebuild the local SQLite operational cache from Supabase when it is empty."""
    cfg = config()
    if not cfg["enabled"]:
        return {"restored": False, "reason": "supabase_not_configured"}
    init_database()
    with sqlite3.connect(DATABASE_FILE) as conn:
        local_rows = int(conn.execute("SELECT COUNT(*) FROM stock_daily").fetchone()[0])
    if local_rows > 0:
        return {"restored": False, "reason": "local_data_present", "rows": local_rows}

    remote = _fetch_remote_daily()
    if remote.empty:
        return {"restored": False, "reason": "supabase_empty", "rows": 0}
    remote = normalize_dataframe(remote)
    remote = remote.dropna(subset=["trade_date", "stock_code"])
    remote = remote.drop_duplicates(subset=["trade_date", "stock_code"], keep="last")
    if remote.empty:
        return {"restored": False, "reason": "supabase_has_no_valid_daily_rows", "rows": 0}
    saved = save_dataframe(remote)
    return {"restored": True, "reason": "supabase_primary", "rows": int(saved)}
