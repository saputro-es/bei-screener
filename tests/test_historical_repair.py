import pandas as pd

from modules import historical_repair
from modules import supabase_persistence as persistence


def _row():
    return {
        "Kode Saham": "TEST",
        "Nama Perusahaan": "Test Company",
        "Tanggal Perdagangan Terakhir": "31/07/2026",
        "Sebelumnya": 95,
        "First Trade": 98,
        "Penutupan": 100,
        "Selisih": 5,
        "Index Individual": 0.0012,
        "Listed Shares": 1000000,
        "Tradeble Shares": 900000,
        "Weight For Index": 0.0009,
        "Non Regular Volume": 10,
        "Non Regular Value": 1000,
        "Non Regular Frequency": 2,
        "Volume": 1000,
        "Foreign Buy": 700,
        "Foreign Sell": 300,
        "Offer": 101,
        "Offer Volume": 800,
        "Bid": 99,
        "Bid Volume": 900,
    }


def test_duplicate_upload_repairs_missing_historical_fields(monkeypatch):
    calls = []
    monkeypatch.setattr(persistence, "_existing_remote_hashes", lambda hashes: set(hashes))

    def fake_post(payload, path=persistence.RPC_PATH):
        calls.append((payload, path))
        return {"daily_updated": 1, "orderbook_updated": 1}

    monkeypatch.setattr(persistence, "_post_rpc", fake_post)
    result = persistence.persist_upload_batch(
        [pd.DataFrame([_row()])],
        [{"sha256": "a" * 64, "filename": "sample.xlsx", "size_bytes": 1, "rows_read": 1, "rows_saved": 1}],
    )

    assert result["duplicate"] is True
    assert result["repaired"] is True
    assert result["repair_daily_rows"] == 1
    assert result["repair_orderbook_rows"] == 1
    assert calls[0][1] == persistence.REPAIR_RPC_PATH
    assert calls[0][0]["p_daily"][0]["ask_volume_1"] == 800


def test_repair_frames_preserves_source_only_excel_fields(monkeypatch):
    captured = {}

    def fake_post(payload, path=persistence.RPC_PATH):
        captured["payload"] = payload
        captured["path"] = path
        return {"daily_updated": 1, "orderbook_updated": 1}

    monkeypatch.setattr(historical_repair, "_post_rpc", fake_post)
    result = historical_repair.repair_frames([pd.DataFrame([_row()])])

    raw = captured["payload"]["p_daily"][0]["raw_data"]
    assert captured["path"] == historical_repair.REPAIR_RPC_PATH
    assert result == {"daily_updated": 1, "orderbook_updated": 1}
    assert raw["Sebelumnya"] == 95
    assert raw["First Trade"] == 98
    assert raw["Selisih"] == 5
    assert raw["Index Individual"] == 0.0012
    assert raw["Listed Shares"] == 1000000
    assert raw["Tradeble Shares"] == 900000
    assert raw["Weight For Index"] == 0.0009
    assert raw["Non Regular Volume"] == 10
    assert raw["Non Regular Value"] == 1000
    assert raw["Non Regular Frequency"] == 2

    orderbook_raw = captured["payload"]["p_orderbook"][0]["raw_data"]
    assert orderbook_raw["Listed Shares"] == 1000000


def test_partial_duplicate_batch_still_fails_closed(monkeypatch):
    monkeypatch.setattr(persistence, "_existing_remote_hashes", lambda hashes: {next(iter(hashes))})
    try:
        persistence.persist_upload_batch(
            [pd.DataFrame([_row()])],
            [
                {"sha256": "a" * 64, "filename": "old.xlsx", "size_bytes": 1, "rows_read": 1, "rows_saved": 1},
                {"sha256": "b" * 64, "filename": "new.xlsx", "size_bytes": 1, "rows_read": 1, "rows_saved": 1},
            ],
        )
    except RuntimeError as exc:
        assert "Sebagian file batch" in str(exc)
    else:
        raise AssertionError("partial duplicate batch must fail closed")
