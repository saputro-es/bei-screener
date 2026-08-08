"""SQLite persistence for uploaded BEI stock snapshots."""
from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Iterable

import pandas as pd

DB_PATH = Path("database") / "bei_screener.db"


def get_connection(db_path: Path | str = DB_PATH) -> sqlite3.Connection:
    path = Path(db_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path)
    conn.execute(
        """CREATE TABLE IF NOT EXISTS stock_daily (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            upload_date TEXT NOT NULL,
            source_file TEXT,
            stock_code TEXT,
            stock_name TEXT,
            trade_date TEXT,
            price REAL,
            volume REAL,
            net_buy_pct REAL,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(stock_code, trade_date, source_file)
        )"""
    )
    conn.commit()
    return conn


def save_dataframe(df: pd.DataFrame, source_file: str = "upload.xlsx", db_path: Path | str = DB_PATH) -> int:
    if df.empty:
        return 0
    conn = get_connection(db_path)
    work = df.copy()
    work.columns = [str(c).strip() for c in work.columns]
    mapping = {}
    aliases = {
        "stock_code": ["stock_code", "kode", "kode saham", "symbol", "ticker", "code"],
        "stock_name": ["stock_name", "nama", "nama saham", "name"],
        "trade_date": ["trade_date", "date", "tanggal", "trading date"],
        "price": ["price", "harga", "close", "last", "harga terakhir"],
        "volume": ["volume", "vol"],
        "net_buy_pct": ["net_buy_pct", "% net buy", "net buy %", "net buy", "accumulation", "akumulasi"],
    }
    lower = {str(c).lower(): c for c in work.columns}
    for target, names in aliases.items():
        for name in names:
            if name.lower() in lower:
                mapping[target] = lower[name.lower()]
                break
    out = pd.DataFrame(index=work.index)
    for target in aliases:
        out[target] = work[mapping[target]] if target in mapping else None
    out["upload_date"] = pd.Timestamp.now().strftime("%Y-%m-%d")
    out["source_file"] = source_file
    for c in ["price", "volume", "net_buy_pct"]:
        out[c] = pd.to_numeric(out[c], errors="coerce")
    out["trade_date"] = pd.to_datetime(out["trade_date"], errors="coerce").dt.strftime("%Y-%m-%d")
    out = out.dropna(subset=["stock_code"])
    out.to_sql("stock_daily", conn, if_exists="append", index=False)
    conn.close()
    return len(out)


def database_info(db_path: Path | str = DB_PATH) -> dict:
    conn = get_connection(db_path)
    rows = conn.execute("SELECT COUNT(*) FROM stock_daily").fetchone()[0]
    stocks = conn.execute("SELECT COUNT(DISTINCT stock_code) FROM stock_daily").fetchone()[0]
    days = conn.execute("SELECT COUNT(DISTINCT trade_date) FROM stock_daily WHERE trade_date IS NOT NULL").fetchone()[0]
    conn.close()
    return {"total_rows": rows, "total_stocks": stocks, "total_days": days}


def load_recent(limit: int = 10000, db_path: Path | str = DB_PATH) -> pd.DataFrame:
    conn = get_connection(db_path)
    df = pd.read_sql_query("SELECT * FROM stock_daily ORDER BY trade_date DESC, id DESC LIMIT ?", conn, params=(limit,))
    conn.close()
    return df
