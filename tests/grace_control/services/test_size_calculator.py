"""Tests for SizeCalculator + fmt_size.

TZ_RETENTION_POLICY.md Phase 2 acceptance:
- Sizes shown in human-readable everywhere
- Total size for: per-file, per-run, per-packet, per-wave, per-folder (worktree/state/branches)
- Format: B/KB/MB/GB/TB/PB
"""
from __future__ import annotations

import json
import os
import tempfile
import threading
from pathlib import Path

import pytest

from grace_control.services.size_calculator import (
    DiskSnapshot,
    PacketSizeInfo,
    RunSizeInfo,
    SizeCalculator,
    fmt_size,
)


# ── fmt_size unit tests ────────────────────────────────────────────────────


class TestFmtSize:
    """fmt_size: format byte count as B/KB/MB/GB/TB/PB."""

    def test_zero(self):
        assert fmt_size(0) == "0 B"

    def test_none(self):
        assert fmt_size(None) == "0 B"

    def test_negative(self):
        assert fmt_size(-2048) == "-2.0 KB"

    def test_bytes(self):
        assert fmt_size(1) == "1 B"
        assert fmt_size(512) == "512 B"
        assert fmt_size(1023) == "1023 B"

    def test_kb_boundary(self):
        assert fmt_size(1024) == "1.0 KB"
        assert fmt_size(1536) == "1.5 KB"

    def test_mb_boundary(self):
        assert fmt_size(1024 * 1024) == "1.0 MB"
        assert fmt_size(1572864) == "1.5 MB"

    def test_gb_boundary(self):
        assert fmt_size(1024 ** 3) == "1.0 GB"
        assert fmt_size(2 * 1024 ** 3) == "2.0 GB"

    def test_tb_boundary(self):
        assert fmt_size(1024 ** 4) == "1.0 TB"
        assert fmt_size(5 * 1024 ** 4) == "5.0 TB"

    def test_pb_boundary(self):
        assert fmt_size(1024 ** 5) == "1.0 PB"
        assert fmt_size(2 * 1024 ** 5) == "2.0 PB"

    def test_handles_float(self):
        assert fmt_size(1500.5) in ("1.5 KB", "1.5 KB".replace("1.5", "1.5"))


# ── SizeCalculator unit tests ──────────────────────────────────────────────


@pytest.fixture
def fake_state_root(tmp_path: Path) -> Path:
    """Create a fake .grace/state/ with packets and run dirs.

    Layout:
        state/packets/<pid1>/runs/R01/logs/coder.log  (1 KB)
        state/packets/<pid1>/runs/R02/logs/coder.log  (2 KB)
        state/packets/<pid2>/runs/R01/logs/coder.log  (1 MB)
    """
    p1 = tmp_path / "state" / "packets" / "pkt_001" / "runs" / "R01" / "logs"
    p2 = tmp_path / "state" / "packets" / "pkt_001" / "runs" / "R02" / "logs"
    p3 = tmp_path / "state" / "packets" / "pkt_002" / "runs" / "R01" / "logs"
    for d in (p1, p2, p3):
        d.mkdir(parents=True, exist_ok=True)
    (p1 / "coder.log").write_bytes(b"x" * 1024)            # 1 KB
    (p2 / "coder.log").write_bytes(b"y" * 2048)            # 2 KB
    (p3 / "coder.log").write_bytes(b"z" * 1024 * 1024)     # 1 MB
    return tmp_path / "state"


@pytest.fixture
def fake_worktree_root(tmp_path: Path) -> Path:
    """Create a fake .grace/worktrees/."""
    wt1 = tmp_path / "worktrees" / "pkt_001" / ".git"
    wt2 = tmp_path / "worktrees" / "pkt_002" / ".git"
    for d in (wt1, wt2):
        d.mkdir(parents=True, exist_ok=True)
    (wt1 / "HEAD").write_bytes(b"x" * 4096)    # 4 KB
    (wt2 / "HEAD").write_bytes(b"y" * 8192)    # 8 KB
    return tmp_path / "worktrees"


@pytest.fixture
def calc(tmp_path: Path) -> SizeCalculator:
    return SizeCalculator(state_root=tmp_path / "state", worktree_root=tmp_path / "worktrees")


class TestDu:
    """`du(path)` returns total size in bytes (sum of all files)."""

    def test_du_empty_dir(self, tmp_path: Path):
        c = SizeCalculator()
        d = tmp_path / "empty"
        d.mkdir()
        assert c.du(d) == 0

    def test_du_missing(self, tmp_path: Path):
        c = SizeCalculator()
        d = tmp_path / "missing"
        assert c.du(d) == 0

    def test_du_single_file(self, tmp_path: Path):
        c = SizeCalculator()
        f = tmp_path / "f.bin"
        f.write_bytes(b"x" * 100)
        assert c.du(f) == 100

    def test_du_nested(self, tmp_path: Path):
        c = SizeCalculator()
        d = tmp_path / "x" / "y" / "z"
        d.mkdir(parents=True)
        (d / "a").write_bytes(b"x" * 50)
        (d / "b").write_bytes(b"y" * 50)
        assert c.du(tmp_path / "x") == 100

    def test_du_mixed_files_and_dirs(self, tmp_path: Path):
        c = SizeCalculator()
        (tmp_path / "a.bin").write_bytes(b"x" * 10)
        sub = tmp_path / "sub"
        sub.mkdir()
        (sub / "b.bin").write_bytes(b"y" * 20)
        assert c.du(tmp_path) == 30

    def test_du_accepts_string_path(self, tmp_path: Path):
        c = SizeCalculator()
        (tmp_path / "f").write_bytes(b"x" * 10)
        assert c.du(str(tmp_path)) == 10


class TestPacketRunsSize:
    """`packet_runs_size(packet_id)` sums all runs for a packet."""

    def test_runs_size_for_known_packet(self, calc, fake_state_root):
        # pkt_001 has R01 (1 KB) + R02 (2 KB) = 3 KB
        assert calc.packet_runs_size("pkt_001") == 1024 + 2048

    def test_runs_size_for_other_packet(self, calc, fake_state_root):
        assert calc.packet_runs_size("pkt_002") == 1024 * 1024

    def test_runs_size_for_unknown_packet(self, calc, fake_state_root):
        assert calc.packet_runs_size("pkt_unknown") == 0

    def test_runs_size_missing_state_root(self, tmp_path: Path):
        c = SizeCalculator(state_root=tmp_path / "missing", worktree_root=tmp_path / "wt")
        assert c.packet_runs_size("pkt_x") == 0


class TestPacketRunsBreakdown:
    """`packet_runs_breakdown(packet_id)` returns PacketSizeInfo."""

    def test_breakdown_returns_per_run(self, calc, fake_state_root):
        info = calc.packet_runs_breakdown("pkt_001")
        assert isinstance(info, PacketSizeInfo)
        assert info.packet_id == "pkt_001"
        assert len(info.runs) == 2
        run_ids = sorted(r.run_id for r in info.runs)
        assert run_ids == ["R01", "R02"]
        for r in info.runs:
            assert isinstance(r, RunSizeInfo)
            assert r.size_bytes > 0
            assert r.path is not None

    def test_breakdown_unknown_packet(self, calc, fake_state_root):
        info = calc.packet_runs_breakdown("pkt_unknown")
        assert info.runs == []
        assert info.size_bytes == 0

    def test_breakdown_size_sum_matches_total(self, calc, fake_state_root):
        total = calc.packet_runs_size("pkt_001")
        info = calc.packet_runs_breakdown("pkt_001")
        assert info.size_bytes == total
        assert info.run_count == 2


class TestWorktreeSize:
    """`worktree_size(packet_id)` and `all_worktrees_total()`."""

    def test_worktree_size_known(self, calc, fake_worktree_root):
        assert calc.worktree_size("pkt_001") == 4096
        assert calc.worktree_size("pkt_002") == 8192

    def test_worktree_size_unknown(self, calc, fake_worktree_root):
        assert calc.worktree_size("pkt_unknown") == 0

    def test_worktree_size_missing_root(self, tmp_path: Path):
        c = SizeCalculator(state_root=tmp_path / "s", worktree_root=tmp_path / "missing")
        assert c.worktree_size("pkt_x") == 0

    def test_all_worktrees_total(self, calc, fake_worktree_root):
        assert calc.all_worktrees_total() == 4096 + 8192


class TestAllStateTotal:
    """`all_state_total()` returns total bytes in state root."""

    def test_total(self, calc, fake_state_root):
        expected = 1024 + 2048 + 1024 * 1024
        assert calc.all_state_total() == expected

    def test_total_missing_root(self, tmp_path: Path):
        c = SizeCalculator(state_root=tmp_path / "missing", worktree_root=tmp_path / "wt")
        assert c.all_state_total() == 0


class TestListWorktreeSlugs:
    """`list_worktree_slugs()` returns all packet IDs in worktree root."""

    def test_list(self, calc, fake_worktree_root):
        slugs = calc.list_worktree_slugs()
        assert "pkt_001" in slugs
        assert "pkt_002" in slugs
        assert len(slugs) == 2

    def test_list_missing_root(self, tmp_path: Path):
        c = SizeCalculator(state_root=tmp_path / "s", worktree_root=tmp_path / "missing")
        assert c.list_worktree_slugs() == []


class TestStateCounters:
    """`state_packet_count()` and `state_run_count()`."""

    def test_packet_count(self, calc, fake_state_root):
        assert calc.state_packet_count() == 2  # pkt_001, pkt_002

    def test_run_count(self, calc, fake_state_root):
        assert calc.state_run_count() == 3  # pkt_001/R01, pkt_001/R02, pkt_002/R01

    def test_count_missing_root(self, tmp_path: Path):
        c = SizeCalculator(state_root=tmp_path / "missing", worktree_root=tmp_path / "wt")
        assert c.state_packet_count() == 0
        assert c.state_run_count() == 0


class TestDiskSnapshot:
    """`disk_snapshot()` returns DiskSnapshot with all totals."""

    def test_snapshot(self, calc, fake_state_root, fake_worktree_root):
        snap = calc.disk_snapshot()
        assert isinstance(snap, DiskSnapshot)
        assert snap.state_total_bytes == 1024 + 2048 + 1024 * 1024
        assert snap.worktrees_total_bytes == 4096 + 8192
        assert snap.packet_count == 2
        assert snap.run_count == 3
        assert snap.worktree_count == 2
        assert isinstance(snap.taken_at, str) if hasattr(snap, "taken_at") else True

    def test_snapshot_empty(self, tmp_path: Path):
        c = SizeCalculator(state_root=tmp_path / "s", worktree_root=tmp_path / "wt")
        snap = c.disk_snapshot()
        assert snap.state_total_bytes == 0
        assert snap.worktrees_total_bytes == 0
        assert snap.packet_count == 0
        assert snap.run_count == 0
        assert snap.worktree_count == 0


class TestPacketSizeInfo:
    """PacketSizeInfo dataclass."""

    def test_dataclass(self):
        info = PacketSizeInfo(packet_id="p1", runs=[])
        assert info.packet_id == "p1"
        assert info.size_bytes == 0
        assert info.run_count == 0
        assert info.runs == []

    def test_size_bytes_sums_runs(self):
        r1 = RunSizeInfo(run_id="R01", path="/x", size_bytes=1024)
        r2 = RunSizeInfo(run_id="R02", path="/y", size_bytes=2048)
        info = PacketSizeInfo(packet_id="p1", runs=[r1, r2])
        assert info.size_bytes == 3072
        assert info.run_count == 2
        assert info.size_human == "3.0 KB"
