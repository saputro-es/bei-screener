from __future__ import annotations

import json
import sqlite3
import time

import pandas as pd
import requests

from .database import DAILY_ORDERBOOK_COLUMNS, DATABASE_FILE, ORDERBOOK_COLUMNS, init_database
from .supabase_persistence import _headers, config

PAGE_SIZE = 1000
TIMEOUT_SECONDS = 60
SQLITE_BUSY_TIMEOUT_MS = 120_000
SQLITE_RETRIES = 4


def _connect_local() -> sqlite3.Connection:
    """Open the local read model with a long busy timeout.

    Streamlit can rerun the script while another session is finishing a local
    reconciliation. The old code used sqlite's short default timeout during
    init/signature checks, turning a transient lock into a fatal application
    error. All canonical-sync connections now wait for the writer to finish.
    """
    conn = sqlite3.connect(DATABASE_FILE, timeout=SQLITE_BUSY_TIMEOUT_MS / 1000)
    conn.execute(f"PRAGMA busy_timeout={SQLITE_BUSY_TIMEOUT_MS}")
    return conn


def _get_page(cfg: dict[str, str | bool], table: str, offset: int) -> list[dict]:
    response = requests.get(
        f"{cfg['url']}/rest/v1/{table}",
        headers={**_headers(str(cfg['key'])), "Prefer": "count=exact"},
        params={"select": "*", "order": "id.asc", "limit": PAGE_SIZE, "offset": offset},
        timeout=TIMEOUT_SECONDS,
    )
    if response.status_code >= 400:
        raise RuntimeError(f"Supabase {table} {response.status_code}: {response.text[:1000]}")
    body = response.json()
    if not isinstance(body, list):
        raise RuntimeError(f"Supabase {table} mengembalikan payload yang tidak valid.")
    return [item for item in body if isinstance(item, dict)]


def _fetch_all(cfg: dict[str, str | bool], table: str) -> list[dict]:
    rows: list[dict] = []
    offset = 0
    while True:
        page = _get_page(cfg, table, offset)
        rows.extend(page)
        if len(page) < PAGE_SIZE:
            return rows
        offset += PAGE_SIZE


def _local_signature() -> tuple[int, str | None]:
    # Signature is read-only. Do not run schema migrations here because every
    # app session would become a writer before canonical reconciliation starts.
    if not DATABASE_FILE.exists():
        init_database()
    for attempt in range(SQLITE_RETRIES):
        try:
            with _connect_local() as conn:
                count = int(conn.execute("SELECT COUNT(*) FROM stock_daily").fetchone()[0])
                latest = conn.execute("SELECT MAX(trade_date) FROM stock_daily").fetchone()[0]
            return count, latest
        except sqlite3.OperationalError as exc:
            if "locked" not in str(exc).lower() or attempt == SQLITE_RETRIES - 1:
                raise
            time.sleep(0.5 * (attempt + 1))
    raise RuntimeError("Local SQLite signature could not be read.")


def _remote_signature(cfg: dict[str, str | bool]) -> tuple[int, str | None]:
    response = requests.get(
        f"{cfg['url']}/rest/v1/stock_daily",
        headers={**_headers(str(cfg['key'])), "Prefer": "count=exact"},
        params={"select": "id,trade_date", "order": "trade_date.desc", "limit": 1},
        timeout=TIMEOUT_SECONDS,
    )
    if response.status_code >= 400:
        raise RuntimeError(f"Supabase stock_daily {response.status_code}: {response.text[:1000]}")
    content_range = response.headers.get("Content-Range", "")
    total = None
    if "/" in content_range:
        try:
            total = int(content_range.rsplit("/", 1)[1])
        except ValueError:
            total = None
    body = response.json()
    latest = body[0].get("trade_date") if body else None
    if total is None:
        total = len(body)
    return int(total), str(latest) if latest else None


def _replace_local_once(cfg: dict[str, str | bool], remote_count: int, remote_latest: str | None) -> dict[str, object]:
    daily_rows = _fetch_all(cfg, "stock_daily")
    orderbook_rows = _fetch_all(cfg, "orderbook_snapshot")
    if len(daily_rows) != remote_count:
        raise RuntimeError(
            f"Verifikasi sync gagal: remote signature {remote_count} row, tetapi fetch mendapatkan {len(daily_rows)} row."
        )

    init_database()
    daily_columns = [
        "trade_date", "stock_code", "company_name", "open_price", "high_price", "low_price",
        "close_price", "volume", "value", "frequency", "foreign_sell", "foreign_buy",
        *DAILY_ORDERBOOK_COLUMNS,
    ]
    daily_insert_columns = daily_columns + ["raw_data"]
    orderbook_insert_columns = ORDERBOOK_COLUMNS + ["raw_data"]

    with _connect_local() as conn:
        conn.execute("BEGIN IMMEDIATE")
        conn.execute("DELETE FROM stock_daily")
        conn.execute("DELETE FROM orderbook_snapshot")

        for row in daily_rows:
            values = [row.get(column) for column in daily_columns]
            raw = row.get("raw_data")
            if raw is None:
                raw = json.dumps(row, ensure_ascii=False, default=str)
            elif isinstance(raw, (dict, list)):
                raw = json.dumps(raw, ensure_ascii=False, default=str)
            conn.execute(
                f"INSERT INTO stock_daily ({', '.join(daily_insert_columns)}) VALUES ({','.join('?' for _ in daily_insert_columns)})",
                values + [raw],
            )

        for row in orderbook_rows:
            values = [row.get(column) for column in ORDERBOOK_COLUMNS]
            raw = row.get("raw_data")
            if raw is None:
                raw = json.dumps(row, ensure_ascii=False, default=str)
            elif isinstance(raw, (dict, list)):
                raw = json.dumps(raw, ensure_ascii=False, default=str)
            conn.execute(
                f"INSERT INTO orderbook_snapshot ({', '.join(orderbook_insert_columns)}) VALUES ({','.join('?' for _ in orderbook_insert_columns)})",
                values + [raw],
            )
        conn.commit()

    return {
        "synced": True,
        "reason": "remote_canonical_data",
        "rows": len(daily_rows),
        "orderbook_rows": len(orderbook_rows),
        "latest_date": remote_latest,
    }


def _replace_local_with_remote(cfg: dict[str, str | bool], remote_count: int, remote_latest: str | None) -> dict[str, object]:
    """Replace the local read model, retrying only transient SQLite locks."""
    for attempt in range(SQLITE_RETRIES):
        try:
            return _replace_local_once(cfg, remote_count, remote_latest)
        except sqlite3.OperationalError as exc:
            if "locked" not in str(exc).lower() or attempt == SQLITE_RETRIES - 1:
                raise
            time.sleep(0.5 * (attempt + 1))
    raise RuntimeError("Local SQLite reconciliation could not complete.")


def sync_local_from_supabase(force: bool = False) -> dict[str, object]:
    """Reconcile SQLite with canonical Supabase data.

    A forced sync is intended for a fresh app session so a stale local database cannot
    masquerade as current data merely because its row count and latest date happen to
    match. The remote dataset is fetched and verified before replacing the local read model.
    """
    cfg = config()
    if not cfg["enabled"]:
        return {"synced": False, "reason": "supabase_disabled"}

    local_count, local_latest = _local_signature()
    remote_count, remote_latest = _remote_signature(cfg)
    if not force and local_count == remote_count and local_latest == remote_latest:
        return {"synced": False, "reason": "already_current", "rows": local_count}

    return _replace_local_with_remote(cfg, remote_count, remote_latest)
