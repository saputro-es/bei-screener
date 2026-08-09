import pandas as pd
import pytest

from modules import upload


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


def _record() -> dict:
    return {
        "sha256": "sample-sha",
        "filename": "sample.xlsx",
        "size_bytes": 123,
        "rows_read": 1,
        "rows_saved": 1,
    }


def test_supabase_failure_blocks_sqlite(monkeypatch, tmp_path):
    monkeypatch.setattr(upload, "DATABASE_FILE", tmp_path / "bei.db")
    monkeypatch.setattr(upload, "supabase_config", lambda: {"enabled": True})

    def fail(*args, **kwargs):
        raise RuntimeError("remote write failed")

    monkeypatch.setattr(upload, "persist_upload_batch", fail)

    with pytest.raises(RuntimeError, match="remote write failed"):
        upload.save_upload_batch([_frame()], [_record()])

    assert not (tmp_path / "bei.db").exists()


def test_supabase_success_allows_sqlite_commit(monkeypatch, tmp_path):
    monkeypatch.setattr(upload, "DATABASE_FILE", tmp_path / "bei.db")
    monkeypatch.setattr(upload, "supabase_config", lambda: {"enabled": True})
    monkeypatch.setattr(
        upload,
        "persist_upload_batch",
        lambda *args, **kwargs: {
            "saved": True,
            "duplicate": False,
            "upload_run_id": "run-1",
        },
    )

    result = upload.save_upload_batch([_frame()], [_record()])

    assert result["supabase_saved"] is True
    assert result["files_saved"] == 1
