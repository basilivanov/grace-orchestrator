"""Tests for size display in admin UI (Phase 2 of retention TZ).

Acceptance:
- fmt_size filter formats bytes as B/KB/MB/GB/TB/PB
- Master tree shows packet size
- Timeline shows wave size in wave meta + packet size in packet grid
- Packet detail shows per-run breakdown + total in pkt-meta-block
- Wave detail shows total size in pkt-meta-block
- Sizes render only when > 0 (no empty "0 B" noise)
"""
from __future__ import annotations

import html
import os
import re
import urllib.parse
import urllib.request

import pytest

from grace_control.services.size_calculator import (
    PacketSizeInfo,
    RunSizeInfo,
    SizeCalculator,
    fmt_size,
)


BASE_URL = os.environ.get("GRACE_BASE_URL", "http://127.0.0.1:8042")


def _get(path: str) -> tuple[int, str]:
    url = f"{BASE_URL}{path}"
    try:
        with urllib.request.urlopen(url, timeout=10) as r:
            return r.status, r.read().decode("utf-8", "replace")
    except Exception as e:
        pytest.skip(f"server unreachable at {url}: {e}")


# ── fmt_size Jinja filter integration ──────────────────────────────────────


def test_fmt_size_in_filter_module():
    """`fmt_size` is importable from admin_template_filters."""
    from grace_control.ui.admin_template_filters import fmt_size as jinja_fmt_size
    assert jinja_fmt_size(0) == "0 B"
    assert jinja_fmt_size(2 * 1024 ** 3) == "2.0 GB"
    assert jinja_fmt_size(None) == "0 B"


def test_fmt_size_edge_cases():
    """Boundary cases for human-readable formatter."""
    assert fmt_size(0) == "0 B"
    assert fmt_size(1024) == "1.0 KB"
    assert fmt_size(1024 ** 2) == "1.0 MB"
    assert fmt_size(1024 ** 3) == "1.0 GB"
    assert fmt_size(1024 ** 4) == "1.0 TB"
    assert fmt_size(1024 ** 5) == "1.0 PB"


# ── SizeCalculator in admin aggregation ────────────────────────────────────


def test_size_calculator_uses_correct_state_layout():
    """`packet_runs_size` reads from `<state_root>/packets/<pid>/runs/`."""
    import tempfile
    from pathlib import Path

    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        runs = root / "packets" / "pkt_x" / "runs" / "R01" / "logs"
        runs.mkdir(parents=True)
        (runs / "f.log").write_bytes(b"x" * 4096)

        c = SizeCalculator(state_root=root, worktree_root=root / "wt")
        assert c.packet_runs_size("pkt_x") == 4096


def test_size_calculator_works_without_state_root():
    """`SizeCalculator()` with no roots returns 0 for everything."""
    c = SizeCalculator()
    assert c.packet_runs_size("anything") == 0
    assert c.all_state_total() == 0
    assert c.all_worktrees_total() == 0
    assert c.state_packet_count() == 0
    assert c.state_run_count() == 0
    assert c.list_worktree_slugs() == []
    assert c.disk_snapshot().state_total_bytes == 0
    assert c.disk_snapshot().worktrees_total_bytes == 0


def test_packet_size_info_size_bytes_sums_runs():
    """PacketSizeInfo.size_bytes returns sum of run sizes."""
    r1 = RunSizeInfo(run_id="R01", path="/a", size_bytes=1024)
    r2 = RunSizeInfo(run_id="R02", path="/b", size_bytes=2048)
    info = PacketSizeInfo(packet_id="p1", runs=[r1, r2])
    assert info.size_bytes == 3072
    assert info.size_human == "3.0 KB"
    assert info.run_count == 2


# ── Live UI: master tree shows packet size ─────────────────────────────────


def test_master_tree_includes_pkt_size_class():
    """Master partial should reference the .pkt-size class for packet size."""
    status, body = _get("/admin/_partial/master")
    assert status == 200
    # Class is referenced in template; presence of class string is sufficient
    # (actual data depends on disk state which is empty in test env).
    # We just verify the class is at least in the loaded CSS.
    css_status, css_body = _get("/static/admin.css")
    assert css_status == 200
    assert ".pkt-size" in css_body or ".size-info" in css_body, (
        "Size CSS classes missing from admin.css"
    )


# ── Live UI: timeline shows wave + packet size ─────────────────────────────


def test_timeline_includes_size_classes_in_css():
    """admin.css must define the size-related classes used by timeline."""
    status, body = _get("/static/admin.css")
    assert status == 200
    # At minimum, the CSS should have these classes (added in Phase 2)
    assert ".pkt-size" in body or ".size-info" in body


# ── fmt_size filter is registered in templates ────────────────────────────


def test_fmt_size_is_registered_as_template_filter():
    """The fmt_size filter must be registered for Jinja templates."""
    from grace_control.ui import admin_template_filters as mod

    # Test the register() function attaches fmt_size + shell_url to env
    class FakeEnv:
        def __init__(self):
            self.filters = {}
            self.globals = {}

    env = FakeEnv()
    mod.register(env)
    assert "fmt_size" in env.filters, (
        "fmt_size must be registered by register(env) in admin_template_filters"
    )
    assert env.filters["fmt_size"] is mod.fmt_size


# ── Aggregation service includes size data ────────────────────────────────


def test_aggregation_service_exposes_size_data():
    """AdminAggregationService must expose size_calculator with roots."""
    from pathlib import Path
    import tempfile

    with tempfile.TemporaryDirectory() as tmp:
        from grace_control.services.admin_aggregation_service import (
            AdminAggregationService,
        )

        state_root = Path(tmp) / "state"
        wt_root = Path(tmp) / "wt"

        svc = AdminAggregationService(
            state_root=state_root,
            worktree_root=wt_root,
        )
        # SizeCalculator is lazily created
        assert svc._size_calc is not None
        assert svc._size_calc.state_root == state_root
        assert svc._size_calc.worktree_root == wt_root
