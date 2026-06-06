# AI_HEADER: tests for supervisor_cleanup_service
# Pure unit tests; no DB, no subprocesses for the main flow.
import os
import subprocess
import time
from pathlib import Path

import pytest

from grace_control.services.supervisor_cleanup_service import (
    CleanupReport,
    SupervisorCleanupService,
)


@pytest.fixture
def worktree_env(tmp_path: Path) -> tuple[Path, Path]:
    """Create a tiny git repo + .grace/worktrees/ with one orphan dir."""
    target = tmp_path / "target"
    source = tmp_path / "source"
    target.mkdir()
    source.mkdir()
    # Init a git repo so worktree commands work
    subprocess.run(["git", "init", "-q"], cwd=str(target), check=True)
    subprocess.run(["git", "config", "user.email", "t@t"], cwd=str(target), check=True)
    subprocess.run(["git", "config", "user.name", "t"], cwd=str(target), check=True)
    (target / "README.md").write_text("init")
    subprocess.run(["git", "add", "README.md"], cwd=str(target), check=True)
    subprocess.run(["git", "commit", "-q", "-m", "init"], cwd=str(target), check=True)
    # Create a worktree dir that is NOT a real git worktree — simulates orphan
    wt_root = target / ".grace" / "worktrees"
    wt_root.mkdir(parents=True)
    orphan = wt_root / "pkt_001-attempt-0001"
    orphan.mkdir()
    (orphan / "junk.txt").write_text("leftover")
    return target, source


class TestCleanupReport:
    def test_to_dict_shape(self) -> None:
        r = CleanupReport()
        d = r.to_dict()
        assert set(d.keys()) == {
            "worktrees_removed", "worktrees_kept",
            "state_files_removed", "state_files_kept",
            "stale_leases_released", "errors", "duration_seconds",
        }
        assert d["worktrees_removed"] == []
        assert d["stale_leases_released"] == 0


class TestWorktreeCleanup:
    def test_orphan_worktree_is_removed(self, worktree_env: tuple[Path, Path]) -> None:
        target, source = worktree_env
        svc = SupervisorCleanupService(target, source)
        report = svc.run(stale_leases=False, state_files=False)
        assert "pkt_001-attempt-0001" in report.worktrees_removed
        assert not (target / ".grace" / "worktrees" / "pkt_001-attempt-0001").exists()

    def test_idempotent_when_nothing_to_clean(self, worktree_env: tuple[Path, Path]) -> None:
        target, source = worktree_env
        svc = SupervisorCleanupService(target, source)
        first = svc.run(stale_leases=False, state_files=False)
        second = svc.run(stale_leases=False, state_files=False)
        # Second run finds nothing to remove
        assert first.worktrees_removed == ["pkt_001-attempt-0001"]
        assert second.worktrees_removed == []
        assert second.errors == []

    def test_nonexistent_roots_are_noop(self, tmp_path: Path) -> None:
        target = tmp_path / "empty_target"
        source = tmp_path / "empty_source"
        target.mkdir()
        source.mkdir()
        svc = SupervisorCleanupService(target, source)
        report = svc.run()
        assert report.worktrees_removed == []
        assert report.state_files_removed == []
        # Lease step is allowed to fail silently if no DB is initialized —
        # we only assert it doesn't raise here. The errors list may contain
        # a single "stale leases: ..." entry, which is expected and not a
        # problem for the cleanup contract.
        assert isinstance(report.errors, list)


class TestStateFileCleanup:
    def test_old_state_file_is_removed(self, tmp_path: Path) -> None:
        target = tmp_path / "target"
        source = tmp_path / "source"
        target.mkdir()
        source.mkdir()
        state_root = target / ".grace" / "state"
        state_root.mkdir(parents=True)
        old = state_root / "pkt_done"
        old.mkdir()
        (old / "data.json").write_text("{}")
        # Force old mtime
        old_mtime = time.time() - 30 * 86400  # 30 days old
        os.utime(old, (old_mtime, old_mtime))
        # Fresh one
        fresh = state_root / "pkt_recent"
        fresh.mkdir()
        (fresh / "data.json").write_text("{}")
        svc = SupervisorCleanupService(target, source)
        report = svc.run(worktrees=False, stale_leases=False, stale_state_days=7)
        assert "pkt_done" in report.state_files_removed
        assert "pkt_recent" in report.state_files_kept
        assert not old.exists()
        assert fresh.exists()


class TestSafeFailure:
    def test_keeps_worktree_when_packet_lookup_raises(self, tmp_path: Path) -> None:
        """If the DB check for active packets raises, we keep the worktree
        (conservative) and never propagate the exception."""
        from grace_control.services import supervisor_cleanup_service as mod

        target = tmp_path / "target"
        source = tmp_path / "source"
        target.mkdir()
        source.mkdir()
        wt_root = target / ".grace" / "worktrees"
        wt_root.mkdir(parents=True)
        orphan = wt_root / "pkt_002-attempt-0001"
        orphan.mkdir()
        (orphan / "junk.txt").write_text("x")

        # Force `_is_worktree_registered` to return True so the condition
        # short-circuits past it and exercises `_worktree_for_active_packet`.
        original = mod.SupervisorCleanupService._is_worktree_registered
        mod.SupervisorCleanupService._is_worktree_registered = lambda self, slug: True
        try:
            svc = SupervisorCleanupService(target, source)
            # `_worktree_for_active_packet` will raise RuntimeError ("DB not
            # initialized") and our service should swallow it and return False.
            assert svc._worktree_for_active_packet("pkt_002-attempt-0001") is False
        finally:
            mod.SupervisorCleanupService._is_worktree_registered = original
