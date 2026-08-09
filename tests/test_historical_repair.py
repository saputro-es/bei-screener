import pandas as pd

from modules import supabase_persistence as persistence


def _row():
    return {
        "Kode Saham": "TEST",
        "Nama Perusahaan": "Test Company",
        "Tanggal Perdagangan Terakhir": "31/07/2026",
        "Penutupan": 100,
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
