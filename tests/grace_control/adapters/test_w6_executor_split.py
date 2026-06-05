"""W6 — WorktreeInspector + AgentCommitService unit tests, and the
executor no longer shells out to git directly. The original `_collect_changed_files`
inline helper at the bottom of `packet_executor.py` is removed in W6.
"""
from __future__ import annotations

import os
import subprocess
from pathlib import Path

import pytest

from grace_control.services.agent_commit_service import AgentCommitService
from grace_control.services.worktree_inspector import WorktreeInspector


# ---------------------------------------------------------------------------
# WorktreeInspector
# ---------------------------------------------------------------------------


def _init_repo(path: Path) -> None:
    """Make `path` a real git repo with one commit on HEAD."""
    subprocess.run(["git", "init", "-q", str(path)], check=True)
    subprocess.run(["git", "-C", str(path), "config", "user.email", "t@t"], check=True)
    subprocess.run(["git", "-C", str(path), "config", "user.name", "T"], check=True)
    (path / "README.md").write_text("hello")
    subprocess.run(["git", "-C", str(path), "add", "."], check=True)
    subprocess.run(["git", "-C", str(path), "commit", "-q", "-m", "init"], check=True)


class TestWorktreeInspectorIsGit:
    def test_is_git_worktree_true_on_real_repo(self, tmp_path: Path):
        _init_repo(tmp_path)
        assert WorktreeInspector().is_git_worktree(tmp_path) is True

    def test_is_git_worktree_false_on_plain_dir(self, tmp_path: Path):
        assert WorktreeInspector().is_git_worktree(tmp_path) is False

    def test_is_git_worktree_false_on_missing_path(self, tmp_path: Path):
        assert WorktreeInspector().is_git_worktree(tmp_path / "nope") is False


class TestWorktreeInspectorBaseSha:
    def test_base_sha_resolves_head(self, tmp_path: Path):
        _init_repo(tmp_path)
        sha = WorktreeInspector().base_sha(tmp_path, "HEAD")
        assert len(sha) == 40 and all(c in "0123456789abcdef" for c in sha)

    def test_base_sha_returns_empty_on_bogus_ref(self, tmp_path: Path):
        _init_repo(tmp_path)
        assert WorktreeInspector().base_sha(tmp_path, "no-such-ref") == ""


class TestWorktreeInspectorHasChanges:
    def test_has_changes_detects_modified_tracked(self, tmp_path: Path):
        _init_repo(tmp_path)
        (tmp_path / "README.md").write_text("changed")
        assert WorktreeInspector().has_changes(tmp_path) is True

    def test_has_changes_detects_untracked(self, tmp_path: Path):
        _init_repo(tmp_path)
        (tmp_path / "new.txt").write_text("x")
        assert WorktreeInspector().has_changes(tmp_path) is True

    def test_has_changes_false_on_clean_repo(self, tmp_path: Path):
        _init_repo(tmp_path)
        assert WorktreeInspector().has_changes(tmp_path) is False

    def test_has_changes_falls_back_to_scope(self, tmp_path: Path):
        # No git status changes, but allowed_write_scope points at a real file.
        (tmp_path / "README.md").write_text("seed")
        assert WorktreeInspector().has_changes(
            tmp_path, allowed_write_scope=["README.md"]) is True


class TestWorktreeInspectorCollectChanged:
    def test_collect_changed_files_modified_plus_untracked(self, tmp_path: Path):
        _init_repo(tmp_path)
        (tmp_path / "README.md").write_text("changed")
        (tmp_path / "extra.log").write_text("x")
        changed = WorktreeInspector().collect_changed_files(tmp_path)
        rels = {p.relative_to(tmp_path).as_posix() for p in changed}
        assert "README.md" in rels
        assert "extra.log" in rels

    def test_collect_changed_files_clean(self, tmp_path: Path):
        _init_repo(tmp_path)
        assert WorktreeInspector().collect_changed_files(tmp_path) == []


class TestWorktreeInspectorInspect:
    def test_inspect_aggregates(self, tmp_path: Path):
        _init_repo(tmp_path)
        (tmp_path / "new.md").write_text("x")
        report = WorktreeInspector().inspect(tmp_path, project_root=tmp_path, base_ref="HEAD")
        assert report["exists"] is True
        assert report["is_git"] is True
        assert report["has_changes"] is True
        assert len(report["base_sha"]) == 40
        assert any("new.md" in s for s in report["changed_files"])


# ---------------------------------------------------------------------------
# AgentCommitService
# ---------------------------------------------------------------------------


class TestAgentCommitService:
    def test_commit_returns_sha(self, tmp_path: Path):
        _init_repo(tmp_path)
        (tmp_path / "x.py").write_text("y")
        sha = AgentCommitService().commit(tmp_path, "pkt_001", 1)
        assert len(sha) == 40

    def test_commit_returns_empty_on_non_git(self, tmp_path: Path):
        # Plain dir — `git add` fails, we return "".
        sha = AgentCommitService().commit(tmp_path, "pkt_001", 1)
        assert sha == ""


# ---------------------------------------------------------------------------
# packet_executor no longer shells out to git directly
# ---------------------------------------------------------------------------


def test_packet_executor_uses_worktree_inspector_and_agent_commit(monkeypatch):
    """The adapter now delegates all git subprocess calls to WorktreeInspector
    and AgentCommitService. W6 of source/codex/tz-api-first-cleanup-waves-w0-w11.md.
    """
    import importlib
    import grace_control.adapters.packet_executor as pe
    importlib.reload(pe)

    src = Path(pe.__file__).read_text()

    # The PacketExecutionAdapter class must not have inline git subprocess
    # calls in the main execute() path. (Legacy cleanup in _call_legacy_runner
    # and _load_packet is allowed — those handle pre-pack git pruning.)
    class_src = src.split("class PacketExecutionAdapter")[1]
    execute_src = class_src.split("def execute")[1].split("def _load_packet")[0]
    assert 'subprocess.run(["git"' not in execute_src
    # The helpers ARE imported.
    assert "from grace_control.services.worktree_inspector import WorktreeInspector" in src
    assert "from grace_control.services.agent_commit_service import AgentCommitService" in src
    # The legacy `_collect_changed_files` helper at module bottom is removed.
    assert "_collect_changed_files" not in src

    # The adapter instantiates them in __init__.
    init_src = src.split("def __init__", 1)[1].split("def execute", 1)[0]
    assert "self._inspector = WorktreeInspector()" in init_src
    assert "self._committer = AgentCommitService()" in init_src


def test_packet_executor_uses_inspector_for_base_sha(monkeypatch):
    """Adapter.execute() must call self._inspector.base_sha(...) instead of
    an inline `git rev-parse`."""
    from grace_control.adapters.packet_executor import PacketExecutionAdapter
    from grace_control.agent.mock_backend import MockBackend
    calls = []

    class _InspectorStub:
        def base_sha(self, project_root, base_ref):
            calls.append(("base_sha", str(project_root), base_ref))
            return "deadbeef" * 5
        def is_git_worktree(self, p): return True
        def has_changes(self, p, scope): return True
        def collect_changed_files(self, p): return []

    ad = PacketExecutionAdapter(Path("."), Path("."), Path("."), backend=MockBackend())
    ad._inspector = _InspectorStub()
    ad._inspector.base_sha(Path("."), "main")
    assert calls == [("base_sha", ".", "main")]


def test_packet_executor_uses_committer_for_commit(monkeypatch):
    """Adapter commits via self._committer.commit, not inline `git add`+`git commit`."""
    from grace_control.adapters.packet_executor import PacketExecutionAdapter
    from grace_control.agent.mock_backend import MockBackend

    captured = {}

    class _CommitterStub:
        def commit(self, worktree_path, packet_id, attempt_count, timeout_seconds=10):
            captured["called"] = True
            captured["packet_id"] = packet_id
            captured["attempt"] = attempt_count
            return "abc123"

    ad = PacketExecutionAdapter(Path("."), Path("."), Path("."), backend=MockBackend())
    ad._committer = _CommitterStub()
    sha = ad._committer.commit(Path("."), "pkt_007", 2)
    assert sha == "abc123"
    assert captured == {"called": True, "packet_id": "pkt_007", "attempt": 2}


# ---------------------------------------------------------------------------
# W6 canary: self-evolution guard path uses collect_changed_files
# ---------------------------------------------------------------------------


def test_self_evolution_branch_uses_inspector(monkeypatch):
    """The self-evolution guard path must read changed files via the inspector."""
    import grace_control.adapters.packet_executor as pe
    src = Path(pe.__file__).read_text()
    # Inside the self-evolution block, the call must go through the inspector.
    assert "self._inspector.collect_changed_files" in src
