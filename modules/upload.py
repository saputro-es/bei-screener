from __future__ import annotations

import hashlib
import json
import re
import sqlite3
from collections.abc import Iterable

import pandas as pd

from .database import (
    DAILY_ORDERBOOK_COLUMNS,
    DATABASE_FILE,
    ORDERBOOK_COLUMNS,
    init_database,
    normalize_dataframe,
)
from .supabase_persistence import config as supabase_config, persist_upload_batch

MAX_FILES_PER_BATCH = 20
_FILENAME_DATE_RE = re.compile(r"(?<!\d)(20\d{6})(?!\d)")

DAILY_COLUMNS = [
    "trade_date", "stock_code", "company_name", "open_price", "high_price", "low_price", "close_price", "volume", "value", "frequency", "foreign_sell", "foreign_buy",
] + DAILY_ORDERBOOK_COLUMNS


def sha256_bytes(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def _expected_trade_date(filename: str) -> str | None:
    match = _FILENAME_DATE_RE.search(str(filename))
    if not match:
        return None
    return pd.to_datetime(match.group(1), format="%Y%m%d", errors="raise").strftime("%Y-%m-%d")


def _prepare_upload_frame(frame: pd.DataFrame, filename: str) -> pd.DataFrame:
    """Normalize one file and enforce its YYYYMMDD filename date."""
    data = normalize_dataframe(frame)
    expected = _expected_trade_date(filename)
    if expected is None:
        return data

    actual_dates = sorted({str(value) for value in data["trade_date"].dropna().unique()})
    if len(actual_dates) != 1:
        raise ValueError(
            f"{filename}: tanggal perdagangan harus tepat satu tanggal; ditemukan {actual_dates or 'kosong'}."
        )

    actual = actual_dates[0]
    if actual == expected:
        return data

    expected_ts = pd.Timestamp(expected)
    actual_ts = pd.Timestamp(actual)
    try:
        swapped = expected_ts.replace(day=expected_ts.month, month=expected_ts.day).strftime("%Y-%m-%d")
    except ValueError:
        swapped = None

    if swapped == actual:
        data = data.copy()
        data["trade_date"] = expected
        return data

    raise ValueError(
        f"{filename}: tanggal file {expected} tidak cocok dengan data Excel {actual}. "
        "Upload dihentikan agar histori tidak tercatat pada tanggal yang salah."
    )


def _supabase_safe_frames(frames: list[pd.DataFrame]) -> list[pd.DataFrame]:
    """Keep validated dates as datetime objects before the second persistence normalization.

    The Supabase payload builder normalizes frames defensively. Passing an ISO string
    back through the legacy day-first parser can re-introduce the exact day/month
    inversion that upload validation just corrected. A real datetime value is
    unambiguous and survives that second normalization unchanged.
    """
    safe: list[pd.DataFrame] = []
    for frame in frames:
        copy = frame.copy()
        if "trade_date" in copy.columns:
            copy["trade_date"] = pd.to_datetime(copy["trade_date"], format="%Y-%m-%d", errors="raise")
        safe.append(copy)
    return safe


def _ensure_upload_ledger(conn: sqlite3.Connection) -> None:
    conn.execute(
        """CREATE TABLE IF NOT EXISTS upload_ledger (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            sha256 TEXT NOT NULL UNIQUE,
            filename TEXT NOT NULL,
            size_bytes INTEGER NOT NULL,
            rows_read INTEGER NOT NULL DEFAULT 0,
            rows_saved INTEGER NOT NULL DEFAULT 0,
            uploaded_at TEXT DEFAULT CURRENT_TIMESTAMP
        )"""
    )
    conn.execute("CREATE INDEX IF NOT EXISTS idx_upload_filename ON upload_ledger(filename)")


def existing_hashes(hashes: Iterable[str]) -> set[str]:
    values = [str(value) for value in hashes if value]
    if not values:
        return set()
    init_database()
    placeholders = ",".join("?" for _ in values)
    with sqlite3.connect(DATABASE_FILE) as conn:
        _ensure_upload_ledger(conn)
        rows = conn.execute(
            f"SELECT sha256 FROM upload_ledger WHERE sha256 IN ({placeholders})", values
        ).fetchall()
    return {row[0] for row in rows}


def save_upload_batch(
    frames: list[pd.DataFrame],
    file_records: list[dict],
) -> dict[str, int | bool | str | None]:
    """Persist a whole upload batch with deterministic trade-date validation."""
    if not frames:
        return {"rows_read": 0, "rows_saved": 0, "orderbook_rows": 0, "files_saved": 0, "supabase_saved": False}
    if len(frames) > MAX_FILES_PER_BATCH:
        raise ValueError(f"Maksimal {MAX_FILES_PER_BATCH} file per batch.")
    if len(frames) != len(file_records):
        raise ValueError("Jumlah frame dan metadata file tidak sama.")

    prepared_frames = [
        _prepare_upload_frame(frame, str(record.get("filename", "")))
        for frame, record in zip(frames, file_records)
    ]
    data = pd.concat(prepared_frames, ignore_index=True)
    data = data.dropna(subset=["trade_date", "stock_code"]).copy()
    data = data.drop_duplicates(subset=["trade_date", "stock_code"], keep="last")
    if data.empty:
        raise ValueError("File tidak memiliki baris valid dengan tanggal dan kode saham.")

    supabase_result: dict[str, object] = {
        "saved": False,
        "duplicate": False,
        "upload_run_id": None,
    }
    if supabase_config()["enabled"]:
        supabase_result = persist_upload_batch(_supabase_safe_frames(prepared_frames), file_records)

    init_database()
    data = data.copy()
    for column in DAILY_COLUMNS:
        if column not in data.columns:
            data[column] = None

    raw_payloads = [json.dumps(row.to_dict(), default=str, ensure_ascii=False) for _, row in data.iterrows()]
    rows = []
    for values, raw_data in zip(data[DAILY_COLUMNS].itertuples(index=False, name=None), raw_payloads):
        rows.append(tuple(None if pd.isna(value) else value for value in values) + (raw_data,))

    insert_sql = (
        f"INSERT INTO stock_daily ({', '.join(DAILY_COLUMNS)}, raw_data) "
        f"VALUES ({','.join('?' for _ in range(len(DAILY_COLUMNS) + 1))}) "
        "ON CONFLICT(trade_date, stock_code) DO UPDATE SET "
        + ", ".join(
            f"{column}=COALESCE(excluded.{column}, stock_daily.{column})"
            for column in DAILY_COLUMNS[2:]
        )
        + ", raw_data=COALESCE(excluded.raw_data, stock_daily.raw_data)"
    )

    embedded = data[["trade_date", "stock_code"] + DAILY_ORDERBOOK_COLUMNS].copy()
    embedded = embedded.rename(columns={"trade_date": "snapshot_date"})
    embedded["snapshot_time"] = "00:00:00"
    embedded = embedded[["snapshot_date", "snapshot_time", "stock_code"] + DAILY_ORDERBOOK_COLUMNS]
    embedded = embedded[embedded[DAILY_ORDERBOOK_COLUMNS].notna().any(axis=1)].copy()
    embedded = embedded.drop_duplicates(subset=["snapshot_date", "snapshot_time", "stock_code"], keep="last")

    orderbook_rows = []
    if not embedded.empty:
        for values in embedded[ORDERBOOK_COLUMNS].itertuples(index=False, name=None):
            clean = tuple(None if pd.isna(value) else value for value in values)
            raw_data = json.dumps(dict(zip(ORDERBOOK_COLUMNS, clean)), default=str, ensure_ascii=False)
            orderbook_rows.append(clean + (raw_data,))

    ob_columns = [column for column in ORDERBOOK_COLUMNS if column not in {"snapshot_date", "snapshot_time", "stock_code"}]
    ob_sql = (
        f"INSERT INTO orderbook_snapshot ({', '.join(ORDERBOOK_COLUMNS)}, raw_data) "
        f"VALUES ({','.join('?' for _ in range(len(ORDERBOOK_COLUMNS) + 1))}) "
        "ON CONFLICT(snapshot_date, snapshot_time, stock_code) DO UPDATE SET "
        + ", ".join(f"{column}=excluded.{column}" for column in ob_columns)
        + ", raw_data=excluded.raw_data"
    )

    records = []
    for record in file_records:
        records.append(
            (
                str(record["sha256"]),
                str(record["filename"]),
                int(record.get("size_bytes", 0)),
                int(record.get("rows_read", 0)),
                int(record.get("rows_saved", 0)),
            )
        )

    with sqlite3.connect(DATABASE_FILE, timeout=60) as conn:
        _ensure_upload_ledger(conn)
        conn.execute("PRAGMA busy_timeout=60000")
        conn.execute("PRAGMA synchronous=NORMAL")
        conn.executemany(insert_sql, rows)
        if orderbook_rows:
            conn.executemany(ob_sql, orderbook_rows)
        if records:
            conn.executemany(
                "INSERT OR IGNORE INTO upload_ledger "
                "(sha256, filename, size_bytes, rows_read, rows_saved) VALUES (?, ?, ?, ?, ?)",
                records,
            )
        conn.commit()

    return {
        "rows_read": int(sum(len(frame) for frame in prepared_frames)),
        "rows_saved": int(len(data)),
        "orderbook_rows": int(len(orderbook_rows)),
        "files_saved": int(len(records)),
        "supabase_saved": bool(supabase_result.get("saved")),
        "supabase_duplicate": bool(supabase_result.get("duplicate")),
        "supabase_run_id": supabase_result.get("upload_run_id"),
    }
