from pathlib import Path


APP = Path(__file__).resolve().parents[1] / "app.py"


def test_uploader_does_not_override_streamlit_file_uploader_dom():
    source = APP.read_text(encoding="utf-8")
    assert '[data-testid="stFileUploader"]' not in source
    assert "unsafe_allow_html=True" not in source


def test_uploader_keeps_native_mobile_selection_visible_and_supports_multiple_files():
    source = APP.read_text(encoding="utf-8")
    assert "files = st.file_uploader(" in source
    assert "accept_multiple_files=True" in source
    assert "MAX_FILES_PER_BATCH" in source
    assert "if files:" in source
    assert 'st.success(f"📎 {len(files)} file siap diproses:' in source
    assert "st.button(" in source
    assert "disabled=not persistence_cfg[\"enabled\"] or not files" in source
    assert 'with st.form("daily_upload_form"' not in source


def test_candidate_identity_columns_remain_pinned():
    source = APP.read_text(encoding="utf-8")
    assert '"stock_code": st.column_config.TextColumn("Stock", pinned=True)' in source
    assert '"company_name": st.column_config.TextColumn("Company", pinned=True)' in source
