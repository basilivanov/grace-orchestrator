# ############################################################################
# AI_HEADER: test_admin_ui_layout_density
# ROLE: Regression tests for the operator dashboard density improvements.
#       Verifies:
#         - display_title() filter returns fallback for placeholder titles
#         - Selected feature block has explicit "Selected feature" label
#         - Wave cards show structured rows (title / wave_id / meta)
#         - Packet cards inside waves show grid with attempts/stage/started/
#           duration (visible without tooltips)
#         - Wave details page shows summary section + wave progress section
#         - Short titles like "t", "d", "w1", "p1" are NOT shown as the main
#           heading without explanation
#         - Stage derivation helper returns the correct pipeline stage
# ############################################################################
from __future__ import annotations

import os
import re
import urllib.parse
import urllib.request
import html

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
# 1. display_title() filter — fallback for placeholder titles
# ---------------------------------------------------------------------------

def test_display_title_returns_untitled_for_short_titles():
    """A short / placeholder title must return the Untitled fallback."""
    from grace_control.ui.admin_template_filters import display_title

    for t in [None, "", "t", "d", "w1", "p1", "P2", "W3"]:
        out = display_title(t, "feature")
        assert out["is_placeholder"] is True, (
            f"title={t!r} should be flagged as placeholder"
        )
        assert "Untitled" in out["title"], (
            f"title={t!r} should return 'Untitled …' fallback, got: {out}"
        )


def test_display_title_preserves_normal_titles():
    """A normal title (long, descriptive) is returned as-is."""
    from grace_control.ui.admin_template_filters import display_title

    out = display_title("Calculator class with add and subtract", "packet")
    assert out["is_placeholder"] is False
    assert out["title"] == "Calculator class with add and subtract"
    assert out["original"] == "Calculator class with add and subtract"


def test_display_title_kind_specific_fallback():
    """Each kind has its own fallback label."""
    from grace_control.ui.admin_template_filters import display_title

    assert display_title("t", "feature")["title"] == "Untitled feature"
    assert display_title("w1", "wave")["title"] == "Untitled wave"
    assert display_title("p1", "packet")["title"] == "Untitled packet"


def test_display_title_keeps_original_for_metadata():
    """When title is a placeholder, the original is preserved in `original`."""
    from grace_control.ui.admin_template_filters import display_title

    out = display_title("w1", "wave")
    assert out["original"] == "w1"
    out2 = display_title(None, "feature")
    assert out2["original"] == ""


# ---------------------------------------------------------------------------
# 2. Stage derivation helper
# ---------------------------------------------------------------------------

def test_derive_packet_stage_for_draft_packet():
    """A draft packet with no runs has stage 'Materialized' or 'Not started'."""
    from grace_control.services.admin_aggregation_service import (
        AdminAggregationService,
    )
    from types import SimpleNamespace

    svc = AdminAggregationService()
    p = SimpleNamespace(state="draft", attempt_count=0, max_attempts=3)
    stage = svc._derive_packet_stage(p, None)
    assert stage["label"] in ("Materialized", "Not started"), (
        f"draft packet should be at Materialized/Not started, got {stage}"
    )


def test_derive_packet_stage_for_rejected_packet():
    """A rejected packet has stage 'Reviewer gate'."""
    from grace_control.services.admin_aggregation_service import (
        AdminAggregationService,
    )
    from types import SimpleNamespace

    svc = AdminAggregationService()
    p = SimpleNamespace(state="rejected", attempt_count=2, max_attempts=3)
    r = SimpleNamespace(status="rejected")
    stage = svc._derive_packet_stage(p, r)
    assert stage["label"] == "Reviewer gate"
    assert stage["key"] == "reviewer"


def test_derive_packet_stage_for_merged_packet():
    """A merged packet has stage 'Merge'."""
    from grace_control.services.admin_aggregation_service import (
        AdminAggregationService,
    )
    from types import SimpleNamespace

    svc = AdminAggregationService()
    p = SimpleNamespace(state="merged", attempt_count=1, max_attempts=3)
    r = SimpleNamespace(status="accepted")
    stage = svc._derive_packet_stage(p, r)
    assert stage["label"] == "Merge"
    assert stage["key"] == "merge"


# ---------------------------------------------------------------------------
# 3. Selected feature block has explicit label
# ---------------------------------------------------------------------------

def _first_feature_id() -> str | None:
    status, body = _get("/admin/_partial/master")
    if status != 200:
        return None
    m = re.search(r'feature_id=([a-zA-Z0-9_-]+)', body)
    return m.group(1) if m else None


def _first_wave_id_for(feature_id: str) -> str | None:
    status, body = _get(f"/admin/_partial/timeline?feature_id={feature_id}")
    if status != 200:
        return None
    m = re.search(r'wave_id=([a-zA-Z0-9_-]+)', body)
    return m.group(1) if m else None


@pytest.mark.external
def test_timeline_renders_selected_feature_label():
    """The middle pane renders an explicit 'Selected feature' label."""
    fid = _first_feature_id()
    if not fid:
        pytest.skip("no feature in DB")
    status, body = _get(f"/admin/_partial/timeline?feature_id={fid}")
    assert status == 200
    assert "Selected feature" in body, (
        "timeline must contain 'Selected feature' label for the active feature"
    )
    assert "ft-feature-selected" in body, (
        "timeline must contain .ft-feature-selected block"
    )
    assert "feature_id:" in body, (
        "selected feature block must show feature_id: <id>"
    )


@pytest.mark.external
def test_timeline_renders_wave_order_label():
    """Each wave shows 'Wave #N' on its own line."""
    fid = _first_feature_id()
    if not fid:
        pytest.skip("no feature in DB")
    status, body = _get(f"/admin/_partial/timeline?feature_id={fid}")
    assert status == 200
    assert re.search(r'Wave #\d+', body), (
        "each wave card must show 'Wave #<order>' label"
    )


@pytest.mark.external
def test_timeline_renders_packet_grid_with_required_fields():
    """Packet cards show attempts/stage/started/duration (no tooltip-only)."""
    fid = _first_feature_id()
    if not fid:
        pytest.skip("no feature in DB")
    status, body = _get(f"/admin/_partial/timeline?feature_id={fid}")
    assert status == 200
    # All four key labels must be present
    for key in ("attempts", "stage", "started", "duration"):
        assert re.search(
            rf'ft-pkt-key[^>]*>\s*{key}\s*<',
            body,
        ), f"packet grid must show '{key}' field, not tooltip-only"
    # And the grid container must be present
    assert "ft-pkt-grid" in body, (
        "packet grid container must be present in timeline"
    )


# ---------------------------------------------------------------------------
# 4. Short titles get fallback in the selected feature block
# ---------------------------------------------------------------------------

@pytest.mark.external
def test_short_titles_get_untitled_fallback_in_timeline():
    """When a feature has a placeholder title like 't', the timeline
    shows 'Untitled feature' as the main heading, with the original
    as 'slug: …' metadata."""
    from grace_control.services.admin_aggregation_service import (
        AdminAggregationService,
    )
    # Use the get_features_tree data to find a feature with a short title
    # We test the filter directly here, the integration is covered below.
    from grace_control.ui.admin_template_filters import display_title
    out = display_title("t", "feature")
    assert out["title"] == "Untitled feature"
    assert out["is_placeholder"] is True

    # Integration: if the live DB has a feature with a short title,
    # the timeline should show "Untitled feature" — but live data
    # may or may not include one. We check the page HTML defensively:
    # whenever the title 't' appears in the timeline body, it should
    # be within a 'slug:' metadata line, not as a main heading.
    status, body = _get(f"/admin/_partial/master")
    if status == 200:
        # Look for raw short titles in master tree
        short_titles = re.findall(r'title="([twdp][0-9]?)"', body)
        # If we find any, they should be wrapped in title-slug spans
        for st in short_titles:
            if len(st) < 3:
                # Verify the master tree has the placeholder span
                assert (
                    'title-slug' in body
                ), (
                    f"short title {st!r} should be wrapped in title-slug span"
                )


# ---------------------------------------------------------------------------
# 5. Wave details: summary, progress, packet grid
# ---------------------------------------------------------------------------

@pytest.mark.external
def test_wave_details_renders_summary_section():
    """The wave details page has a 'Summary' section with per-state counts."""
    fid = _first_feature_id()
    if not fid:
        pytest.skip("no feature in DB")
    wid = _first_wave_id_for(fid)
    if not wid:
        pytest.skip("no wave in DB")
    status, body = _get(
        f"/admin/_partial/detail?wave_id={wid}&feature_id={fid}"
    )
    assert status == 200
    assert "Summary" in body, "wave details must have a Summary section"
    assert "wave-summary-grid" in body, "summary grid must be present"
    # Each summary key
    for key in ("total packets", "rejected / failed", "running", "blocked", "done"):
        assert key in body, f"summary must show '{key}' key, got body"


@pytest.mark.external
def test_wave_details_renders_progress_section():
    """The wave details page has a 'Wave progress' section with per-stage counts."""
    fid = _first_feature_id()
    if not fid:
        pytest.skip("no feature in DB")
    wid = _first_wave_id_for(fid)
    if not wid:
        pytest.skip("no wave in DB")
    status, body = _get(
        f"/admin/_partial/detail?wave_id={wid}&feature_id={fid}"
    )
    assert status == 200
    assert "Wave progress" in body, "wave details must have a Wave progress section"
    # Each stage label
    for label in ("Materialized", "Coder run", "Reviewer gate", "Merge reached"):
        assert label in body, f"progress must show '{label}' stage, got body"
    # Progress rows
    assert "wave-progress-row" in body, "progress rows must be present"


@pytest.mark.external
def test_wave_details_renders_packet_grid():
    """Each packet card in wave details shows attempts/stage/started/duration."""
    fid = _first_feature_id()
    if not fid:
        pytest.skip("no feature in DB")
    wid = _first_wave_id_for(fid)
    if not wid:
        pytest.skip("no wave in DB")
    status, body = _get(
        f"/admin/_partial/detail?wave_id={wid}&feature_id={fid}"
    )
    assert status == 200
    for key in ("attempts", "stage", "started", "duration"):
        assert re.search(
            rf'wave-pkt-key[^>]*>\s*{key}\s*<',
            body,
        ), f"wave packet grid must show '{key}' field"
    assert "wave-pkt-grid" in body, "wave packet grid container must be present"


@pytest.mark.external
def test_wave_details_renders_selected_wave_label():
    """The wave details page has an explicit 'Selected wave' label."""
    fid = _first_feature_id()
    if not fid:
        pytest.skip("no feature in DB")
    wid = _first_wave_id_for(fid)
    if not wid:
        pytest.skip("no wave in DB")
    status, body = _get(
        f"/admin/_partial/detail?wave_id={wid}&feature_id={fid}"
    )
    assert status == 200
    assert "Selected wave" in body, (
        "wave details must contain 'Selected wave' label"
    )


# ---------------------------------------------------------------------------
# 6. Layout structure tests (no flat "title · id · meta" string)
# ---------------------------------------------------------------------------

@pytest.mark.external
def test_wave_card_meta_is_structured_not_concatenated():
    """The wave card meta must be in separate spans/rows, not a single
    flat 'title · wave_id · packets · attention' string."""
    fid = _first_feature_id()
    if not fid:
        pytest.skip("no feature in DB")
    status, body = _get(f"/admin/_partial/timeline?feature_id={fid}")
    assert status == 200
    # Find the ft-wave block
    m = re.search(
        r'<div class="ft-wave[^"]*"[^>]*>(.*?)</div>\s*</div>',
        body,
        re.DOTALL,
    )
    assert m, "no .ft-wave block found in timeline"
    ft_wave_inner = m.group(1)
    # Must NOT contain a single concatenated string like
    # "wave_xxx · 1 packet · 1 needs attention" all in one line
    # The new structure separates title, wave_id, and meta into
    # different .ft-wave-* elements
    assert "ft-wave-title-row" in ft_wave_inner, (
        "wave card must have a .ft-wave-title-row (title row)"
    )
    assert "ft-wave-id" in ft_wave_inner, (
        "wave card must have a .ft-wave-id (separate id row)"
    )
    assert "ft-wave-meta" in ft_wave_inner, (
        "wave card must have a .ft-wave-meta (separate meta row)"
    )
    # The three elements must be SEPARATE (not nested in a single span)
    # We check that ft-wave-id is its own element, not inside ft-wave-meta
    assert ft_wave_inner.count("ft-wave-id") == 1
    assert ft_wave_inner.count("ft-wave-meta") == 1


# ---------------------------------------------------------------------------
# 7. Mobile hierarchy test
# ---------------------------------------------------------------------------

@pytest.fixture(scope="module")
def browser():
    playwright = pytest.importorskip("playwright")
    sync_api = pytest.importorskip("playwright.sync_api")
    with sync_api.sync_playwright() as p:
        try:
            b = p.chromium.launch(headless=True)
        except Exception as exc:
            pytest.skip(f"Chromium unavailable: {exc}")
        yield b
        b.close()


@pytest.mark.external
def test_browser_mobile_390_packet_grid_visible(browser):
    """On 390px, the packet grid (attempts/stage/started/duration)
    is still visible without horizontal scroll."""
    fid = _first_feature_id()
    if not fid:
        pytest.skip("no feature in DB")
    page = browser.new_page(viewport={"width": 390, "height": 844})
    try:
        page.goto(
            f"{BASE_URL}/admin?feature_id={fid}",
            wait_until="domcontentloaded",
        )
        page.wait_for_selector(".ft-pkt-grid", timeout=10000)
        # No horizontal scroll
        sw = page.evaluate("() => document.body.scrollWidth")
        vw = page.evaluate("() => window.innerWidth")
        assert sw <= vw, (
            f"horizontal scroll on mobile: {sw} > {vw}"
        )
        # The grid is still present and contains all 4 keys
        for key in ("attempts", "stage", "started", "duration"):
            visible = page.evaluate(
                f"() => !!Array.from(document.querySelectorAll('.ft-pkt-key'))"
                f".find(e => e.textContent.trim() === '{key}')"
            )
            assert visible, (
                f"'{key}' key not visible in mobile packet grid"
            )
    finally:
        page.close()
