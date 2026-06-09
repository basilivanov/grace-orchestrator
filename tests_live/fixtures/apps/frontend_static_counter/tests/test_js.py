from pathlib import Path


BASE_DIR = Path(__file__).resolve().parent.parent


def test_index_html_fixture() -> None:
    index_file = BASE_DIR / "index.html"

    assert index_file.exists()
    content = index_file.read_text()
    assert "<!DOCTYPE html>" in content
    assert "Counter" in content
    assert "count" in content


def test_app_js_fixture() -> None:
    app_file = BASE_DIR / "app.js"

    assert app_file.exists()
    content = app_file.read_text()
    assert "addEventListener" in content
