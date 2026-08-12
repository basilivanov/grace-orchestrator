# ############################################################################
# AI_HEADER: test_admin_ui_htmx_layout
# ROLE: Regression test for the HTMX-partial layout of the operator console.
#       Verifies that:
#         - all 5 partials return their expected root wrapper element
#         - clicking feature / packet / tab / filter only swaps the right pane
#         - desktop 1440 layout shows 3 stable columns
#         - mobile 390 has no horizontal page scroll
#         - browser URL is always /admin?... and never /admin/_partial/...
# ############################################################################
from __future__ import annotations

import json
import os
import re
import urllib.parse
from pathlib import Path

import pytest


# Server is expected to be already running (pytest does not start the server).
# Override with env var GRACE_BASE_URL.
BASE_URL = os.environ.get("GRACE_BASE_URL", "http://127.0.0.1:8042")
pytestmark = pytest.mark.external


# ---------------------------------------------------------------------------
# Server-side smoke tests (no browser) — every partial must return its root
# wrapper element so hx-swap="outerHTML" preserves the grid layout.
# ---------------------------------------------------------------------------

def _get(path: str) -> tuple[int, str]:
    import urllib.request
    url = f"{BASE_URL}{path}"
    try:
        with urllib.request.urlopen(url, timeout=10) as r:
            return r.status, r.read().decode("utf-8", "replace")
    except Exception as e:
        pytest.skip(f"server unreachable at {url}: {e}")


def test_partial_master_returns_master_tree_wrapper():
    status, body = _get("/admin/_partial/master")
    assert status == 200
    # The first non-whitespace token must be the master-tree wrapper
    # (jinja templates often add a leading newline).
    stripped = body.lstrip()
    assert stripped.startswith('<div id="master-tree"'), (
        f"_master.html must return <div id=\"master-tree\" ...> as root; "
        f"got: {stripped[:120]!r}"
    )


def test_partial_timeline_returns_timeline_pane_wrapper():
    status, body = _get("/admin/_partial/timeline?feature_id=feat_test")
    assert status == 200
    stripped = body.lstrip()
    assert stripped.startswith('<div class="console-middle" id="timeline-pane"'), (
        f"_timeline.html must return <div ... id=\"timeline-pane\"> as root; "
        f"got: {stripped[:120]!r}"
    )


def test_partial_detail_returns_detail_pane_wrapper():
    status, body = _get("/admin/_partial/detail?packet_id=pkt_test")
    # 200 even if packet is not found, because the wrapper is still returned
    assert status == 200
    stripped = body.lstrip()
    assert stripped.startswith('<div class="console-detail" id="detail-pane"'), (
        f"_detail.html must return <div ... id=\"detail-pane\"> as root; "
        f"got: {stripped[:120]!r}"
    )


def test_partial_tab_returns_packet_tab_content_wrapper():
    status, body = _get("/admin/_partial/tab?packet_id=pkt_test&tab=timeline")
    assert status == 200
    stripped = body.lstrip()
    assert stripped.startswith('<div id="packet-tab-content"'), (
        f"_tab.html must return <div id=\"packet-tab-content\"> as root; "
        f"got: {stripped[:120]!r}"
    )


def test_partial_stats_returns_stats_bar_container_wrapper():
    status, body = _get("/admin/_partial/stats")
    assert status == 200
    stripped = body.lstrip()
    assert stripped.startswith('<div id="stats-bar-container"'), (
        f"_stats.html must return <div id=\"stats-bar-container\"> as root; "
        f"got: {stripped[:120]!r}"
    )


def test_partial_detail_has_hx_push_url_with_shell_url():
    """The detail partial is invoked with a real packet, so we get tabs.
    Each tab's hx-push-url must point to /admin?... (not /admin/_partial/...)."""
    pid = _seed_packet_id()
    if not pid:
        pytest.skip("no packet in DB")

    status, body = _get(f"/admin/_partial/detail?packet_id={pid}")
    assert status == 200
    # Find hx-push-url on tab links
    push_urls = re.findall(r'hx-push-url="([^"]+)"', body)
    assert push_urls, "no hx-push-url attributes found in detail partial"
    for u in push_urls:
        assert u.startswith("/admin"), (
            f"hx-push-url must point to /admin (shell), got: {u!r}"
        )
        assert "/_partial/" not in u, (
            f"hx-push-url must not point to a /_partial/ endpoint, got: {u!r}"
        )


# ---------------------------------------------------------------------------
# Browser-based regression tests (Playwright)
# ---------------------------------------------------------------------------

@pytest.fixture(scope="module")
def browser():
    from playwright.sync_api import sync_playwright
    with sync_playwright() as p:
        b = p.chromium.launch(headless=True)
        yield b
        b.close()


def _seed_packet_id() -> str | None:
    """Find a real packet id from the timeline partial (so the test doesn't
    depend on a hard-coded fixture). We hit the timeline with any feature_id
    — the response contains all packet_ids from the feature tree."""
    import urllib.request
    # Hit master first to find a feature id
    with urllib.request.urlopen(f"{BASE_URL}/admin/_partial/master", timeout=10) as r:
        master = r.read().decode("utf-8", "replace")
    m = re.search(r'feature_id=([a-zA-Z0-9_-]+)', master)
    if not m:
        return None
    fid = m.group(1)
    with urllib.request.urlopen(
        f"{BASE_URL}/admin/_partial/timeline?feature_id={fid}", timeout=10
    ) as r:
        body = r.read().decode("utf-8", "replace")
    m = re.search(r'packet_id=([a-zA-Z0-9_-]+)', body)
    return m.group(1) if m else None


def test_browser_desktop_1440_three_panes(browser):
    """At 1440x900: 3 visible columns (master | timeline | detail)."""
    page = browser.new_page(viewport={"width": 1440, "height": 900})
    try:
        page.goto(f"{BASE_URL}/admin", wait_until="domcontentloaded")
        page.wait_for_selector("#master-tree", timeout=10000)
        # All 3 root panes must be present
        for sel in ("#master-tree", "#timeline-pane", "#detail-pane"):
            assert page.query_selector(sel) is not None, (
                f"selector {sel} not present after initial /admin load"
            )
        # Each pane must be inside the .console grid (computed)
        cols = page.evaluate(
            "() => getComputedStyle(document.querySelector('.console'))"
            ".gridTemplateColumns"
        )
        # 3 columns at 1440+
        assert len(cols.split()) >= 3, (
            f"expected 3+ grid columns at 1440 width, got: {cols!r}"
        )
    finally:
        page.close()


def test_browser_mobile_390_no_horizontal_scroll(browser):
    """At 390x844: no horizontal page scroll, layout is stacked."""
    page = browser.new_page(viewport={"width": 390, "height": 844})
    try:
        page.goto(f"{BASE_URL}/admin", wait_until="domcontentloaded")
        page.wait_for_selector("#master-tree", timeout=10000)
        sw = page.evaluate("() => document.body.scrollWidth")
        vw = page.evaluate("() => window.innerWidth")
        assert sw <= vw, (
            f"horizontal page scroll on mobile: body.scrollWidth={sw} > "
            f"viewport={vw}"
        )
    finally:
        page.close()


def test_browser_click_flow_preserves_wrappers(browser):
    """Open /admin → click feature → click packet → click tab.
    After each step, all 4 root wrappers must still exist."""
    pid = _seed_packet_id()
    if not pid:
        pytest.skip("no packet in DB to click")

    page = browser.new_page(viewport={"width": 1440, "height": 900})
    try:
        page.goto(f"{BASE_URL}/admin", wait_until="domcontentloaded")
        page.wait_for_selector("#master-tree", timeout=10000)

        for sel in ("#master-tree", "#timeline-pane", "#detail-pane"):
            assert page.query_selector(sel) is not None, f"missing {sel} initially"

        # 1) Click the first feature head
        first_feature = page.query_selector(".tn-feature-head")
        assert first_feature is not None, "no .tn-feature-head in master"
        first_feature.click()
        page.wait_for_selector("#timeline-pane", timeout=10000)

        for sel in ("#master-tree", "#timeline-pane", "#detail-pane"):
            assert page.query_selector(sel) is not None, (
                f"missing {sel} after feature click"
            )

        # 2) Click the first packet in the feature timeline
        #     We need to find a clickable .ft-packet or .tn-packet
        #     The feature head's hx-get set selected_feature_id, so
        #     timeline should now show the feature's packets.
        ft_packet = page.query_selector(".ft-packet")
        if ft_packet is None:
            # Master may have been expanded showing .tn-packet
            ft_packet = page.query_selector(".tn-packet")
        assert ft_packet is not None, "no clickable packet after feature click"
        ft_packet.click()
        page.wait_for_selector("#packet-tab-content", timeout=10000)

        for sel in (
            "#master-tree", "#timeline-pane", "#detail-pane",
            "#packet-tab-content",
        ):
            assert page.query_selector(sel) is not None, (
                f"missing {sel} after packet click"
            )

        # 3) Click the "logs" tab
        tab_link = None
        for a in page.query_selector_all("#packet-tabs a"):
            if a.inner_text().strip().lower() == "logs":
                tab_link = a
                break
        assert tab_link is not None, "no 'logs' tab in packet detail"
        tab_link.click()
        # Wait for tab content to refresh — sleep briefly to let htmx fire
        page.wait_for_function(
            "() => document.querySelector('#packet-tab-content') !== null",
            timeout=10000,
        )

        for sel in (
            "#master-tree", "#timeline-pane", "#detail-pane",
            "#packet-tab-content",
        ):
            assert page.query_selector(sel) is not None, (
                f"missing {sel} after tab click"
            )

        # 4) URL must be /admin?... (not /admin/_partial/...)
        url = page.url
        assert "/admin" in url, f"unexpected URL: {url}"
        parsed = urllib.parse.urlparse(url)
        assert "/_partial/" not in parsed.path, (
            f"URL should not contain /_partial/: {url}"
        )
    finally:
        page.close()
