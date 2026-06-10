"""Tests for MaintenanceService (TZ_RETENTION_POLICY.md Phase 3)."""
from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from grace_control.services.maintenance_service import (
    BranchInfo,
    CleanupResult,
    MaintenanceService,
    MaintenanceSnapshot,
    WorktreeEntry,
)


@pytest.fixture
def fake_layout(tmp_path: Path) -> tuple[Path, Path, Path]:
    """Create a fake project + state + worktrees layout.

    Returns (state_root, worktree_root, project_root).
    """
    state = tmp_path / "state"
    wt = tmp_path / "worktrees"
    project = tmp_path / "project"
    for d in (state, wt, project):
        d.mkdir()
    # One stale worktree
    stale = wt / "pkt_stale_001"
    stale.mkdir()
    (stale / "f").write_bytes(b"x" * 4096)
    # One fresh worktree
    fresh = wt / "pkt_fresh_002"
    fresh.mkdir()
    (fresh / "f").write_bytes(b"y" * 1024)
    # State dir
    runs = state / "packets" / "pkt_stale_001" / "runs" / "R01"
    runs.mkdir(parents=True)
    (runs / "log").write_bytes(b"z" * 2048)
    return state, wt, project


@pytest.fixture
def fake_git(tmp_path: Path) -> Path:
    """Create a minimal git repo with a few branches."""
    repo = tmp_path / "git_repo"
    repo.mkdir()
    subprocess.run(["git", "init", "-b", "main"], cwd=str(repo), check=True, capture_output=True)
    subprocess.run(["git", "config", "user.email", "t@t"], cwd=str(repo), check=True, capture_output=True)
    subprocess.run(["git", "config", "user.name", "t"], cwd=str(repo), check=True, capture_output=True)
    (repo / "f").write_bytes(b"x")
    subprocess.run(["git", "add", "."], cwd=str(repo), check=True, capture_output=True)
    subprocess.run(["git", "commit", "-m", "init"], cwd=str(repo), check=True, capture_output=True)
    # Create an agent/* branch
    subprocess.run(["git", "branch", "agent/pkt_x-attempt-0001"], cwd=str(repo), check=True, capture_output=True)
    return repo


# ── Initialization ────────────────────────────────────────────────────────


class TestInit:
    def test_init_with_roots(self, fake_layout):
        s, w, p = fake_layout
        svc = MaintenanceService(state_root=s, worktree_root=w, project_root=p)
        assert svc.state_root == s
        assert svc.worktree_root == w
        assert svc.project_root == p
        assert svc.size_calculator is not None

    def test_init_without_roots(self):
        svc = MaintenanceService()
        assert svc.state_root is None
        assert svc.worktree_root is None
        assert svc.project_root is None


# ── snapshot ──────────────────────────────────────────────────────────────


class TestSnapshot:
    def test_snapshot_returns_dataclass(self, fake_layout):
        s, w, p = fake_layout
        svc = MaintenanceService(state_root=s, worktree_root=w, project_root=p)
        snap = svc.snapshot()
        assert isinstance(snap, MaintenanceSnapshot)
        assert isinstance(snap.taken_at, str) and snap.taken_at

    def test_snapshot_disk_totals(self, fake_layout):
        s, w, p = fake_layout
        svc = MaintenanceService(state_root=s, worktree_root=w, project_root=p)
        snap = svc.snapshot()
        # pkt_stale_001 (4096) + pkt_fresh_002 (1024)
        assert snap.disk.worktrees_total_bytes == 4096 + 1024
        assert snap.disk.worktree_count == 2
        # state has 2048 bytes
        assert snap.disk.state_total_bytes == 2048
        assert snap.disk.packet_count == 1
        assert snap.disk.run_count == 1

    def test_snapshot_worktrees_listed(self, fake_layout):
        s, w, p = fake_layout
        svc = MaintenanceService(state_root=s, worktree_root=w, project_root=p)
        snap = svc.snapshot(packet_states={"pkt_stale_001": "rejected", "pkt_fresh_002": "running"})
        slugs = {w.slug for w in snap.worktrees}
        assert "pkt_stale_001" in slugs
        assert "pkt_fresh_002" in slugs

    def test_snapshot_flags_stale(self, fake_layout):
        s, w, p = fake_layout
        svc = MaintenanceService(state_root=s, worktree_root=w, project_root=p)
        snap = svc.snapshot(packet_states={"pkt_stale_001": "rejected", "pkt_fresh_002": "running"})
        stale = [w for w in snap.worktrees if w.is_stale]
        assert len(stale) == 1
        assert stale[0].slug == "pkt_stale_001"
        assert stale[0].size_bytes == 4096
        assert snap.stale_worktree_count == 1
        assert snap.stale_worktree_total_bytes == 4096
        assert snap.stale_worktree_total_human == "4.0 KB"

    def test_snapshot_unknown_packet_not_stale(self, fake_layout):
        s, w, p = fake_layout
        svc = MaintenanceService(state_root=s, worktree_root=w, project_root=p)
        # Empty states map → no worktrees are flagged stale
        snap = svc.snapshot(packet_states={})
        assert all(not w.is_stale for w in snap.worktrees)
        assert snap.stale_worktree_count == 0

    def test_snapshot_terminal_state_types(self, fake_layout):
        """All terminal-like states are flagged stale."""
        s, w, p = fake_layout
        svc = MaintenanceService(state_root=s, worktree_root=w, project_root=p)
        for state in ("merged", "rejected", "failed", "blocked", "cancelled"):
            snap = svc.snapshot(packet_states={"pkt_stale_001": state})
            stale = [wt for wt in snap.worktrees if wt.slug == "pkt_stale_001"]
            assert stale and stale[0].is_stale, f"state={state!r} should be stale"

    def test_snapshot_git_root_found(self, fake_layout, fake_git):
        s, w, _ = fake_layout
        svc = MaintenanceService(state_root=s, worktree_root=w, project_root=fake_git)
        snap = svc.snapshot()
        assert snap.git_available is True
        assert snap.git_root is not None
        assert Path(snap.git_root).resolve() == fake_git.resolve()

    def test_snapshot_no_git_returns_none(self, fake_layout):
        s, w, p = fake_layout
        svc = MaintenanceService(state_root=s, worktree_root=w, project_root=p)
        snap = svc.snapshot()
        assert snap.git_available is False
        assert snap.git_root is None

    def test_snapshot_to_dict(self, fake_layout):
        s, w, p = fake_layout
        svc = MaintenanceService(state_root=s, worktree_root=w, project_root=p)
        snap = svc.snapshot()
        d = snap.to_dict()
        assert "disk" in d
        assert "branches" in d
        assert "worktrees" in d
        assert "stale_worktree_count" in d


# ── Branches listing ───────────────────────────────────────────────────────


class TestListBranches:
    def test_lists_agent_branches(self, fake_git):
        svc = MaintenanceService(project_root=fake_git)
        branches = svc._list_branches()
        names = {b.name for b in branches}
        assert "main" in names
        assert "agent/pkt_x-attempt-0001" in names

    def test_flags_agent_branches(self, fake_git):
        svc = MaintenanceService(project_root=fake_git)
        branches = svc._list_branches()
        agent = [b for b in branches if b.is_agent_branch]
        non_agent = [b for b in branches if not b.is_agent_branch]
        assert {b.name for b in agent} == {"agent/pkt_x-attempt-0001"}
        assert "main" in {b.name for b in non_agent}

    def test_no_git_returns_empty(self, tmp_path):
        svc = MaintenanceService(project_root=tmp_path)
        assert svc._list_branches() == []

    def test_no_project_returns_empty(self):
        svc = MaintenanceService()
        assert svc._list_branches() == []


# ── Worktrees listing ──────────────────────────────────────────────────────


class TestListWorktrees:
    def test_lists_all_worktrees(self, fake_layout):
        s, w, p = fake_layout
        svc = MaintenanceService(state_root=s, worktree_root=w, project_root=p)
        entries = svc._list_worktrees({})
        slugs = {e.slug for e in entries}
        assert slugs == {"pkt_stale_001", "pkt_fresh_002"}

    def test_missing_worktree_root(self, tmp_path):
        svc = MaintenanceService(worktree_root=tmp_path / "missing")
        assert svc._list_worktrees({}) == []


# ── Cleanup actions ───────────────────────────────────────────────────────


class TestCleanupWorktree:
    def test_dry_run_does_not_remove(self, fake_layout):
        s, w, p = fake_layout
        svc = MaintenanceService(state_root=s, worktree_root=w, project_root=p)
        result = svc.cleanup_worktree("pkt_stale_001", dry_run=True)
        assert "pkt_stale_001" in result.worktrees_removed
        assert result.dry_run is True
        # Directory still exists
        assert (w / "pkt_stale_001").exists()

    def test_actual_removal(self, fake_layout):
        s, w, p = fake_layout
        svc = MaintenanceService(state_root=s, worktree_root=w, project_root=p)
        result = svc.cleanup_worktree("pkt_stale_001")
        assert result.errors == []
        assert "pkt_stale_001" in result.worktrees_removed
        assert result.bytes_freed == 4096
        # Directory gone
        assert not (w / "pkt_stale_001").exists()

    def test_unknown_slug_returns_error(self, fake_layout):
        s, w, p = fake_layout
        svc = MaintenanceService(state_root=s, worktree_root=w, project_root=p)
        result = svc.cleanup_worktree("pkt_unknown")
        assert result.errors
        assert result.worktrees_removed == []

    def test_no_worktree_root_returns_error(self):
        svc = MaintenanceService()
        result = svc.cleanup_worktree("pkt_x")
        assert result.errors


class TestCleanupBranch:
    def test_dry_run(self, fake_git):
        svc = MaintenanceService(project_root=fake_git)
        result = svc.cleanup_branch("agent/pkt_x-attempt-0001", dry_run=True)
        assert "agent/pkt_x-attempt-0001" in result.branches_deleted
        # Branch still exists
        assert svc._branch_exists("agent/pkt_x-attempt-0001")

    def test_actual_delete(self, fake_git):
        svc = MaintenanceService(project_root=fake_git)
        result = svc.cleanup_branch("agent/pkt_x-attempt-0001")
        assert result.errors == []
        assert "agent/pkt_x-attempt-0001" in result.branches_deleted
        # Branch gone
        assert not svc._branch_exists("agent/pkt_x-attempt-0001")

    def test_unknown_branch(self, fake_git):
        svc = MaintenanceService(project_root=fake_git)
        result = svc.cleanup_branch("agent/nonexistent")
        assert result.errors
        assert result.branches_deleted == []

    def test_no_project_root(self):
        svc = MaintenanceService()
        result = svc.cleanup_branch("agent/x")
        assert result.errors


class TestCleanupStaleWorktrees:
    def test_cleans_only_stale(self, fake_layout):
        s, w, p = fake_layout
        svc = MaintenanceService(state_root=s, worktree_root=w, project_root=p)
        result = svc.cleanup_stale_worktrees(
            packet_states={"pkt_stale_001": "rejected", "pkt_fresh_002": "running"},
        )
        assert result.errors == []
        assert "pkt_stale_001" in result.worktrees_removed
        assert "pkt_fresh_002" not in result.worktrees_removed
        # Bytes freed = stale size (4096)
        assert result.bytes_freed == 4096
        # Stale dir gone, fresh dir remains
        assert not (w / "pkt_stale_001").exists()
        assert (w / "pkt_fresh_002").exists()

    def test_dry_run(self, fake_layout):
        s, w, p = fake_layout
        svc = MaintenanceService(state_root=s, worktree_root=w, project_root=p)
        result = svc.cleanup_stale_worktrees(
            packet_states={"pkt_stale_001": "rejected"},
            dry_run=True,
        )
        assert "pkt_stale_001" in result.worktrees_removed
        assert (w / "pkt_stale_001").exists()  # still there

    def test_no_stale(self, fake_layout):
        s, w, p = fake_layout
        svc = MaintenanceService(state_root=s, worktree_root=w, project_root=p)
        result = svc.cleanup_stale_worktrees(
            packet_states={"pkt_stale_001": "running", "pkt_fresh_002": "running"},
        )
        assert result.worktrees_removed == []
        assert result.bytes_freed == 0


# ── Dataclasses ────────────────────────────────────────────────────────────


class TestDataclasses:
    def test_branch_info(self):
        b = BranchInfo(name="agent/x", is_agent_branch=True, is_current=False)
        assert b.to_dict() == {
            "name": "agent/x",
            "is_agent_branch": True,
            "is_current": False,
        }

    def test_worktree_entry(self):
        w = WorktreeEntry(slug="x", path="/p", size_bytes=2048, packet_state="rejected", is_stale=True)
        assert w.size_human == "2.0 KB"
        d = w.to_dict()
        assert d["slug"] == "x"
        assert d["size_human"] == "2.0 KB"
        assert d["is_stale"] is True

    def test_cleanup_result(self):
        r = CleanupResult(worktrees_removed=["x"], bytes_freed=1024)
        assert r.bytes_freed_human == "1.0 KB"
        d = r.to_dict()
        assert d["ok"] is True
        assert d["bytes_freed_human"] == "1.0 KB"


class TestGitServicePreflight:
    def test_preflight_valid_clean_repo(self, fake_git: Path):
        from grace_control.services.git_service import GitService
        git = GitService()
        res = git.run_preflight(fake_git, require_clean=True, require_sync=False)
        assert res.success is True
        assert res.is_git_repo is True
        assert res.working_tree_clean is True
        assert res.current_branch == "main"
        assert res.local_head != ""

    def test_preflight_dirty_repo(self, fake_git: Path):
        from grace_control.services.git_service import GitService
        git = GitService()
        # Make target repo dirty by writing an untracked file
        (fake_git / "dirty.txt").write_text("dirty content")
        
        # When require_clean=True, must fail
        res = git.run_preflight(fake_git, require_clean=True, require_sync=False)
        assert res.success is False
        assert "uncommitted changes" in res.error
        assert res.working_tree_clean is False

        # When require_clean=False, must pass
        res_no_clean = git.run_preflight(fake_git, require_clean=False, require_sync=False)
        assert res_no_clean.success is True
        assert res_no_clean.working_tree_clean is False

    def test_preflight_non_git_dir(self, tmp_path: Path):
        from grace_control.services.git_service import GitService
        git = GitService()
        non_git = tmp_path / "nongit"
        non_git.mkdir()
        res = git.run_preflight(non_git)
        assert res.success is False
        assert "requires execution.target_repo_root" in res.error
        assert res.is_git_repo is False

    def test_preflight_missing_dir(self):
        from grace_control.services.git_service import GitService
        git = GitService()
        res = git.run_preflight(Path("/nonexistent/path"))
        assert res.success is False
        assert "does not exist" in res.error
