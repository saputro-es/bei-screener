from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import Iterable

import pandas as pd

BASE_DIR = Path(__file__).resolve().parent.parent
DATABASE_DIR = BASE_DIR / "database"
DATABASE_FILE = DATABASE_DIR / "bei_screener.db"

COLUMN_ALIASES = {
    "trade_date": ["Tanggal Perdagangan Terakhir", "Tanggal", "Trade Date", "Date"],
    "stock_code": ["Kode Saham", "Kode", "Ticker", "Symbol"],
    "company_name": ["Nama Perusahaan", "Nama", "Company", "Company Name"],
    "open_price": ["Open Price", "Open", "Pembukaan"],
    "high_price": ["Tertinggi", "High", "High Price"],
    "low_price": ["Terendah", "Low", "Low Price"],
    "close_price": ["Penutupan", "Close", "Closing", "Close Price"],
    "volume": ["Volume", "Volume Saham"],
    "value": ["Nilai", "Value", "Trading Value"],
    "frequency": ["Frekuensi", "Frequency"],
    "foreign_sell": ["Foreign Sell", "Foreign Sell Volume", "Foreign Sell Value", "Asing Sell"],
    "foreign_buy": ["Foreign Buy", "Foreign Buy Volume", "Foreign Buy Value", "Asing Buy"],
}

OPTIONAL_COLUMNS = [
    "company_name", "open_price", "high_price", "low_price", "close_price",
    "volume", "value", "frequency", "foreign_sell", "foreign_buy",
]


def _find_column(columns: Iterable[str], aliases: list[str]) -> str | None:
    normalized = {str(c).strip().lower(): c for c in columns}
    for alias in aliases:
        if alias.lower() in normalized:
            return normalized[alias.lower()]
    for alias in aliases:
        needle = alias.lower()
        for col in columns:
            if needle in str(col).strip().lower():
                return col
    return None


def _db_value(value):
    if value is None:
        return None
    try:
        if pd.isna(value):
            return None
    except (TypeError, ValueError):
        pass
    return value


def normalize_dataframe(df: pd.DataFrame) -> pd.DataFrame:
    """Normalize common BEI column names while retaining original columns."""
    if df is None or df.empty:
        return pd.DataFrame()

    data = df.copy()
    data.columns = [str(c).strip() for c in data.columns]

    for canonical, aliases in COLUMN_ALIASES.items():
        source = _find_column(data.columns, aliases)
        if source is not None and canonical not in data.columns:
            data[canonical] = data[source]

    required = {"trade_date", "stock_code"}
    missing = required - set(data.columns)
    if missing:
        raise ValueError("Kolom wajib tidak ditemukan: " + ", ".join(sorted(missing)))

    for col in OPTIONAL_COLUMNS:
        if col not in data.columns:
            data[col] = None

    data["stock_code"] = data["stock_code"].astype(str).str.strip().str.upper()
    data.loc[data["stock_code"].isin(["", "NAN", "NONE"]), "stock_code"] = pd.NA
    data["company_name"] = data["company_name"].astype("string")

    parsed = pd.to_datetime(data["trade_date"], errors="coerce", dayfirst=True)
    data["trade_date"] = parsed.dt.strftime("%Y-%m-%d")

    numeric_columns = [
        "open_price", "high_price", "low_price", "close_price", "volume",
        "value", "frequency", "foreign_sell", "foreign_buy",
    ]
    for col in numeric_columns:
        data[col] = pd.to_numeric(data[col], errors="coerce")

    return data


def init_database() -> None:
    DATABASE_DIR.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(DATABASE_FILE) as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS stock_daily (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                trade_date TEXT NOT NULL,
                stock_code TEXT NOT NULL,
                company_name TEXT,
                open_price REAL,
                high_price REAL,
                low_price REAL,
                close_price REAL,
                volume REAL,
                value REAL,
                frequency REAL,
                foreign_sell REAL,
                foreign_buy REAL,
                raw_data TEXT,
                created_at TEXT DEFAULT CURRENT_TIMESTAMP,
                UNIQUE(trade_date, stock_code)
            )
            """
        )
        conn.execute("CREATE INDEX IF NOT EXISTS idx_stock_date ON stock_daily(stock_code, trade_date)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_trade_date ON stock_daily(trade_date)")
        conn.commit()


def save_dataframe(df: pd.DataFrame) -> int:
    """Upsert valid daily rows and return the number of rows written."""
    data = normalize_dataframe(df)
    if data.empty:
        return 0
    init_database()
    data = data.dropna(subset=["trade_date", "stock_code"]).copy()
    if data.empty:
        return 0

    saved = 0
    with sqlite3.connect(DATABASE_FILE) as conn:
        for _, row in data.iterrows():
            raw_data = json.dumps(row.to_dict(), default=str, ensure_ascii=False)
            values = (
                _db_value(row.get("trade_date")), _db_value(row.get("stock_code")),
                _db_value(row.get("company_name")), _db_value(row.get("open_price")),
                _db_value(row.get("high_price")), _db_value(row.get("low_price")),
                _db_value(row.get("close_price")), _db_value(row.get("volume")),
                _db_value(row.get("value")), _db_value(row.get("frequency")),
                _db_value(row.get("foreign_sell")), _db_value(row.get("foreign_buy")), raw_data,
            )
            conn.execute(
                """
                INSERT INTO stock_daily (
                    trade_date, stock_code, company_name, open_price, high_price,
                    low_price, close_price, volume, value, frequency,
                    foreign_sell, foreign_buy, raw_data
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(trade_date, stock_code) DO UPDATE SET
                    company_name=excluded.company_name,
                    open_price=excluded.open_price,
                    high_price=excluded.high_price,
                    low_price=excluded.low_price,
                    close_price=excluded.close_price,
                    volume=excluded.volume,
                    value=excluded.value,
                    frequency=excluded.frequency,
                    foreign_sell=excluded.foreign_sell,
                    foreign_buy=excluded.foreign_buy,
                    raw_data=excluded.raw_data
                """,
                values,
            )
            saved += 1
        conn.commit()
    return saved


def load_data(stock_code: str | None = None, days: int | None = None) -> pd.DataFrame:
    init_database()
    query = "SELECT * FROM stock_daily"
    params: list[object] = []
    clauses: list[str] = []
    if stock_code:
        clauses.append("stock_code = ?")
        params.append(str(stock_code).upper())
    if days is not None:
        clauses.append("trade_date >= date((SELECT MAX(trade_date) FROM stock_daily), ?)")
        params.append(f"-{int(days) - 1} days")
    if clauses:
        query += " WHERE " + " AND ".join(clauses)
    query += " ORDER BY trade_date ASC, stock_code ASC"
    with sqlite3.connect(DATABASE_FILE) as conn:
        return pd.read_sql_query(query, conn, params=params)


def database_info() -> dict[str, int]:
    init_database()
    with sqlite3.connect(DATABASE_FILE) as conn:
        total_rows = conn.execute("SELECT COUNT(*) FROM stock_daily").fetchone()[0]
        total_stocks = conn.execute("SELECT COUNT(DISTINCT stock_code) FROM stock_daily").fetchone()[0]
        total_days = conn.execute("SELECT COUNT(DISTINCT trade_date) FROM stock_daily").fetchone()[0]
    return {"total_rows": total_rows, "total_stocks": total_stocks, "total_days": total_days}


def clear_database() -> None:
    """Delete stored rows without deleting the SQLite file."""
    init_database()
    with sqlite3.connect(DATABASE_FILE) as conn:
        conn.execute("DELETE FROM stock_daily")
        conn.commit()
