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

ORDERBOOK_ALIASES = {
    "snapshot_date": ["Tanggal", "Date", "Trade Date", "Tanggal Perdagangan Terakhir"],
    "snapshot_time": ["Waktu", "Time", "Timestamp", "Jam"],
    "stock_code": ["Kode Saham", "Kode", "Ticker", "Symbol"],
    "bid_price_1": ["Bid Price 1", "Bid1 Price", "Bid 1", "Best Bid", "Harga Bid 1"],
    "bid_volume_1": ["Bid Volume 1", "Bid1 Volume", "Bid 1 Volume", "Bid Volume", "Volume Bid 1", "Best Bid Volume"],
    "ask_price_1": ["Offer Price 1", "Ask Price 1", "Offer1 Price", "Ask1 Price", "Offer 1", "Harga Offer 1", "Best Offer"],
    "ask_volume_1": ["Offer Volume 1", "Ask Volume 1", "Offer1 Volume", "Ask1 Volume", "Offer 1 Volume", "Volume Offer 1", "Best Offer Volume"],
}

for side, side_alias in (("bid", "Bid"), ("ask", "Ask")):
    for level in range(2, 6):
        ORDERBOOK_ALIASES[f"{side}_price_{level}"] = [
            f"{side_alias} Price {level}", f"{side_alias}{level} Price", f"{side_alias} {level}",
            f"Harga {side_alias} {level}",
        ]
        ORDERBOOK_ALIASES[f"{side}_volume_{level}"] = [
            f"{side_alias} Volume {level}", f"{side_alias}{level} Volume", f"{side_alias} {level} Volume",
            f"Volume {side_alias} {level}",
        ]

OPTIONAL_COLUMNS = [
    "company_name", "open_price", "high_price", "low_price", "close_price",
    "volume", "value", "frequency", "foreign_sell", "foreign_buy",
]

COLUMN_TYPES = {
    "trade_date": "TEXT", "stock_code": "TEXT", "company_name": "TEXT",
    "open_price": "REAL", "high_price": "REAL", "low_price": "REAL", "close_price": "REAL",
    "volume": "REAL", "value": "REAL", "frequency": "REAL",
    "foreign_sell": "REAL", "foreign_buy": "REAL", "raw_data": "TEXT",
}

ORDERBOOK_COLUMNS = ["snapshot_date", "snapshot_time", "stock_code"] + [
    f"{side}_{kind}_{level}"
    for level in range(1, 6)
    for side in ("bid", "ask")
    for kind in ("price", "volume")
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
    data["trade_date"] = pd.to_datetime(data["trade_date"], errors="coerce", dayfirst=True).dt.strftime("%Y-%m-%d")
    for col in ["open_price", "high_price", "low_price", "close_price", "volume", "value", "frequency", "foreign_sell", "foreign_buy"]:
        data[col] = pd.to_numeric(data[col], errors="coerce")
    return data


def normalize_orderbook_dataframe(df: pd.DataFrame) -> pd.DataFrame:
    if df is None or df.empty:
        return pd.DataFrame()
    data = df.copy()
    data.columns = [str(c).strip() for c in data.columns]
    for canonical, aliases in ORDERBOOK_ALIASES.items():
        source = _find_column(data.columns, aliases)
        if source is not None and canonical not in data.columns:
            data[canonical] = data[source]

    if "stock_code" not in data.columns:
        raise ValueError("Orderbook membutuhkan kolom Kode Saham/Ticker.")
    if "snapshot_date" not in data.columns:
        data["snapshot_date"] = pd.Timestamp.today().normalize()
    if "snapshot_time" not in data.columns:
        data["snapshot_time"] = "00:00:00"

    data["stock_code"] = data["stock_code"].astype(str).str.strip().str.upper()
    data.loc[data["stock_code"].isin(["", "NAN", "NONE"]), "stock_code"] = pd.NA
    data["snapshot_date"] = pd.to_datetime(data["snapshot_date"], errors="coerce", dayfirst=True).dt.strftime("%Y-%m-%d")
    data["snapshot_time"] = data["snapshot_time"].astype(str).replace({"nan": "00:00:00", "NaT": "00:00:00"})
    for col in ORDERBOOK_COLUMNS:
        if col not in data.columns:
            data[col] = None
        elif col not in {"snapshot_date", "snapshot_time", "stock_code"}:
            data[col] = pd.to_numeric(data[col], errors="coerce")
    return data[ORDERBOOK_COLUMNS].dropna(subset=["snapshot_date", "stock_code"]).copy()


def _migrate_schema(conn: sqlite3.Connection) -> None:
    existing = {row[1] for row in conn.execute("PRAGMA table_info(stock_daily)").fetchall()}
    for column, sql_type in COLUMN_TYPES.items():
        if column not in existing:
            conn.execute(f"ALTER TABLE stock_daily ADD COLUMN {column} {sql_type}")

    if "price" in existing:
        conn.execute("UPDATE stock_daily SET close_price = COALESCE(close_price, price)")
    if "stock_name" in existing:
        conn.execute("UPDATE stock_daily SET company_name = COALESCE(company_name, stock_name)")

    conn.execute(
        """
        DELETE FROM stock_daily
        WHERE rowid NOT IN (
            SELECT MAX(rowid) FROM stock_daily
            WHERE trade_date IS NOT NULL AND stock_code IS NOT NULL
            GROUP BY trade_date, stock_code
        )
        AND trade_date IS NOT NULL AND stock_code IS NOT NULL
        """
    )
    conn.execute("CREATE UNIQUE INDEX IF NOT EXISTS ux_stock_daily_date_code ON stock_daily(trade_date, stock_code)")
    conn.commit()


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
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS orderbook_snapshot (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                snapshot_date TEXT NOT NULL,
                snapshot_time TEXT NOT NULL DEFAULT '00:00:00',
                stock_code TEXT NOT NULL,
                bid_price_1 REAL, bid_volume_1 REAL,
                ask_price_1 REAL, ask_volume_1 REAL,
                bid_price_2 REAL, bid_volume_2 REAL,
                ask_price_2 REAL, ask_volume_2 REAL,
                bid_price_3 REAL, bid_volume_3 REAL,
                ask_price_3 REAL, ask_volume_3 REAL,
                bid_price_4 REAL, bid_volume_4 REAL,
                ask_price_4 REAL, ask_volume_4 REAL,
                bid_price_5 REAL, bid_volume_5 REAL,
                ask_price_5 REAL, ask_volume_5 REAL,
                raw_data TEXT,
                created_at TEXT DEFAULT CURRENT_TIMESTAMP,
                UNIQUE(snapshot_date, snapshot_time, stock_code)
            )
            """
        )
        _migrate_schema(conn)
        conn.execute("CREATE INDEX IF NOT EXISTS idx_stock_date ON stock_daily(stock_code, trade_date)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_trade_date ON stock_daily(trade_date)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_orderbook_code_time ON orderbook_snapshot(stock_code, snapshot_date, snapshot_time)")
        conn.commit()


def save_dataframe(df: pd.DataFrame) -> int:
    data = normalize_dataframe(df)
    if data.empty:
        return 0
    init_database()
    data = data.dropna(subset=["trade_date", "stock_code"]).copy()
    saved = 0
    with sqlite3.connect(DATABASE_FILE) as conn:
        for _, row in data.iterrows():
            raw_data = json.dumps(row.to_dict(), default=str, ensure_ascii=False)
            values = tuple(_db_value(row.get(col)) for col in [
                "trade_date", "stock_code", "company_name", "open_price", "high_price", "low_price",
                "close_price", "volume", "value", "frequency", "foreign_sell", "foreign_buy"
            ]) + (raw_data,)
            conn.execute(
                """
                INSERT INTO stock_daily (
                    trade_date, stock_code, company_name, open_price, high_price, low_price, close_price,
                    volume, value, frequency, foreign_sell, foreign_buy, raw_data
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(trade_date, stock_code) DO UPDATE SET
                    company_name=excluded.company_name, open_price=excluded.open_price,
                    high_price=excluded.high_price, low_price=excluded.low_price, close_price=excluded.close_price,
                    volume=excluded.volume, value=excluded.value, frequency=excluded.frequency,
                    foreign_sell=excluded.foreign_sell, foreign_buy=excluded.foreign_buy, raw_data=excluded.raw_data
                """, values,
            )
            saved += 1
        conn.commit()
    return saved


def save_orderbook(df: pd.DataFrame) -> int:
    data = normalize_orderbook_dataframe(df)
    if data.empty:
        return 0
    init_database()
    saved = 0
    value_cols = [c for c in ORDERBOOK_COLUMNS if c not in {"snapshot_date", "snapshot_time", "stock_code"}]
    with sqlite3.connect(DATABASE_FILE) as conn:
        for _, row in data.iterrows():
            raw_data = json.dumps(row.to_dict(), default=str, ensure_ascii=False)
            values = tuple(_db_value(row.get(c)) for c in ORDERBOOK_COLUMNS) + (raw_data,)
            assignments = ", ".join(f"{c}=excluded.{c}" for c in value_cols) + ", raw_data=excluded.raw_data"
            conn.execute(
                f"""
                INSERT INTO orderbook_snapshot ({', '.join(ORDERBOOK_COLUMNS)}, raw_data)
                VALUES ({', '.join('?' for _ in values)})
                ON CONFLICT(snapshot_date, snapshot_time, stock_code) DO UPDATE SET {assignments}
                """, values,
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


def load_orderbook(stock_code: str | None = None, latest_only: bool = False) -> pd.DataFrame:
    init_database()
    query = "SELECT * FROM orderbook_snapshot"
    params: list[object] = []
    if stock_code:
        query += " WHERE stock_code = ?"
        params.append(str(stock_code).upper())
    query += " ORDER BY snapshot_date ASC, snapshot_time ASC, stock_code ASC"
    with sqlite3.connect(DATABASE_FILE) as conn:
        data = pd.read_sql_query(query, conn, params=params)
    if latest_only and not data.empty:
        data = data.sort_values(["snapshot_date", "snapshot_time"]).groupby("stock_code", as_index=False).tail(1)
    return data.reset_index(drop=True)


def database_info() -> dict[str, int]:
    init_database()
    with sqlite3.connect(DATABASE_FILE) as conn:
        total_rows = conn.execute("SELECT COUNT(*) FROM stock_daily").fetchone()[0]
        total_stocks = conn.execute("SELECT COUNT(DISTINCT stock_code) FROM stock_daily").fetchone()[0]
        total_days = conn.execute("SELECT COUNT(DISTINCT trade_date) FROM stock_daily").fetchone()[0]
        orderbook_rows = conn.execute("SELECT COUNT(*) FROM orderbook_snapshot").fetchone()[0]
    return {"total_rows": total_rows, "total_stocks": total_stocks, "total_days": total_days, "orderbook_rows": orderbook_rows}


def clear_database() -> None:
    init_database()
    with sqlite3.connect(DATABASE_FILE) as conn:
        conn.execute("DELETE FROM stock_daily")
        conn.execute("DELETE FROM orderbook_snapshot")
        conn.commit()
