# ############################################################################
# AI_HEADER: test_js_syntax
# ROLE: Validate dashboard JavaScript has no syntax errors before deployment.
# ############################################################################

"""Catch JS syntax errors BEFORE they reach the browser."""
import re
import httpx

API = "http://localhost:8042"


def _extract_js(html: str) -> str:
    m = re.search(r"<script>(.*?)</script>", html, re.DOTALL)
    if not m:
        raise ValueError("No <script> tag found in HTML")
    return m.group(1)


def test_html_has_script_tag():
    r = httpx.get(f"{API}/", timeout=5)
    js = _extract_js(r.text)
    assert len(js) > 1000, f"JS too short: {len(js)} bytes"


def test_no_unescaped_quotes_in_concat():
    """Catch patterns like: '...\\'' + var + '...'  — these are error-prone."""
    r = httpx.get(f"{API}/", timeout=5)
    js = _extract_js(r.text)
    # Any line with 4+ backslashes in a row is suspicious
    for i, line in enumerate(js.split("\n"), 1):
        if line.count("\\\\") >= 2:
            raise AssertionError(f"Line {i}: suspicious escaping: {line.strip()[:80]}")


def test_balanced_backticks():
    r = httpx.get(f"{API}/", timeout=5)
    js = _extract_js(r.text)
    count = js.count("`")
    assert count % 2 == 0, f"Unbalanced backticks: {count}"


def test_balanced_braces():
    r = httpx.get(f"{API}/", timeout=5)
    js = _extract_js(r.text)
    assert js.count("{") == js.count("}"), "Unbalanced braces"


def test_balanced_parens():
    r = httpx.get(f"{API}/", timeout=5)
    js = _extract_js(r.text)
    assert js.count("(") == js.count(")"), "Unbalanced parentheses"


def test_balanced_brackets():
    r = httpx.get(f"{API}/", timeout=5)
    js = _extract_js(r.text)
    assert js.count("[") == js.count("]"), "Unbalanced brackets"


def test_no_onclick_with_escaped_quotes():
    """Catch the most common bug: onclick=\"...\\''...\"  """
    r = httpx.get(f"{API}/", timeout=5)
    js = _extract_js(r.text)
    for i, line in enumerate(js.split("\n"), 1):
        if "onclick" in line and "\\\\'" in line:
            raise AssertionError(f"Line {i}: escaped onclick — use data attributes: {line.strip()[:80]}")


def test_no_style_display_none_inline():
    """Inline style=display:none in template literals causes parsing issues."""
    r = httpx.get(f"{API}/", timeout=5)
    js = _extract_js(r.text)
    assert "style=display:none" not in js, "Inline style=display:none found — use .hidden class"


def test_template_literals_not_nested():
    """Nested template literals (`` `${...}` ``) are error-prone."""
    r = httpx.get(f"{API}/", timeout=5)
    js = _extract_js(r.text)
    for i, line in enumerate(js.split("\n"), 1):
        # Count backtick-openings per line — more than 2 is suspicious
        if line.count("`") > 4:
            raise AssertionError(f"Line {i}: too many backticks ({line.count('`')}) — possible nested template: {line.strip()[:80]}")


def test_all_functions_defined():
    """Verify key functions exist."""
    r = httpx.get(f"{API}/", timeout=5)
    js = _extract_js(r.text)
    required = [
        "function load(", "function renderFeatures(", "function renderWaves(",
        "function renderInspector(", "function selFeature(", "function selPacket(",
        "function connectWS(", "function swTab(", "function navBack(",
    ]
    for fn in required:
        assert fn in js, f"Missing function: {fn}"
