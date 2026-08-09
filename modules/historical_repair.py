from __future__ import annotations

import pandas as pd

from .database import DAILY_ORDERBOOK_COLUMNS, normalize_dataframe
from .supabase_persistence import _post_rpc, _row_to_json

REPAIR_RPC_PATH = "/rest/v1/rpc/repair_historical_missing_fields"


def repair_frames(frames: list[pd.DataFrame]) -> dict[str, int]:
    """Fill only missing historical fields from re-read source files.

    This is deliberately separate from normal upload persistence: existing
    ledger hashes remain untouched, no new upload run is created, and the
    database RPC only coalesces values into NULL fields.
    """
    data = pd.concat(frames, ignore_index=True) if frames else pd.DataFrame()
    data = normalize_dataframe(data)
    data = data.dropna(subset=["trade_date", "stock_code"]).copy()
    data = data.drop_duplicates(subset=["trade_date", "stock_code"], keep="last")
    if data.empty:
        raise ValueError("Tidak ada baris valid untuk historical repair.")

    columns = [
        "trade_date", "stock_code", "company_name", "open_price", "high_price", "low_price",
        "close_price", "volume", "value", "frequency", "foreign_sell", "foreign_buy",
        *DAILY_ORDERBOOK_COLUMNS,
    ]
    for column in columns:
        if column not in data.columns:
            data[column] = None

    daily = []
    for _, row in data[columns].iterrows():
        item = _row_to_json(row)
        item["raw_data"] = _row_to_json(row)
        daily.append(item)

    orderbook = []
    for _, row in data[["trade_date", "stock_code"] + DAILY_ORDERBOOK_COLUMNS].iterrows():
        levels = {column: row.get(column) for column in DAILY_ORDERBOOK_COLUMNS}
        if not any(value is not None for value in levels.values()):
            continue
        item = {
            "snapshot_date": row.get("trade_date"),
            "snapshot_time": "00:00:00",
            "stock_code": row.get("stock_code"),
            **levels,
        }
        item["raw_data"] = _row_to_json(pd.Series(item))
        orderbook.append(item)

    result = _post_rpc(
        {"p_daily": daily, "p_orderbook": orderbook},
        path=REPAIR_RPC_PATH,
    )
    return {
        "daily_updated": int(result.get("daily_updated", 0)),
        "orderbook_updated": int(result.get("orderbook_updated", 0)),
    }
