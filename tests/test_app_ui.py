from pathlib import Path


APP = Path(__file__).resolve().parents[1] / "app.py"


def test_uploader_does_not_override_streamlit_file_uploader_dom():
    source = APP.read_text(encoding="utf-8")
    assert '[data-testid="stFileUploader"]' not in source
    assert "unsafe_allow_html=True" not in source


def test_uploader_uses_native_scroll_container_and_multiple_files():
    source = APP.read_text(encoding="utf-8")
    assert "with st.container(height=430, border=True):" in source
    assert "accept_multiple_files=True" in source
    assert "MAX_FILES_PER_BATCH" in source
