from __future__ import annotations

import gzip
import os
import shutil
import sqlite3
import tempfile
import time
import uuid
from pathlib import Path
from urllib.parse import quote

import pandas as pd
import requests
import streamlit as st

from .analysis import _technical_readiness, add_indicators
from .database import DAILY_ORDERBOOK_COLUMNS, DATABASE_DIR, DATABASE_FILE, init_database, load_data, load_orderbook

API_BASE = "https://api.github.com"
DEFAULT_REPO = "saputro-es/bei-screener"
DEFAULT_TAG = "bei-data-v1"
ASSET_NAME = "bei_screener.db.gz"
API_VERSION = "2026-03-10"
SUPABASE_RPC = "persist_bei_historical_batch"
SUPABASE_CHUNK_SIZE = 2000
CANONICAL_RUN_ID = str(uuid.uuid5(uuid.NAMESPACE_URL, "bei-screener-canonical-sqlite-history-v1"))


def _secret(name: str, default: str = "") -> str:
    try:
        value = st.secrets.get(name, default)
    except Exception:
        value = os.getenv(name, default)
    return str(value).strip()


def _supabase_config() -> dict[str, object]:
    url = _secret("SUPABASE_URL").rstrip("/")
    key = _secret("SUPABASE_SECRET_KEY") or _secret("SUPABASE_SERVICE_ROLE_KEY")
    return {"enabled": bool(url and key), "url": url, "key": key}


def config() -> dict[str, str | bool]:
    token = _secret("GITHUB_TOKEN")
    repo = _secret("GITHUB_REPO", DEFAULT_REPO)
    tag = _secret("GITHUB_RELEASE_TAG", DEFAULT_TAG)
    supabase = _supabase_config()
    return {"enabled": bool((token and repo) or supabase["enabled"]), "token": token, "repo": repo, "tag": tag,
            "github_enabled": bool(token and repo), "supabase_enabled": bool(supabase["enabled"])}


def _github_headers(token: str, accept: str = "application/vnd.github+json") -> dict[str, str]:
    return {"Accept": accept, "Authorization": f"Bearer {token}", "X-GitHub-Api-Version": API_VERSION, "User-Agent": "bei-screener-persistence"}


def _github_request(method: str, url: str, token: str, **kwargs):
    headers = _github_headers(token)
    headers.update(kwargs.pop("headers", {}))
    response = requests.request(method, url, headers=headers, timeout=120, **kwargs)
    if response.status_code >= 400:
        raise RuntimeError(f"GitHub API {response.status_code}: {response.text[:1000]}")
    return response


def _release(token: str, repo: str, tag: str) -> dict | None:
    url = f"{API_BASE}/repos/{quote(repo, safe='/')}/releases/tags/{quote(tag, safe='')}"
    response = requests.get(url, headers=_github_headers(token), timeout=30)
    if response.status_code == 404:
        return None
    if response.status_code >= 400:
        raise RuntimeError(f"Tidak dapat membaca release GitHub ({response.status_code}).")
    return response.json()


def _ensure_release(token: str, repo: str, tag: str) -> dict:
    existing = _release(token, repo, tag)
    if existing:
        return existing
    url = f"{API_BASE}/repos/{quote(repo, safe='/')}/releases"
    return _github_request("POST", url, token, json={"tag_name": tag, "target_commitish": "main", "name": "BEI Screener Data",
        "body": "Persistent SQLite snapshot for the BEI Screener application.", "draft": False, "prerelease": False, "generate_release_notes": False}).json()


def _assets(release: dict, token: str) -> list[dict]:
    return _github_request("GET", release["assets_url"], token, params={"per_page": 100}).json()


def _database_has_rows() -> bool:
    if not DATABASE_FILE.exists() or DATABASE_FILE.stat().st_size == 0:
        return False
    try:
        with sqlite3.connect(DATABASE_FILE) as conn:
            return bool(conn.execute("SELECT COUNT(*) FROM stock_daily").fetchone()[0])
    except sqlite3.Error:
        return False


def _supabase_headers(key: str) -> dict[str, str]:
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
    return [{str(k): _json_value(v) for k, v in row.items()} for row in frame.to_dict(orient="records")]


def _upload_ledger() -> list[dict]:
    with sqlite3.connect(DATABASE_FILE) as conn:
        rows = conn.execute("SELECT sha256,filename,size_bytes,rows_read,rows_saved FROM upload_ledger ORDER BY id").fetchall()
    return [{"sha256": r[0], "filename": r[1], "size_bytes": r[2], "rows_read": r[3], "rows_saved": r[4], "metadata": {"source": "sqlite_upload_ledger"}} for r in rows]


def _supabase_rpc(payload: dict) -> dict:
    cfg = _supabase_config()
    response = requests.post(f"{cfg['url']}/rest/v1/rpc/{SUPABASE_RPC}", headers=_supabase_headers(str(cfg["key"])), json=payload, timeout=120)
    if response.status_code >= 400:
        raise RuntimeError(f"Supabase RPC {response.status_code}: {response.text[:1500]}")
    data = response.json()
    return data[0] if isinstance(data, list) and data and isinstance(data[0], dict) else (data if isinstance(data, dict) else {})


def sync_sqlite_to_supabase() -> dict[str, object]:
    """Keep SQLite as runtime DB while maintaining an append-only canonical mirror in Supabase."""
    cfg = _supabase_config()
    if not cfg["enabled"]:
        return {"enabled": False, "stock_rows": 0, "orderbook_rows": 0, "technical_rows": 0}
    if not _database_has_rows():
        raise RuntimeError("SQLite tidak berisi data untuk disinkronkan ke Supabase.")

    data = load_data().copy()
    orderbook = load_orderbook()
    indicators = add_indicators(data)
    technical_rows: list[dict] = []
    for code, group in indicators.groupby("stock_code"):
        history_days, technical_status = _technical_readiness(data[data["stock_code"] == code])
        for _, row in group.iterrows():
            technical_rows.append({"trade_date": row.get("trade_date"), "stock_code": code, "sma20": row.get("sma20"), "sma50": row.get("sma50"),
                "sma200": row.get("sma200"), "volume_ma20": row.get("volume_ma20"), "volume_ratio": row.get("volume_ratio"),
                "rsi14": row.get("rsi14"), "atr14": row.get("atr14"), "horizons_available": None, "history_days": history_days,
                "technical_status": technical_status})
    technical = pd.DataFrame(technical_rows)
    ledger = _upload_ledger()
    totals = {"enabled": True, "files": len(ledger), "stock_rows": 0, "orderbook_rows": 0, "technical_rows": 0}
    data["trade_date"] = data["trade_date"].astype(str)
    if not orderbook.empty:
        orderbook = orderbook.copy()
    if not technical.empty:
        technical["trade_date"] = technical["trade_date"].astype(str)

    for start in range(0, len(data), SUPABASE_CHUNK_SIZE):
        chunk = data.iloc[start:start + SUPABASE_CHUNK_SIZE].copy()
        keys = chunk[["trade_date", "stock_code"]]
        if not orderbook.empty:
            ob = orderbook.merge(keys, left_on=["snapshot_date", "stock_code"], right_on=["trade_date", "stock_code"], how="inner")
            ob = ob.drop(columns=["trade_date"], errors="ignore")
        else:
            ob = pd.DataFrame()
        tech = technical.merge(keys, on=["trade_date", "stock_code"], how="inner") if not technical.empty else pd.DataFrame()
        result = _supabase_rpc({"p_upload_run_id": CANONICAL_RUN_ID, "p_upload_ledger": ledger if start == 0 else [],
            "p_stock_daily": _records(chunk), "p_orderbook": _records(ob), "p_technical": _records(tech)})
        totals["stock_rows"] += int(result.get("stock_rows", 0))
        totals["orderbook_rows"] += int(result.get("orderbook_rows", 0))
        totals["technical_rows"] += int(result.get("technical_rows", 0))
    return totals


def status() -> dict[str, object]:
    cfg = config()
    result: dict[str, object] = {"enabled": cfg["enabled"], "configured": bool(cfg["enabled"]), "remote_available": False, "github_available": False, "supabase_available": False}
    if cfg["github_enabled"]:
        try:
            release = _release(str(cfg["token"]), str(cfg["repo"]), str(cfg["tag"]))
            result["github_available"] = bool(release and any(a.get("name") == ASSET_NAME for a in _assets(release, str(cfg["token"]))))
        except Exception as exc:
            result["github_error"] = str(exc)
    if cfg["supabase_enabled"]:
        try:
            scfg = _supabase_config()
            response = requests.get(f"{scfg['url']}/rest/v1/stock_daily?select=id&limit=1", headers=_supabase_headers(str(scfg["key"])), timeout=30)
            if response.status_code >= 400:
                raise RuntimeError(f"HTTP {response.status_code}: {response.text[:500]}")
            result["supabase_available"] = True
        except Exception as exc:
            result["supabase_error"] = str(exc)
    result["remote_available"] = bool(result["github_available"] or result["supabase_available"])
    return result


def restore_if_needed() -> dict[str, object]:
    """Restore SQLite from GitHub snapshot only when the current runtime has no data."""
    cfg = config()
    if _database_has_rows():
        return {"restored": False, "reason": "local_data_present"}
    if not cfg["github_enabled"]:
        return {"restored": False, "reason": "github_restore_not_configured"}
    token, repo, tag = str(cfg["token"]), str(cfg["repo"]), str(cfg["tag"])
    release = _release(token, repo, tag)
    if not release:
        return {"restored": False, "reason": "remote_release_missing"}
    asset = next((a for a in _assets(release, token) if a.get("name") == ASSET_NAME), None)
    if not asset:
        return {"restored": False, "reason": "remote_snapshot_missing"}
    DATABASE_DIR.mkdir(parents=True, exist_ok=True)
    temp_dir = Path(tempfile.mkdtemp(prefix="bei-restore-"))
    archive_path, restored_path = temp_dir / ASSET_NAME, temp_dir / "bei_screener.db"
    try:
        response = _github_request("GET", asset["url"], token, headers={"Accept": "application/octet-stream"}, allow_redirects=True)
        archive_path.write_bytes(response.content)
        with gzip.open(archive_path, "rb") as source, restored_path.open("wb") as target:
            shutil.copyfileobj(source, target)
        if restored_path.stat().st_size == 0:
            raise RuntimeError("Snapshot database kosong.")
        os.replace(restored_path, DATABASE_FILE)
        init_database()
        if not _database_has_rows():
            raise RuntimeError("Snapshot tidak berisi data saham.")
        return {"restored": True, "rows": int(status().get("local_rows", 0)), "asset_size": asset.get("size", 0)}
    finally:
        shutil.rmtree(temp_dir, ignore_errors=True)


def _github_backup() -> dict[str, object]:
    cfg = config()
    if not cfg["github_enabled"]:
        return {"saved": False, "asset_size": 0, "reason": "github_not_configured"}
    token, repo, tag = str(cfg["token"]), str(cfg["repo"]), str(cfg["tag"])
    release = _ensure_release(token, repo, tag)
    old = next((a for a in _assets(release, token) if a.get("name") == ASSET_NAME), None)
    temp_dir = Path(tempfile.mkdtemp(prefix="bei-backup-"))
    archive_path, temp_name = temp_dir / ASSET_NAME, f"{ASSET_NAME}.uploading-{int(time.time())}"
    try:
        with archive_path.open("wb") as raw, gzip.GzipFile(fileobj=raw, mode="wb", compresslevel=6) as compressed:
            with DATABASE_FILE.open("rb") as source:
                shutil.copyfileobj(source, compressed, length=1024 * 1024)
        upload_url = release["upload_url"].split("{", 1)[0]
        new_asset = _github_request("POST", upload_url, token, headers={"Content-Type": "application/gzip"}, params={"name": temp_name}, data=archive_path.read_bytes()).json()
        if old:
            _github_request("DELETE", old["url"], token)
        renamed = _github_request("PATCH", new_asset["url"], token, json={"name": ASSET_NAME, "label": "Persistent BEI Screener SQLite snapshot"}).json()
        return {"saved": True, "asset_size": int(renamed.get("size", archive_path.stat().st_size))}
    finally:
        shutil.rmtree(temp_dir, ignore_errors=True)


def backup_database() -> dict[str, object]:
    """Durable backup: Supabase historical mirror first, GitHub snapshot second."""
    cfg = config()
    if not cfg["enabled"]:
        raise RuntimeError("Persistent storage belum dikonfigurasi.")
    if not _database_has_rows():
        raise RuntimeError("Tidak ada data di SQLite yang dapat dicadangkan.")
    result: dict[str, object] = {"saved": False, "asset_size": 0, "supabase": None, "github": None}
    if cfg["supabase_enabled"]:
        result["supabase"] = sync_sqlite_to_supabase()
    if cfg["github_enabled"]:
        result["github"] = _github_backup()
        result["asset_size"] = int(result["github"].get("asset_size", 0))
    result["saved"] = True
    return result
