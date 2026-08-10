from pathlib import Path


APP = Path(__file__).resolve().parents[1] / "app.py"


def test_upload_result_is_persisted_across_rerun():
    source = APP.read_text(encoding="utf-8")
    assert '"upload_notice"' in source
    assert "st.session_state.upload_notice =" in source
    assert "upload_notice = st.session_state.pop(\"upload_notice\")" in source


def test_success_path_sets_notice_before_rerun():
    source = APP.read_text(encoding="utf-8")
    success_marker = 'st.session_state.upload_notice = {"kind": "success"'
    assert success_marker in source
    assert source.index(success_marker) < source.index("st.rerun()")


def test_existing_data_is_not_deleted_by_upload_feedback():
    source = APP.read_text(encoding="utf-8")
    assert "DELETE FROM" not in source
    assert "drop_all" not in source
    assert "reset_database" not in source
