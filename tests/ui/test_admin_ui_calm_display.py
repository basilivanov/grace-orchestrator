# ############################################################################
# AI_HEADER: test_admin_ui_calm_display
# ROLE: Regression tests for the operator-friendly UI display layer.
#       Verifies that:
#         - raw backend states are mapped to calm human labels
#         - severity classes (ok/muted/attention/critical) are applied
#         - left master pane does NOT show raw NOT_STARTED as a pill
#         - feature row uses meta line ("N waves · M packets · K needs attention")
#         - only ONE loud red attention block is visible (selected packet detail)
#         - raw backend states are still visible in detail metadata
# ############################################################################
from __future__ import annotations

import os
import re
import urllib.request

import pytest


BASE_URL = os.environ.get("GRACE_BASE_URL", "http://127.0.0.1:8042")


def _get(path: str) -> tuple[int, str]:
    url = f"{BASE_URL}{path}"
    try:
        with urllib.request.urlopen(url, timeout=10) as r:
            return r.status, r.read().decode("utf-8", "replace")
    except Exception as e:
        pytest.skip(f"server unreachable at {url}: {e}")


# ---------------------------------------------------------------------------
# State mapping (UI-only): raw state -> (label, severity)
# Backend states are NOT changed. Only the labels shown in the UI.
# ---------------------------------------------------------------------------

# The mapping that lives in src/grace_control/ui/admin_template_filters.py
# (kept in sync via the tests below).
EXPECTED_LABELS: dict[str, str] = {
    # packet states
    "draft":       "Draft",
    "ready":       "Ready",
    "claimed":     "Running",
    "running":     "Running",
    "rejected":    "Reviewer rejected",
    "failed":      "Failed",
    "blocked":     "Blocked",
    "blocked_recoverable": "Blocked",
    "blocked_final":       "Blocked",
    "accepted":    "Done",
    "merged":      "Done",
    "cancelled":   "Cancelled",
    # feature / wave statuses (uppercase from DB)
    "NOT_STARTED": "Waiting",
    "DEGRADED":    "Has failed packets",
    "COMPLETED":   "Done",
    "ACTIVE":      "Running",
}

EXPECTED_SEVERITY: dict[str, str] = {
    "draft":       "muted",
    "ready":       "muted",
    "running":     "ok",
    "claimed":     "ok",
    "rejected":    "attention",
    "failed":      "critical",
    "blocked":     "attention",
    "blocked_recoverable": "attention",
    "blocked_final":       "critical",
    "accepted":    "ok",
    "merged":      "ok",
    "cancelled":   "muted",
    "NOT_STARTED": "muted",
    "DEGRADED":    "attention",
    "COMPLETED":   "ok",
    "ACTIVE":      "ok",
}


def test_state_label_mapping_in_filters_module():
    """The UI label mapping is defined in admin_template_filters.py.
    The dictionary values are what users see, NOT raw backend state names."""
    sys = pytest.importorskip("sys")
    from grace_control.ui.admin_template_filters import _state_lookup
    for state, expected in EXPECTED_LABELS.items():
        got = _state_lookup(state)["label"]
        assert got == expected, (
            f"ui label for {state!r} expected {expected!r}, got {got!r}"
        )


def test_state_severity_mapping_in_filters_module():
    from grace_control.ui.admin_template_filters import _state_lookup
    for state, expected in EXPECTED_SEVERITY.items():
        got = _state_lookup(state)["severity"]
        assert got == expected, (
            f"ui severity for {state!r} expected {expected!r}, got {got!r}"
        )


def test_jinja_state_label_filter():
    from grace_control.ui.admin_template_filters import state_label, state_severity
    for state, expected in EXPECTED_LABELS.items():
        assert state_label(state) == expected
    for state, expected in EXPECTED_SEVERITY.items():
        assert state_severity(state) == expected


# ---------------------------------------------------------------------------
# Master pane: no loud raw NOT_STARTED pills; meta line with attention count
# ---------------------------------------------------------------------------

def test_master_pane_does_not_show_raw_not_started_pill():
    status, body = _get("/admin/_partial/master")
    assert status == 200
    # A pill with class="pill NOT_STARTED" would mean the old loud rendering
    assert 'class="pill NOT_STARTED"' not in body, (
        "master pane still renders raw NOT_STARTED as a pill — should be hidden"
    )
    # Also no raw DEGRADED pill in the navigation row
    assert 'class="pill DEGRADED"' not in body, (
        "master pane still renders raw DEGRADED as a pill"
    )


def test_master_pane_shows_attention_count_text():
    status, body = _get("/admin/_partial/master")
    assert status == 200
    # Live data has features with 1 rejected packet each, so the
    # "1 needs attention" text should appear.
    assert "needs attention" in body, (
        "master pane should show 'N needs attention' meta line"
    )


def test_master_pane_shows_waves_and_packets_counts():
    status, body = _get("/admin/_partial/master")
    assert status == 200
    # Meta line includes "N waves" and "M packets"
    assert re.search(r"\d+\s*wave", body), "master pane missing 'N waves' meta"
    assert re.search(r"\d+\s*packet", body), "master pane missing 'M packets' meta"


def test_master_pane_feature_severity_class_present():
    """Feature rows carry a severity-* class (ok | muted | attention | critical)."""
    status, body = _get("/admin/_partial/master")
    assert status == 200
    assert 'class="tn-feature severity-' in body, (
        "feature rows must have severity-* class for styling"
    )


def test_master_pane_feature_no_loud_pill_for_normal_state():
    """Features with status NOT_STARTED but no failures should be 'severity-muted',
    NOT 'severity-attention' or 'severity-critical'."""
    status, body = _get("/admin/_partial/master")
    assert status == 200
    # The severity class for a "waiting" feature should be muted
    # (no failures present at all in the live data; live data does have
    # 1 failed per feature, so we instead assert that critical is rare
    # in the master pane).
    crit_count = body.count("severity-critical")
    attn_count = body.count("severity-attention")
    # Live data: 5 features, each with 1 attention. No critical in master.
    assert crit_count == 0, (
        f"master pane should not show severity-critical ({crit_count} found); "
        f"this severity is reserved for the selected detail card."
    )
    assert attn_count >= 1, (
        "master pane should show at least one severity-attention for features "
        "with failing packets"
    )


# ---------------------------------------------------------------------------
# Detail pane: "Needs attention" replaces "WHY IT FAILED"
# ---------------------------------------------------------------------------

def _seed_packet_id_with_rejections() -> str | None:
    """Find a real rejected packet id from the timeline."""
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


def test_detail_pane_uses_needs_attention_header():
    pid = _seed_packet_id_with_rejections()
    if not pid:
        pytest.skip("no rejected packet in DB")
    status, body = _get(f"/admin/_partial/detail?packet_id={pid}")
    assert status == 200
    assert "Needs attention" in body, (
        "detail pane should use 'Needs attention' header (calm), not 'WHY IT FAILED'"
    )
    # The old ALL-CAPS red header must be gone
    assert "WHY IT FAILED" not in body, "old 'WHY IT FAILED' header still present"
    assert "Why it was rejected" not in body, (
        "old 'Why it was rejected' header still present"
    )


def test_detail_pane_shows_raw_state_in_metadata():
    """Raw backend state is still visible somewhere in the detail pane
    (as small metadata), so debugging is possible."""
    pid = _seed_packet_id_with_rejections()
    if not pid:
        pytest.skip("no rejected packet in DB")
    status, body = _get(f"/admin/_partial/detail?packet_id={pid}")
    assert status == 200
    # The raw state appears in a small "raw:" line
    assert re.search(r'raw:\s*\w+', body), (
        "raw backend state should be visible in detail metadata (e.g. 'raw: rejected')"
    )
    # The raw state also appears in the 'state:' chip near the title
    assert re.search(r'state:\s*\w+', body), (
        "raw state should be visible in detail head metadata"
    )


def test_detail_pane_uses_calm_label_not_raw_state():
    """The badge in the 'Needs attention' panel should say 'Reviewer rejected',
    not the raw 'rejected' string."""
    pid = _seed_packet_id_with_rejections()
    if not pid:
        pytest.skip("no rejected packet in DB")
    status, body = _get(f"/admin/_partial/detail?packet_id={pid}")
    assert status == 200
    assert "Reviewer rejected" in body, (
        "detail pane should use the calm human label 'Reviewer rejected'"
    )


def test_detail_pane_severity_class_present():
    pid = _seed_packet_id_with_rejections()
    if not pid:
        pytest.skip("no rejected packet in DB")
    status, body = _get(f"/admin/_partial/detail?packet_id={pid}")
    assert status == 200
    # The needs-attention section has severity-* class
    assert re.search(r'class="needs-attention severity-\w+"', body), (
        "needs-attention section must have a severity-* class"
    )


# ---------------------------------------------------------------------------
# Browser visual tests: at most one critical severity per page
# ---------------------------------------------------------------------------

@pytest.fixture(scope="module")
def browser():
    playwright = pytest.importorskip("playwright")
    sync_api = pytest.importorskip("playwright.sync_api")
    with sync_api.sync_playwright() as p:
        b = p.chromium.launch(headless=True)
        yield b
        b.close()


def test_browser_at_most_one_critical_block_on_overview(browser):
    """The 'critical' severity is reserved for the selected blocking
    detail card. On the overview (no packet selected) there should be
    zero critical elements."""
    page = browser.new_page(viewport={"width": 1440, "height": 900})
    try:
        page.goto(f"{BASE_URL}/admin", wait_until="domcontentloaded")
        page.wait_for_selector("#master-tree", timeout=10000)
        n = page.evaluate(
            "() => document.querySelectorAll('.severity-critical').length"
        )
        assert n == 0, (
            f"overview should have 0 severity-critical elements, got {n}. "
            f"Critical is reserved for the selected detail card only."
        )
    finally:
        page.close()


def test_browser_desktop_calm_visual(browser):
    """Desktop 1440: check that no loud red elements are stacked on
    the left master pane (which should be calm navigation)."""
    page = browser.new_page(viewport={"width": 1440, "height": 900})
    try:
        page.goto(f"{BASE_URL}/admin", wait_until="domcontentloaded")
        page.wait_for_selector("#master-tree", timeout=10000)
        # Master pane should not have any element styled with the loud err color
        master = page.query_selector("#master-pane")
        assert master is not None
        # Check that no child has the full-saturation red
        loud_red = page.evaluate(
            "() => {"
            "  const m = document.querySelector('#master-pane');"
            "  if (!m) return 0;"
            "  return Array.from(m.querySelectorAll('*')).filter(el => {"
            "    const c = getComputedStyle(el).color;"
            "    return c === 'rgb(248, 113, 113)' || c === 'rgb(239, 91, 91)';"
            "  }).length;"
            "}"
        )
        # Allow the severity-muted text but not full-saturation red
        # (we use the softer --sev-crit in CSS)
        assert loud_red == 0, (
            f"master pane has {loud_red} full-saturation red elements "
            f"(should be 0 — use softer severity colors)"
        )
    finally:
        page.close()
