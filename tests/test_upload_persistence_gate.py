from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
UPLOAD = ROOT / "modules" / "upload.py"
APP = ROOT / "app.py"


def test_upload_hashes_are_not_complete_before_durable_persistence():
    source = UPLOAD.read_text(encoding="utf-8")
    assert "persistence_status TEXT NOT NULL DEFAULT 'pending'" in source
    assert "AND persistence_status = 'complete'" in source
    assert "persistence_status='pending'" in source
    assert "mark_persistence_complete" in source


def test_upload_persists_to_supabase_before_marking_complete():
    source = UPLOAD.read_text(encoding="utf-8")
    sync_pos = source.index("sync_sqlite_to_supabase()")
    mark_pos = source.index("mark_persistence_complete(record[\"sha256\"] for record in file_records)")
    assert sync_pos < mark_pos


def test_app_upload_still_requires_persistence_configuration():
    source = APP.read_text(encoding="utf-8")
    assert "disabled=not persistence_cfg[\"enabled\"]" in source
    assert "backup_database()" in source
