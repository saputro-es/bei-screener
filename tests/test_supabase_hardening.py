import hashlib

import pandas as pd
import pytest

from modules import supabase_persistence


def _frame() -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                "trade_date": "2026-08-07",
                "stock_code": "TLKM",
                "company_name": "Telkom Indonesia",
                "close_price": 2740,
                "foreign_buy": 100,
                "foreign_sell": 40,
            }
        ]
    )


def _record(name: str = "sample.xlsx", sha: str | None = None) -> dict:
    return {
        "sha256": sha or hashlib.sha256(name.encode()).hexdigest(),
        "filename": name,
        "size_bytes": 123,
        "rows_read": 1,
        "rows_saved": 1,
    }


def test_batch_key_is_order_independent():
    a = [_record("a.xlsx")]
    b = [_record("b.xlsx")]
    assert supabase_persistence._batch_key(a + b) == supabase_persistence._batch_key(b + a)


def test_batch_key_rejects_invalid_hash():
    with pytest.raises(ValueError):
        supabase_persistence._batch_key([_record(sha="bad")])


def test_persist_rejects_empty_batch(monkeypatch):
    with pytest.raises(ValueError, match="kosong"):
        supabase_persistence.persist_upload_batch([], [])


def test_persist_rejects_no_valid_daily_rows(monkeypatch):
    monkeypatch.setattr(supabase_persistence, "_post_rpc", lambda payload: pytest.fail("RPC must not run"))
    bad = pd.DataFrame({"trade_date": [None], "stock_code": [None]})
    with pytest.raises(ValueError, match="valid"):
        supabase_persistence.persist_upload_batch([bad], [_record()])


def test_remote_duplicate_is_idempotent(monkeypatch):
    monkeypatch.setattr(
        supabase_persistence,
        "_existing_remote_hashes",
        lambda hashes: set(hashes),
    )
    calls = []

    def fake_post(payload, *, path):
        calls.append(path)
        return {"daily_updated": 1, "orderbook_updated": 1}

    monkeypatch.setattr(supabase_persistence, "_post_rpc", fake_post)
    result = supabase_persistence.persist_upload_batch([_frame()], [_record()])
    assert result["saved"] is True
    assert result["duplicate"] is True
    assert calls == [supabase_persistence.REPAIR_RPC_PATH]


def test_partial_remote_duplicate_is_blocked(monkeypatch):
    first = _record("a.xlsx")
    second = _record("b.xlsx")
    monkeypatch.setattr(supabase_persistence, "_existing_remote_hashes", lambda hashes: {first["sha256"]})
    with pytest.raises(RuntimeError, match="Sebagian file"):
        supabase_persistence.persist_upload_batch([_frame()], [first, second])
