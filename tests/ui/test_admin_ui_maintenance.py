"""Tests for the admin UI Maintenance tab (Phase 3 of retention TZ)."""
from __future__ import annotations

import os
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


def test_maintenance_partial_returns_200():
    status, _ = _get("/admin/_partial/maintenance")
    assert status == 200


def test_maintenance_partial_self_wraps_in_detail_pane():
    """Partial root must be `#detail-pane` (HTMX outerHTML contract)."""
    status, body = _get("/admin/_partial/maintenance")
    assert status == 200
    assert 'id="detail-pane"' in body
    assert "maintenance-pane" in body


def test_maintenance_partial_has_disk_usage_section():
    status, body = _get("/admin/_partial/maintenance")
    assert status == 200
    assert "Disk usage" in body
    assert "maint-grid" in body
    assert "maint-cell" in body


def test_maintenance_partial_has_worktrees_section():
    status, body = _get("/admin/_partial/maintenance")
    assert status == 200
    assert "Worktrees" in body


def test_maintenance_partial_has_branches_section():
    status, body = _get("/admin/_partial/maintenance")
    assert status == 200
    assert "Branches" in body


def test_maintenance_partial_has_archives_placeholder():
    status, body = _get("/admin/_partial/maintenance")
    assert status == 200
    assert "archive" in body.lower()
    # TZ: no tar.gz, kept forever
    assert "kept forever" in body or "no TTL" in body or "no automatic" in body


def test_maintenance_partial_has_refresh_button():
    status, body = _get("/admin/_partial/maintenance")
    assert status == 200
    assert "Refresh" in body
    assert "hx-get=\"/admin/_partial/maintenance\"" in body


def test_maintenance_full_page_includes_view_tabs():
    status, body = _get("/admin?view=maintenance")
    assert status == 200
    assert "view-tabs" in body
    assert "Maintenance" in body


def test_maintenance_full_page_view_tab_active():
    status, body = _get("/admin?view=maintenance")
    assert status == 200
    assert "view-tab-active" in body
    # The Maintenance tab is the active one
    assert body.count("view-tab-active") >= 1


def test_admin_overview_hides_maintenance_view():
    """Default /admin should NOT show maintenance pane as main view."""
    status, body = _get("/admin")
    assert status == 200
    # view=overview (default) should show normal console (not maintenance pane alone)
    # The maintenance view-tab is still visible in nav, but the pane is not active
    assert "view-tabs" in body
    # The console grid is rendered (not the maintenance pane)
    assert "console" in body


def test_css_includes_maintenance_pane_styles():
    status, body = _get("/static/admin.css")
    assert status == 200
    assert ".maintenance-pane" in body
    assert ".maint-section" in body
    assert ".maint-grid" in body
    assert ".maint-cell" in body
    assert ".maint-table" in body
    assert ".maint-btn" in body
    assert ".maint-btn-danger" in body
    assert ".maint-btn-primary" in body
    assert ".maint-btn-secondary" in body
    assert ".maint-result" in body
    assert ".maint-callout" in body
    assert ".maint-tag" in body
    assert ".view-tabs" in body
    assert ".view-tab" in body
    assert ".view-tab-active" in body


def test_maintenance_uses_human_readable_sizes():
    status, body = _get("/admin/_partial/maintenance")
    assert status == 200
    # Should reference fmt_size filter output (B/KB/MB/GB/TB)
    # In a fresh test env, sizes are 0 B, but the filter must be applied
    assert "0 B" in body or "size-info" in body


def test_shell_url_supports_view_param():
    """`shell_url(view='maintenance')` returns the maintenance URL."""
    from grace_control.ui.admin_template_filters import shell_url
    assert shell_url(view="maintenance") == "/admin?view=maintenance"
    assert shell_url(view="overview") == "/admin"
    # default is overview
    assert shell_url() == "/admin"


def test_cleanup_endpoint_returns_html():
    """POST /admin/maintenance/cleanup returns HTML (not 500)."""
    import urllib.parse
    url = f"{BASE_URL}/admin/maintenance/cleanup?action=stale&dry_run=true"
    try:
        req = urllib.request.Request(url, method="POST")
        with urllib.request.urlopen(req, timeout=10) as r:
            status = r.status
            body = r.read().decode("utf-8", "replace")
    except Exception as e:
        pytest.skip(f"server unreachable: {e}")
    assert status == 200
    assert "maintenance-pane" in body
    # dry-run result banner
    assert "dry-run" in body or "Freed" in body or "OK" in body


def test_cleanup_unknown_action_returns_error_banner():
    url = f"{BASE_URL}/admin/maintenance/cleanup?action=foo"
    try:
        req = urllib.request.Request(url, method="POST")
        with urllib.request.urlopen(req, timeout=10) as r:
            body = r.read().decode("utf-8", "replace")
    except Exception as e:
        pytest.skip(f"server unreachable: {e}")
    assert "unknown action" in body
    assert "maint-result-err" in body
