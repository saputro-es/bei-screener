from __future__ import annotations

import pandas as pd

from .database import DAILY_ORDERBOOK_COLUMNS, normalize_dataframe
from .supabase_persistence import _post_rpc, _row_to_json

REPAIR_RPC_PATH = "/rest/v1/rpc/repair_historical_missing_fields"


def repair_frames(frames: list[pd.DataFrame]) -> dict[str, int]:
    """Repair existing historical rows from the complete source Excel rows.

    The canonical fields are normalized for matching and repair, while the
    complete normalized source row is preserved in raw_data. Existing upload
    ledger hashes are untouched and no new upload run is created.
    """
    data = pd.concat(frames, ignore_index=True) if frames else pd.DataFrame()
    data = normalize_dataframe(data)
    data = data.dropna(subset=["trade_date", "stock_code"]).copy()
    data = data.drop_duplicates(subset=["trade_date", "stock_code"], keep="last")
    if data.empty:
        raise ValueError("Tidak ada baris valid untuk historical repair.")

    canonical_columns = [
        "trade_date", "stock_code", "company_name", "open_price", "high_price", "low_price",
        "close_price", "volume", "value", "frequency", "foreign_sell", "foreign_buy",
        *DAILY_ORDERBOOK_COLUMNS,
    ]
    for column in canonical_columns:
        if column not in data.columns:
            data[column] = None

    daily = []
    for _, row in data.iterrows():
        item = {column: _row_to_json(pd.Series({column: row.get(column)}))[column] for column in canonical_columns}
        item["raw_data"] = _row_to_json(row)
        daily.append(item)

    orderbook = []
    for _, row in data.iterrows():
        levels = {column: row.get(column) for column in DAILY_ORDERBOOK_COLUMNS}
        if not any(value is not None for value in levels.values()):
            continue
        item = {
            "snapshot_date": row.get("trade_date"),
            "snapshot_time": "00:00:00",
            "stock_code": row.get("stock_code"),
            **levels,
        }
        # Preserve the complete source row here too; the canonical orderbook
        # columns remain at the top level for the RPC recordset.
        item["raw_data"] = _row_to_json(row)
        orderbook.append(item)

    result = _post_rpc(
        {"p_daily": daily, "p_orderbook": orderbook},
        path=REPAIR_RPC_PATH,
    )
    return {
        "daily_updated": int(result.get("daily_updated", 0)),
        "orderbook_updated": int(result.get("orderbook_updated", 0)),
    }
