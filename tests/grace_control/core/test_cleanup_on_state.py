"""Unit tests for TerminalStateCleanup (TZ_RETENTION_POLICY.md Phase 1).

Coverage:
1. CleanupResult dataclass + to_dict + success property.
2. Rejected packet: deletes worktree + all attempt-branches for packet.
3. Failed packet: deletes worktree + all attempt-branches for packet.
4. Blocked packet: deletes worktree + all attempt-branches for packet.
5. Specific attempt cleanup: only that attempt's worktree + branch.
6. All-attempts cleanup: scans worktree dirs 1..max_attempts + wildcard branch.
7. Run artifacts in .grace/state/ are NOT touched.
8. No-op if no worktree + no branches (idempotent).
9. Errors collected but never raised.
10. _parse_branch_list handles `* `, `  `, `+ ` markers.
11. _branch_pattern constructs correct git pattern.
12. Different packets' branches/worktrees not affected.
"""
from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from grace_control.core.cleanup_on_state import CleanupResult, TerminalStateCleanup


# ── Fixtures ────────────────────────────────────────────────────────────────


@pytest.fixture
def git_repo(tmp_path: Path) -> Path:
    """Create a minimal git repo with an initial commit (so branches can be created)."""
    repo = tmp_path / "repo"
    repo.mkdir()
    subprocess.run(["git", "init", "-b", "main", str(repo)], check=True, capture_output=True)
    subprocess.run(["git", "-C", str(repo), "config", "user.email", "t@t"], check=True, capture_output=True)
    subprocess.run(["git", "-C", str(repo), "config", "user.name", "T"], check=True, capture_output=True)
    (repo / "README.md").write_text("init")
    subprocess.run(["git", "-C", str(repo), "add", "README.md"], check=True, capture_output=True)
    subprocess.run(["git", "-C", str(repo), "commit", "-m", "init"], check=True, capture_output=True)
    return repo


@pytest.fixture
def worktree_root(tmp_path: Path) -> Path:
    """Create an empty worktree root (no worktrees yet)."""
    wt = tmp_path / "worktrees"
    wt.mkdir()
    return wt


@pytest.fixture
def state_root(tmp_path: Path) -> Path:
    """Create a state root with a sample run artifacts dir that MUST survive cleanup."""
    sr = tmp_path / "state"
    sr.mkdir()
    runs = sr / "packets" / "pkt_AAA" / "runs"
    for r in ("R01", "R02", "R03"):
        rd = runs / r
        rd.mkdir(parents=True)
        (rd / "agent_output.log").write_text("log line 1\nlog line 2\n")
        (rd / "acceptance_report.json").write_text('{"verdict": "rejected"}')
    return sr


def _make_branch(repo: Path, name: str) -> None:
    """Create a git branch in the repo."""
    r = subprocess.run(
        ["git", "-C", str(repo), "branch", name],
        capture_output=True, text=True,
    )
    assert r.returncode == 0, r.stderr


def _branch_exists(repo: Path, name: str) -> bool:
    r = subprocess.run(
        ["git", "-C", str(repo), "branch", "--list", name],
        capture_output=True, text=True,
    )
    return bool(r.stdout.strip())


def _make_worktree(worktree_root: Path, slug: str) -> Path:
    """Create a fake worktree directory (the real one is created via `git worktree add`).

    For cleanup testing we don't need a real worktree — we just need a dir to remove.
    """
    wt = worktree_root / slug
    wt.mkdir()
    (wt / "fake_file.txt").write_text("x")
    return wt


# ── 1. CleanupResult dataclass ──────────────────────────────────────────────


class TestCleanupResult:
    def test_defaults(self):
        r = CleanupResult()
        assert r.branches_deleted == []
        assert r.worktree_removed is False
        assert r.errors == []
        assert r.success is True

    def test_success_false_on_errors(self):
        r = CleanupResult(errors=["oops"])
        assert r.success is False

    def test_to_dict_shape(self):
        r = CleanupResult(branches_deleted=["agent/x-attempt-0001"], worktree_removed=True)
        d = r.to_dict()
        assert d["branches_deleted"] == ["agent/x-attempt-0001"]
        assert d["worktree_removed"] is True
        assert d["errors"] == []
        assert d["success"] is True


# ── 2-4. Terminal states delete worktree + branches ─────────────────────────


class TestTerminalStateCleanup:
    def test_rejected_deletes_worktree_and_branches(self, git_repo, worktree_root, state_root):
        pid = "pkt_AAA"
        _make_branch(git_repo, f"agent/{pid}-attempt-0001")
        _make_branch(git_repo, f"agent/{pid}-attempt-0002")
        _make_worktree(worktree_root, f"{pid}-attempt-0001")
        _make_worktree(worktree_root, f"{pid}-attempt-0002")

        cleanup = TerminalStateCleanup(git_repo, worktree_root)
        result = cleanup.run(pid, attempt=None)

        assert result.success
        assert result.worktree_removed is True
        assert len(result.branches_deleted) == 2
        assert f"agent/{pid}-attempt-0001" in result.branches_deleted
        assert f"agent/{pid}-attempt-0002" in result.branches_deleted
        # Branches actually gone from git:
        assert not _branch_exists(git_repo, f"agent/{pid}-attempt-0001")
        assert not _branch_exists(git_repo, f"agent/{pid}-attempt-0002")
        # Worktree dirs gone:
        assert not (worktree_root / f"{pid}-attempt-0001").exists()
        assert not (worktree_root / f"{pid}-attempt-0002").exists()
        # Run artifacts UNTOUCHED:
        assert (state_root / "packets" / pid / "runs" / "R01" / "agent_output.log").exists()
        assert (state_root / "packets" / pid / "runs" / "R02" / "acceptance_report.json").exists()

    def test_failed_deletes_worktree_and_branches(self, git_repo, worktree_root, state_root):
        pid = "pkt_BBB"
        _make_branch(git_repo, f"agent/{pid}-attempt-0001")
        _make_worktree(worktree_root, f"{pid}-attempt-0001")

        cleanup = TerminalStateCleanup(git_repo, worktree_root)
        result = cleanup.run(pid)

        assert result.success
        assert result.worktree_removed is True
        assert result.branches_deleted == [f"agent/{pid}-attempt-0001"]
        assert not _branch_exists(git_repo, f"agent/{pid}-attempt-0001")
        assert not (worktree_root / f"{pid}-attempt-0001").exists()
        # State preserved
        assert (state_root / "packets" / "pkt_AAA" / "runs" / "R01" / "agent_output.log").exists()

    def test_blocked_deletes_worktree_and_branches(self, git_repo, worktree_root, state_root):
        pid = "pkt_CCC"
        for a in (1, 2, 3):
            _make_branch(git_repo, f"agent/{pid}-attempt-{a:04d}")
            _make_worktree(worktree_root, f"{pid}-attempt-{a:04d}")

        cleanup = TerminalStateCleanup(git_repo, worktree_root)
        result = cleanup.run(pid)

        assert result.success
        assert result.worktree_removed is True
        assert len(result.branches_deleted) == 3
        # All gone from git
        for a in (1, 2, 3):
            assert not _branch_exists(git_repo, f"agent/{pid}-attempt-{a:04d}")
            assert not (worktree_root / f"{pid}-attempt-{a:04d}").exists()


# ── 5-6. Attempt-specific vs all-attempts cleanup ───────────────────────────


class TestAttemptSelection:
    def test_specific_attempt_only(self, git_repo, worktree_root):
        pid = "pkt_DDD"
        _make_branch(git_repo, f"agent/{pid}-attempt-0001")
        _make_branch(git_repo, f"agent/{pid}-attempt-0002")
        _make_branch(git_repo, f"agent/{pid}-attempt-0003")
        _make_worktree(worktree_root, f"{pid}-attempt-0001")
        _make_worktree(worktree_root, f"{pid}-attempt-0002")
        _make_worktree(worktree_root, f"{pid}-attempt-0003")

        cleanup = TerminalStateCleanup(git_repo, worktree_root)
        result = cleanup.run(pid, attempt=2)

        # Only attempt 2 cleaned
        assert result.branches_deleted == [f"agent/{pid}-attempt-0002"]
        assert not _branch_exists(git_repo, f"agent/{pid}-attempt-0002")
        # Others remain
        assert _branch_exists(git_repo, f"agent/{pid}-attempt-0001")
        assert _branch_exists(git_repo, f"agent/{pid}-attempt-0003")
        assert (worktree_root / f"{pid}-attempt-0001").exists()
        assert (worktree_root / f"{pid}-attempt-0003").exists()

    def test_all_attempts_via_wildcard(self, git_repo, worktree_root):
        pid = "pkt_EEE"
        for a in range(1, 4):
            _make_branch(git_repo, f"agent/{pid}-attempt-{a:04d}")
            _make_worktree(worktree_root, f"{pid}-attempt-{a:04d}")
        # Add an unrelated branch that must NOT be deleted
        _make_branch(git_repo, "some-feature-branch")
        _make_branch(git_repo, f"agent/OTHER-attempt-0001")

        cleanup = TerminalStateCleanup(git_repo, worktree_root)
        result = cleanup.run(pid, attempt=None)

        assert len(result.branches_deleted) == 3
        # Other branches safe
        assert _branch_exists(git_repo, "some-feature-branch")
        assert _branch_exists(git_repo, "agent/OTHER-attempt-0001")

    def test_max_attempts_scans_dirs(self, git_repo, worktree_root):
        pid = "pkt_FFF"
        # No branches, but a high-numbered worktree dir
        _make_worktree(worktree_root, f"{pid}-attempt-0007")

        cleanup = TerminalStateCleanup(git_repo, worktree_root)
        result = cleanup.run(pid, attempt=None, max_attempts=8)

        assert result.worktree_removed is True
        assert result.branches_deleted == []
        assert not (worktree_root / f"{pid}-attempt-0007").exists()


# ── 7. Run artifacts preserved ──────────────────────────────────────────────


class TestArtifactsPreserved:
    def test_state_dir_intact_after_cleanup(self, git_repo, worktree_root, state_root):
        pid = "pkt_GGG"
        _make_branch(git_repo, f"agent/{pid}-attempt-0001")
        _make_worktree(worktree_root, f"{pid}-attempt-0001")

        cleanup = TerminalStateCleanup(git_repo, worktree_root)
        cleanup.run(pid)

        # ALL run files preserved
        for r in ("R01", "R02", "R03"):
            log = state_root / "packets" / "pkt_AAA" / "runs" / r / "agent_output.log"
            rep = state_root / "packets" / "pkt_AAA" / "runs" / r / "acceptance_report.json"
            assert log.exists(), f"log missing: {log}"
            assert rep.exists(), f"report missing: {rep}"
            assert log.read_text() == "log line 1\nlog line 2\n"
            assert rep.read_text() == '{"verdict": "rejected"}'


# ── 8. Idempotency ──────────────────────────────────────────────────────────


class TestIdempotency:
    def test_no_op_when_no_worktree_and_no_branches(self, git_repo, worktree_root):
        cleanup = TerminalStateCleanup(git_repo, worktree_root)
        result = cleanup.run("pkt_NONE")
        assert result.success
        assert result.worktree_removed is False
        assert result.branches_deleted == []
        assert result.errors == []

    def test_repeated_calls_safe(self, git_repo, worktree_root):
        pid = "pkt_HHH"
        _make_branch(git_repo, f"agent/{pid}-attempt-0001")
        _make_worktree(worktree_root, f"{pid}-attempt-0001")

        cleanup = TerminalStateCleanup(git_repo, worktree_root)
        r1 = cleanup.run(pid)
        r2 = cleanup.run(pid)  # second call

        # First call cleans; second call is no-op (no errors)
        assert r1.success
        assert r1.worktree_removed is True
        assert r1.branches_deleted == [f"agent/{pid}-attempt-0001"]
        assert r2.success
        assert r2.worktree_removed is False
        assert r2.branches_deleted == []


# ── 9. Error handling ───────────────────────────────────────────────────────


class TestErrorHandling:
    def test_non_git_repo_collects_error(self, tmp_path):
        """If project_root isn't a git repo, errors are collected, not raised."""
        not_repo = tmp_path / "notgit"
        not_repo.mkdir()
        wt = tmp_path / "wt"
        wt.mkdir()
        cleanup = TerminalStateCleanup(not_repo, wt)
        result = cleanup.run("pkt_X")
        # `git branch --list` will fail in a non-git dir, so we expect an error.
        assert not result.success
        assert len(result.errors) >= 1

    def test_missing_worktree_dir_ignored(self, git_repo, tmp_path):
        """If worktree_root doesn't exist, the run still completes (no worktree to remove)."""
        wt = tmp_path / "nonexistent_wt"
        pid = "pkt_III"
        _make_branch(git_repo, f"agent/{pid}-attempt-0001")

        cleanup = TerminalStateCleanup(git_repo, wt)
        result = cleanup.run(pid)
        # Branch still cleaned, worktree skipped (doesn't exist)
        assert result.branches_deleted == [f"agent/{pid}-attempt-0001"]
        assert result.worktree_removed is False
        assert result.success


# ── 10. _parse_branch_list ──────────────────────────────────────────────────


class TestParseBranchList:
    def test_plain_branches(self):
        out = "  agent/pkt_X-attempt-0001\n  agent/pkt_X-attempt-0002\n"
        assert TerminalStateCleanup._parse_branch_list(out) == [
            "agent/pkt_X-attempt-0001",
            "agent/pkt_X-attempt-0002",
        ]

    def test_current_marker_star(self):
        out = "* agent/pkt_X-attempt-0001\n  agent/pkt_X-attempt-0002\n"
        assert TerminalStateCleanup._parse_branch_list(out) == [
            "agent/pkt_X-attempt-0001",
            "agent/pkt_X-attempt-0002",
        ]

    def test_checked_out_marker_plus(self):
        out = "+ agent/pkt_X-attempt-0001\n"
        assert TerminalStateCleanup._parse_branch_list(out) == [
            "agent/pkt_X-attempt-0001",
        ]

    def test_empty_lines_skipped(self):
        out = "\n  agent/pkt_X-attempt-0001\n\n"
        assert TerminalStateCleanup._parse_branch_list(out) == [
            "agent/pkt_X-attempt-0001",
        ]


# ── 11. _branch_pattern ─────────────────────────────────────────────────────


class TestBranchPattern:
    def test_specific_attempt(self, tmp_path):
        cleanup = TerminalStateCleanup(tmp_path, tmp_path)
        assert cleanup._branch_pattern("pkt_X", 3) == "agent/pkt_X-attempt-0003"

    def test_all_attempts_wildcard(self, tmp_path):
        cleanup = TerminalStateCleanup(tmp_path, tmp_path)
        assert cleanup._branch_pattern("pkt_X", None) == "agent/pkt_X-attempt-*"


# ── 12. Cross-packet isolation ──────────────────────────────────────────────


class TestCrossPacketIsolation:
    def test_other_packets_unaffected(self, git_repo, worktree_root):
        # Two packets, each with 2 attempts
        for pid in ("pkt_J1", "pkt_J2"):
            for a in (1, 2):
                _make_branch(git_repo, f"agent/{pid}-attempt-{a:04d}")
                _make_worktree(worktree_root, f"{pid}-attempt-{a:04d}")

        cleanup = TerminalStateCleanup(git_repo, worktree_root)
        result = cleanup.run("pkt_J1")

        # Only pkt_J1 cleaned
        assert len(result.branches_deleted) == 2
        for a in (1, 2):
            assert not _branch_exists(git_repo, f"agent/pkt_J1-attempt-{a:04d}")
            assert not (worktree_root / f"pkt_J1-attempt-{a:04d}").exists()
            # pkt_J2 untouched
            assert _branch_exists(git_repo, f"agent/pkt_J2-attempt-{a:04d}")
            assert (worktree_root / f"pkt_J2-attempt-{a:04d}").exists()
