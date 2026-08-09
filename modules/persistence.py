from __future__ import annotations

import gzip
import os
import shutil
import sqlite3
import tempfile
import time
from pathlib import Path
from urllib.parse import quote

import requests
import streamlit as st

from .database import DATABASE_DIR, DATABASE_FILE, init_database
from .supabase_persistence import (
    config as supabase_config,
    restore_from_supabase_if_needed,
    status as supabase_status,
)

API_BASE = "https://api.github.com"
DEFAULT_REPO = "saputro-es/bei-screener"
DEFAULT_TAG = "bei-data-v1"
ASSET_NAME = "bei_screener.db.gz"
API_VERSION = "2026-03-10"


def _secret(name: str, default: str = "") -> str:
    try:
        value = st.secrets.get(name, default)
    except Exception:
        value = os.getenv(name, default)
    return str(value).strip()


def config() -> dict[str, str | bool]:
    token = _secret("GITHUB_TOKEN")
    repo = _secret("GITHUB_REPO", DEFAULT_REPO)
    tag = _secret("GITHUB_RELEASE_TAG", DEFAULT_TAG)
    supabase_enabled = bool(supabase_config()["enabled"])
    return {
        "enabled": bool((token and repo) or supabase_enabled),
        "github_enabled": bool(token and repo),
        "supabase_enabled": supabase_enabled,
        "token": token,
        "repo": repo,
        "tag": tag,
    }


def _headers(token: str, accept: str = "application/vnd.github+json") -> dict[str, str]:
    return {
        "Accept": accept,
        "Authorization": f"Bearer {token}",
        "X-GitHub-Api-Version": API_VERSION,
        "User-Agent": "bei-screener-persistence",
    }


def _request(method: str, url: str, token: str, **kwargs):
    headers = kwargs.pop("headers", {})
    merged = _headers(token)
    merged.update(headers)
    response = requests.request(method, url, headers=merged, timeout=120, **kwargs)
    if response.status_code >= 400:
        raise RuntimeError(f"GitHub API {response.status_code}: {response.text[:1000]}")
    return response


def _release(token: str, repo: str, tag: str) -> dict | None:
    owner_repo = quote(repo, safe="/")
    url = f"{API_BASE}/repos/{owner_repo}/releases/tags/{quote(tag, safe='')}"
    response = requests.get(url, headers=_headers(token), timeout=30)
    if response.status_code == 404:
        return None
    if response.status_code >= 400:
        raise RuntimeError(f"Tidak dapat membaca release GitHub ({response.status_code}).")
    return response.json()


def _ensure_release(token: str, repo: str, tag: str) -> dict:
    existing = _release(token, repo, tag)
    if existing:
        return existing
    owner_repo = quote(repo, safe="/")
    url = f"{API_BASE}/repos/{owner_repo}/releases"
    payload = {
        "tag_name": tag,
        "target_commitish": "main",
        "name": "BEI Screener Data",
        "body": "Secondary SQLite recovery snapshot for the BEI Screener application. Supabase is the primary durable store.",
        "draft": False,
        "prerelease": False,
        "generate_release_notes": False,
    }
    return _request("POST", url, token, json=payload).json()


def _assets(release: dict, token: str) -> list[dict]:
    return _request("GET", release["assets_url"], token, params={"per_page": 100}).json()


def _database_has_rows() -> bool:
    if not DATABASE_FILE.exists() or DATABASE_FILE.stat().st_size == 0:
        return False
    try:
        with sqlite3.connect(DATABASE_FILE) as conn:
            row = conn.execute("SELECT COUNT(*) FROM stock_daily").fetchone()
        return bool(row and row[0] > 0)
    except sqlite3.Error:
        return False


def status() -> dict[str, object]:
    cfg = config()
    result: dict[str, object] = {
        "enabled": cfg["enabled"],
        "configured": bool(cfg["enabled"]),
        "github_enabled": cfg["github_enabled"],
        "supabase_enabled": cfg["supabase_enabled"],
        "repo": cfg["repo"],
        "tag": cfg["tag"],
        "asset": ASSET_NAME,
        "local_rows": 0,
        "remote_available": False,
        "supabase_reachable": False,
    }
    try:
        if DATABASE_FILE.exists():
            with sqlite3.connect(DATABASE_FILE) as conn:
                result["local_rows"] = int(conn.execute("SELECT COUNT(*) FROM stock_daily").fetchone()[0])
    except sqlite3.Error:
        pass

    if cfg["supabase_enabled"]:
        sb = supabase_status()
        result["supabase_reachable"] = bool(sb.get("reachable"))
        result["supabase_historical_rows"] = int(sb.get("historical_rows", 0))
        if sb.get("reachable"):
            result["remote_available"] = True

    if cfg["github_enabled"]:
        try:
            release = _release(str(cfg["token"]), str(cfg["repo"]), str(cfg["tag"]))
            if release:
                result["github_remote_available"] = any(
                    asset.get("name") == ASSET_NAME for asset in _assets(release, str(cfg["token"]))
                )
                result["remote_available"] = bool(result["remote_available"] or result["github_remote_available"])
        except Exception as exc:
            result["github_error"] = str(exc)
    return result


def restore_if_needed() -> dict[str, object]:
    """Restore the operational SQLite cache from the primary store first.

    Supabase is authoritative. GitHub is only a secondary recovery snapshot.
    If Supabase is configured but empty, GitHub may still be used as a legacy
    recovery source so an older deployment is not stranded.
    """
    if _database_has_rows():
        return {"restored": False, "reason": "local_data_present"}

    cfg = config()
    if cfg["supabase_enabled"]:
        try:
            supabase_result = restore_from_supabase_if_needed()
            if supabase_result.get("restored") or supabase_result.get("rows", 0):
                return supabase_result
            if supabase_result.get("reason") not in {"supabase_empty", "supabase_has_no_valid_daily_rows"}:
                return supabase_result
        except Exception as exc:
            # Do not silently accept a broken primary store when there is no
            # secondary recovery path. With GitHub configured we can fall back.
            if not cfg["github_enabled"]:
                return {"restored": False, "reason": "supabase_restore_failed", "error": str(exc)}

    if not cfg["github_enabled"]:
        if cfg["supabase_enabled"]:
            return {"restored": False, "reason": "supabase_empty"}
        return {"restored": False, "reason": "persistence_not_configured"}

    token = str(cfg["token"])
    repo = str(cfg["repo"])
    tag = str(cfg["tag"])
    release = _release(token, repo, tag)
    if not release:
        return {"restored": False, "reason": "remote_release_missing"}

    assets = _assets(release, token)
    asset = next((item for item in assets if item.get("name") == ASSET_NAME), None)
    if not asset:
        return {"restored": False, "reason": "remote_snapshot_missing"}

    DATABASE_DIR.mkdir(parents=True, exist_ok=True)
    temp_dir = Path(tempfile.mkdtemp(prefix="bei-restore-"))
    archive_path = temp_dir / ASSET_NAME
    restored_path = temp_dir / "bei_screener.db"
    try:
        response = _request("GET", asset["url"], token, headers={"Accept": "application/octet-stream"}, allow_redirects=True)
        archive_path.write_bytes(response.content)
        with gzip.open(archive_path, "rb") as source, restored_path.open("wb") as target:
            shutil.copyfileobj(source, target)
        if restored_path.stat().st_size == 0:
            raise RuntimeError("Snapshot database kosong.")
        backup_path = DATABASE_FILE.with_suffix(".db.before_restore")
        if DATABASE_FILE.exists():
            shutil.copy2(DATABASE_FILE, backup_path)
        os.replace(restored_path, DATABASE_FILE)
        init_database()
        if not _database_has_rows():
            raise RuntimeError("Snapshot berhasil diunduh tetapi tidak berisi data saham.")
        return {"restored": True, "rows": status()["local_rows"], "asset_size": asset.get("size", 0), "backend": "github"}
    finally:
        shutil.rmtree(temp_dir, ignore_errors=True)


def backup_database() -> dict[str, object]:
    """Create the optional GitHub SQLite backup after the durable Supabase write."""
    cfg = config()
    if not _database_has_rows():
        raise RuntimeError("Tidak ada data di SQLite yang dapat dicadangkan.")
    if not cfg["github_enabled"]:
        if cfg["supabase_enabled"]:
            return {"saved": True, "asset_size": 0, "rows": status()["local_rows"], "backend": "supabase"}
        raise RuntimeError(
            "Persistent storage belum dikonfigurasi. Tambahkan SUPABASE_SECRET_KEY "
            "atau GITHUB_TOKEN ke Streamlit Secrets."
        )

    init_database()
    token = str(cfg["token"])
    repo = str(cfg["repo"])
    tag = str(cfg["tag"])
    release = _ensure_release(token, repo, tag)
    assets = _assets(release, token)
    old_asset = next((item for item in assets if item.get("name") == ASSET_NAME), None)

    temp_dir = Path(tempfile.mkdtemp(prefix="bei-backup-"))
    archive_path = temp_dir / ASSET_NAME
    temp_name = f"{ASSET_NAME}.uploading-{int(time.time())}"
    try:
        with archive_path.open("wb") as raw, gzip.GzipFile(fileobj=raw, mode="wb", compresslevel=6) as compressed:
            with DATABASE_FILE.open("rb") as source:
                shutil.copyfileobj(source, compressed, length=1024 * 1024)
        upload_url = release["upload_url"].split("{", 1)[0]
        new_asset = _request(
            "POST", upload_url, token,
            headers={"Content-Type": "application/gzip"},
            params={"name": temp_name},
            data=archive_path.read_bytes(),
        ).json()
        if old_asset:
            _request("DELETE", old_asset["url"], token)
        renamed = _request(
            "PATCH", new_asset["url"], token,
            json={"name": ASSET_NAME, "label": "Secondary SQLite recovery snapshot"},
        ).json()
        return {
            "saved": True,
            "asset_size": int(renamed.get("size", archive_path.stat().st_size)),
            "rows": status()["local_rows"],
            "release_tag": tag,
            "backend": "github",
        }
    except Exception:
        try:
            release_now = _release(token, repo, tag)
            if release_now:
                for asset in _assets(release_now, token):
                    if asset.get("name") == temp_name:
                        _request("DELETE", asset["url"], token)
        except Exception:
            pass
        raise
    finally:
        shutil.rmtree(temp_dir, ignore_errors=True)
