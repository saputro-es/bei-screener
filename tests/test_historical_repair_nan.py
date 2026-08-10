from __future__ import annotations

import json

import numpy as np
import pandas as pd

from modules import historical_repair


def test_historical_repair_orderbook_payload_contains_no_nan(monkeypatch):
    captured = {}

    def fake_post(payload, path=historical_repair.REPAIR_RPC_PATH):
        captured["payload"] = payload
        captured["path"] = path
        json.dumps(payload, allow_nan=False)
        return {"daily_updated": 1, "orderbook_updated": 1}

    monkeypatch.setattr(historical_repair, "_post_rpc", fake_post)

    frame = pd.DataFrame(
        [
            {
                "Kode Saham": "SMDM",
                "Tanggal Perdagangan Terakhir": "2026-07-01",
                "Penutupan": 570,
                "Bid": 569,
                "Bid Volume": np.nan,
                "Offer": 571,
                "Offer Volume": np.nan,
            }
        ]
    )

    result = historical_repair.repair_frames([frame])

    assert result == {"daily_updated": 1, "orderbook_updated": 1}
    assert captured["path"] == historical_repair.REPAIR_RPC_PATH
    json.dumps(captured["payload"], allow_nan=False)
    orderbook = captured["payload"]["p_orderbook"][0]
    assert orderbook["bid_volume_1"] is None
    assert orderbook["ask_volume_1"] is None
