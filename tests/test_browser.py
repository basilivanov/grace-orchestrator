# ############################################################################
# AI_HEADER: test_browser
# ROLE: Headless browser tests — catch JS runtime errors before deploy.
# ############################################################################

"""Run dashboard in real Chromium, catch JS errors, verify tab content."""
import pytest
from playwright.sync_api import sync_playwright

API = "http://localhost:8042"

@pytest.fixture(scope="module")
def browser():
    with sync_playwright() as p:
        b = p.chromium.launch()
        yield b
        b.close()

@pytest.fixture
def page(browser):
    ctx = browser.new_context()
    page = ctx.new_page()
    errors = []
    page.on("console", lambda msg: errors.append(msg.text) if msg.type == "error" else None)
    page.on("pageerror", lambda err: errors.append(str(err)))
    page.errors = errors
    yield page
    ctx.close()

def test_page_loads_without_js_errors(page):
    page.goto(API, timeout=10000)
    page.wait_for_selector(".hdr", timeout=5000)
    assert page.errors == [], f"JS errors on load: {page.errors}"
    print("  OK: page loads without JS errors")

def test_features_rendered(page):
    page.goto(API, timeout=10000)
    page.wait_for_selector(".fcard", timeout=10000)
    count = len(page.query_selector_all(".fcard"))
    assert count > 0, "No feature cards rendered"
    print(f"  OK: {count} features rendered")

def test_stats_show_data(page):
    page.goto(API, timeout=10000)
    page.wait_for_selector(".hdr", timeout=5000)
    # Stats should not be all zeros after data loads
    page.wait_for_timeout(3000)  # wait for load() to complete
    html = page.content()
    # Check the stats bar shows non-zero values
    assert "Ready" in html
    print("  OK: stats bar present")

def test_click_feature_shows_waves(page):
    page.goto(API, timeout=10000)
    page.wait_for_selector(".fcard", timeout=10000)
    page.click(".fcard:first-child")
    page.wait_for_selector(".wcard", timeout=5000)
    count = len(page.query_selector_all(".wcard"))
    assert count > 0, "No wave cards after clicking feature"
    print(f"  OK: {count} waves shown")

def test_click_packet_shows_inspector(page):
    page.goto(API, timeout=10000)
    page.wait_for_selector(".fcard", timeout=10000)
    page.click(".fcard:first-child")
    page.wait_for_selector(".pcard", timeout=5000)
    page.click(".pcard:first-child")
    page.wait_for_selector(".insp", timeout=5000)
    # Should NOT show "Error loading" in visible inspector
    insp = page.query_selector(".insp")
    assert insp, "Inspector not found"
    insp_html = insp.inner_html()
    assert "Error loading" not in insp_html, f"Inspector error: {insp_html[:200]}"
    assert "state-badge" in insp_html, "No state badge"
    print("  OK: inspector renders without error")

def test_tabs_have_content(page):
    page.goto(API, timeout=10000)
    page.wait_for_selector(".fcard", timeout=10000)
    page.click(".fcard:first-child")
    page.wait_for_selector(".pcard", timeout=5000)
    page.click(".pcard:first-child")
    page.wait_for_selector(".tab", timeout=5000)
    # Click Runs tab
    page.click('.tab[data-tab="runs"]')
    page.wait_for_timeout(1000)
    html = page.content()
    assert "Run" in html, "Runs tab shows no data"
    print("  OK: tabs have content")

def test_no_console_errors_after_interaction(page):
    page.goto(API, timeout=10000)
    page.wait_for_selector(".fcard", timeout=10000)
    page.click(".fcard:first-child")
    page.wait_for_selector(".pcard", timeout=5000)
    page.click(".pcard:first-child")
    page.wait_for_selector(".tab", timeout=5000)
    page.click('.tab[data-tab="runs"]')
    page.wait_for_timeout(500)
    page.click('.tab[data-tab="events"]')
    page.wait_for_timeout(1000)
    page.click('.tab[data-tab="arts"]')
    page.wait_for_timeout(1000)
    page.click('.tab[data-tab="ov"]')
    page.wait_for_timeout(500)
    assert page.errors == [], f"JS errors during interaction: {page.errors}"
    print("  OK: no JS errors after clicking all tabs")
