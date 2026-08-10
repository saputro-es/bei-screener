from __future__ import annotations

import sqlite3

import pandas as pd
import requests

from .database import DAILY_ORDERBOOK_COLUMNS, DATABASE_FILE, ORDERBOOK_COLUMNS, init_database
from .supabase_persistence import _headers, config

PAGE_SIZE = 1000
TIMEOUT_SECONDS = 60


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
    init_database()
    with sqlite3.connect(DATABASE_FILE) as conn:
        count = int(conn.execute("SELECT COUNT(*) FROM stock_daily").fetchone()[0])
        latest = conn.execute("SELECT MAX(trade_date) FROM stock_daily").fetchone()[0]
    return count, latest


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


def sync_local_from_supabase() -> dict[str, object]:
    """Reconcile the local SQLite read model with canonical Supabase history.

    Uploads are committed to Supabase before local completion is reported, so Supabase
    is the canonical source. If the local read model has a different row count or
    latest trade date (for example, an old restored backup containing stale dates),
    replace the local read model with the canonical remote rows. If Supabase is
    unreachable, leave local data untouched and let the app continue in offline mode.
    """
    cfg = config()
    if not cfg["enabled"]:
        return {"synced": False, "reason": "supabase_disabled"}

    local_count, local_latest = _local_signature()
    remote_count, remote_latest = _remote_signature(cfg)
    if local_count == remote_count and local_latest == remote_latest:
        return {"synced": False, "reason": "already_current", "rows": local_count}

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

    with sqlite3.connect(DATABASE_FILE, timeout=60) as conn:
        conn.execute("PRAGMA busy_timeout=60000")
        conn.execute("BEGIN")
        conn.execute("DELETE FROM stock_daily")
        conn.execute("DELETE FROM orderbook_snapshot")

        for row in daily_rows:
            values = [row.get(column) for column in daily_columns]
            raw = row.get("raw_data")
            if raw is None:
                raw = row
            conn.execute(
                f"INSERT INTO stock_daily ({', '.join(daily_insert_columns)}) VALUES ({','.join('?' for _ in daily_insert_columns)})",
                values + [raw],
            )

        for row in orderbook_rows:
            values = [row.get(column) for column in ORDERBOOK_COLUMNS]
            raw = row.get("raw_data")
            if raw is None:
                raw = row
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
