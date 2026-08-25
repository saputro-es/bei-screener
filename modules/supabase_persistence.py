from __future__ import annotations

import hashlib
import json
import math
import os
import sqlite3
from collections.abc import Iterable

import pandas as pd
import requests
import streamlit as st
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

from .database import DAILY_ORDERBOOK_COLUMNS, DATABASE_FILE, init_database, save_dataframe, normalize_dataframe

DEFAULT_SUPABASE_URL = "https://kgaxmrzyuzajeeuaatcb.supabase.co"
RPC_PATH = "/rest/v1/rpc/persist_upload_batch"
REPAIR_RPC_PATH = "/rest/v1/rpc/repair_historical_missing_fields"
TIMEOUT_SECONDS = 45
PAGE_SIZE = 250
MAX_RESTORE_PAGES = 10000
RETRY_TOTAL = 5


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
    return {"apikey": key, "Authorization": f"Bearer {key}", "Content-Type": "application/json", "Accept": "application/json", "User-Agent": "bei-screener-supabase-persistence/2"}


def _session() -> requests.Session:
    session = requests.Session()
    retry = Retry(total=RETRY_TOTAL, connect=RETRY_TOTAL, read=RETRY_TOTAL, status=RETRY_TOTAL, backoff_factor=1.5, status_forcelist=(429, 500, 502, 503, 504), allowed_methods=frozenset({"GET", "POST", "PATCH", "DELETE"}), respect_retry_after_header=True, raise_on_status=False)
    adapter = HTTPAdapter(max_retries=retry, pool_connections=4, pool_maxsize=8, pool_block=True)
    session.mount("https://", adapter)
    session.mount("http://", adapter)
    return session


def _request(method: str, url: str, *, key: str, timeout: int = TIMEOUT_SECONDS, **kwargs):
    headers = _headers(key)
    headers.update(kwargs.pop("headers", {}))
    try:
        with _session() as session:
            response = session.request(method, url, headers=headers, timeout=timeout, **kwargs)
    except requests.RequestException as exc:
        raise RuntimeError(f"Supabase network error setelah retry: {exc}") from exc
    if response.status_code >= 400:
        raise RuntimeError(f"Supabase HTTP {response.status_code}: {response.text[:2000]}")
    return response


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
    if value is None:
        return None
    if isinstance(value, pd.Timestamp):
        return value.isoformat()
    if isinstance(value, dict):
        return {str(key): _json_safe(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_safe(item) for item in value]
    if hasattr(value, "item"):
        try:
            return _json_safe(value.item())
        except Exception:
            pass
    if isinstance(value, float):
        return value if math.isfinite(value) else None
    try:
        missing = pd.isna(value)
        if isinstance(missing, bool) and missing:
            return None
    except (TypeError, ValueError):
        pass
    return json.loads(json.dumps(value, ensure_ascii=False, allow_nan=False, default=_json_default))


def _row_to_json(row: pd.Series) -> dict:
    return {str(key): _json_safe(value) for key, value in row.items()}


def _post_rpc(payload: dict, path: str = RPC_PATH) -> dict:
    cfg = config()
    if not cfg["enabled"]:
        raise RuntimeError("Supabase historical persistence belum dikonfigurasi. Tambahkan SUPABASE_SECRET_KEY ke Streamlit Secrets.")
    response = _request("POST", f"{cfg['url']}{path}", key=str(cfg["key"]), json=payload)
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
    cfg = config()
    values = sorted({str(value).lower() for value in hashes if value})
    if not cfg["enabled"] or not values:
        return set()
    response = _request("GET", f"{cfg['url']}/rest/v1/upload_ledger", key=str(cfg["key"]), params={"select": "sha256", "sha256": f"in.({','.join(values)})"}, timeout=30)
    body = response.json()
    return {str(item["sha256"]).lower() for item in body if isinstance(item, dict) and item.get("sha256")}


def status() -> dict[str, object]:
    cfg = config()
    result: dict[str, object] = {"enabled": bool(cfg["enabled"]), "configured": bool(cfg["enabled"]), "url": cfg["url"], "reachable": False, "historical_rows": 0}
    if not cfg["enabled"]:
        result["reason"] = "secret_missing"
        return result
    try:
        response = _request("GET", f"{cfg['url']}/rest/v1/stock_daily", key=str(cfg["key"]), headers={"Prefer": "count=exact"}, params={"select": "id", "limit": 1}, timeout=20)
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
    columns = ["trade_date", "stock_code", "company_name", "open_price", "high_price", "low_price", "close_price", "volume", "value", "frequency", "foreign_sell", "foreign_buy", *DAILY_ORDERBOOK_COLUMNS]
    rows: list[dict] = []
    for index in data.index:
        row = data.loc[index]
        item = _row_to_json(row[columns])
        item["raw_data"] = _row_to_json(row)
        rows.append(item)
    return rows


def _orderbook_payload(daily_rows: list[dict]) -> list[dict]:
    rows: list[dict] = []
    for daily in daily_rows:
        levels = {column: daily.get(column) for column in DAILY_ORDERBOOK_COLUMNS}
        if not any(value is not None for value in levels.values()):
            continue
        item = {"snapshot_date": daily.get("trade_date"), "snapshot_time": "00:00:00", "stock_code": daily.get("stock_code"), **levels}
        item["raw_data"] = _json_safe(item)
        rows.append(item)
    return rows


def persist_upload_batch(frames: list[pd.DataFrame], file_records: list[dict]) -> dict[str, object]:
    if not frames or not file_records:
        raise ValueError("Upload batch kosong.")
    if len(file_records) > 20:
        raise ValueError("Maksimal 20 file per batch.")
    daily = _daily_payload(frames)
    if not daily:
        raise ValueError("Tidak ada baris BEI valid yang dapat disimpan ke Supabase.")
    orderbook = _orderbook_payload(daily)
    files = [{"sha256": str(record["sha256"]).strip().lower(), "filename": str(record["filename"]).strip(), "size_bytes": int(record.get("size_bytes", 0)), "rows_read": int(record.get("rows_read", 0)), "rows_saved": int(record.get("rows_saved", 0)), "metadata": _json_safe(record.get("metadata", {}))} for record in file_records]
    batch_key = _batch_key(files)
    remote_hashes = _existing_remote_hashes([item["sha256"] for item in files])
    if len(remote_hashes) == len(files):
        repair = _post_rpc({"p_daily": daily, "p_orderbook": orderbook}, path=REPAIR_RPC_PATH)
        return {"saved": True, "duplicate": True, "repaired": True, "repair_daily_rows": int(repair.get("daily_updated", 0)), "repair_orderbook_rows": int(repair.get("orderbook_updated", 0)), "upload_run_id": None, "ledger_rows": 0, "daily_rows": 0, "orderbook_rows": 0}
    if remote_hashes:
        raise RuntimeError("Sebagian file batch sudah tercatat di Supabase. Pisahkan file lama dan file baru sebelum retry agar tidak terjadi partial batch.")
    result = _post_rpc({"p_run": {"source": "app_upload", "batch_key": batch_key, "note": f"BEI batch: {len(files)} file(s), {len(daily)} unique daily row(s)"}, "p_files": files, "p_daily": daily, "p_orderbook": orderbook})
    return {"saved": True, "duplicate": bool(result.get("duplicate")), "upload_run_id": result.get("upload_run_id"), "ledger_rows": int(result.get("ledger_rows", 0)), "daily_rows": int(result.get("daily_rows", 0)), "orderbook_rows": int(result.get("orderbook_rows", 0))}


def _fetch_remote_daily() -> pd.DataFrame:
    cfg = config()
    if not cfg["enabled"]:
        raise RuntimeError("Supabase belum dikonfigurasi.")
    rows: list[dict] = []
    offset = 0
    columns = "trade_date,stock_code,company_name,open_price,high_price,low_price,close_price,volume,value,frequency,foreign_sell,foreign_buy," + ",".join(DAILY_ORDERBOOK_COLUMNS) + ",raw_data"
    for _ in range(1, MAX_RESTORE_PAGES + 1):
        response = _request("GET", f"{cfg['url']}/rest/v1/stock_daily", key=str(cfg["key"]), params={"select": columns, "order": "trade_date.asc,stock_code.asc", "limit": PAGE_SIZE, "offset": offset}, timeout=TIMEOUT_SECONDS)
        page = response.json()
        if not isinstance(page, list):
            raise RuntimeError("Supabase restore mengembalikan format yang tidak dikenal.")
        rows.extend(item for item in page if isinstance(item, dict))
        if len(page) < PAGE_SIZE:
            return pd.DataFrame(rows)
        offset += PAGE_SIZE
    raise RuntimeError("Restore Supabase dihentikan karena melewati batas halaman aman.")


def restore_from_supabase_if_needed() -> dict[str, object]:
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
