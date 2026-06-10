"""Tests for AgentWorkspaceBuilder — minimal workspace creation."""
from __future__ import annotations

from pathlib import Path

import pytest

from grace_control.services.agent_workspace_builder import (
    AgentWorkspaceBuilder,
    WorkspaceResult,
)


@pytest.fixture
def target_root(tmp_path: Path) -> Path:
    """Create a minimal target repo with some files."""
    root = tmp_path / "target"
    root.mkdir()
    (root / "main.py").write_text("def main(): pass")
    (root / "tests").mkdir()
    (root / "tests" / "test_main.py").write_text("def test_main(): pass")
    (root / "pyproject.toml").write_text("[project]\nname = 'test'")
    from grace_control.services.git_service import GitService
    git = GitService()
    git._run(["init", "-q"], root)
    git._run(["config", "user.email", "test@grace"], root)
    git._run(["config", "user.name", "Test Agent"], root)
    git._run(["add", "."], root)
    git._run(["commit", "-q", "-m", "initial commit"], root)
    return root


class TestWorkspaceBuilder:
    def test_build_scoped_copy_preserves_paths(self, target_root: Path, tmp_path: Path):
        builder = AgentWorkspaceBuilder(target_root=target_root)
        ws = builder.build_scoped_copy(
            scope_paths=["main.py", "tests/test_main.py"],
            workspace_root=tmp_path,
            slug="test-ws",
        )
        assert ws.workspace_path.exists()
        assert (ws.workspace_path / "main.py").exists()
        assert (ws.workspace_path / "tests" / "test_main.py").exists()
        assert ws.workspace_mode == "scoped_copy"
        assert len(ws.copied_files) >= 2

    def test_build_scoped_copy_includes_config(self, target_root: Path, tmp_path: Path):
        builder = AgentWorkspaceBuilder(target_root=target_root)
        ws = builder.build_scoped_copy(
            scope_paths=["main.py"],
            workspace_root=tmp_path,
            slug="test-ws2",
            config_allowlist=["pyproject.toml"],
        )
        assert (ws.workspace_path / "pyproject.toml").exists()

    def test_build_scoped_copy_excludes_orchestrator(self, target_root: Path, tmp_path: Path):
        """Minimal workspace must NOT contain orchestrator files."""
        builder = AgentWorkspaceBuilder(target_root=target_root)
        ws = builder.build_scoped_copy(
            scope_paths=["main.py"],
            workspace_root=tmp_path,
            slug="test-ws3",
        )
        files = [str(f.relative_to(ws.workspace_path)) for f in ws.workspace_path.rglob("*") if f.is_file()]
        assert all("grace_control" not in f for f in files)
        assert all("packet_executor" not in f for f in files)

    def test_workspace_result_to_dict(self, target_root: Path, tmp_path: Path):
        builder = AgentWorkspaceBuilder(target_root=target_root)
        ws = builder.build_scoped_copy(
            scope_paths=["main.py"],
            workspace_root=tmp_path,
            slug="test-ws4",
        )
        d = ws.to_dict()
        assert d["workspace_mode"] == "scoped_copy"
        assert d["base_sha"] != ""
        assert len(d["copied_files"]) >= 1
        assert d["commit_semantics"] == "workspace_only"

    def test_build_scoped_copy_has_base_sha(self, target_root: Path, tmp_path: Path):
        """Minimal repo must have its own base SHA (not from target repo)."""
        builder = AgentWorkspaceBuilder(target_root=target_root)
        ws = builder.build_scoped_copy(
            scope_paths=["main.py"],
            workspace_root=tmp_path,
            slug="test-ws5",
        )
        assert ws.base_sha != ""
        assert len(ws.base_sha) == 40  # full SHA

    def test_missing_target_root_raises(self):
        with pytest.raises(ValueError, match="does not exist"):
            AgentWorkspaceBuilder(target_root="/nonexistent/path")

    def test_absolute_path_outside_target_omitted(self, target_root: Path, tmp_path: Path):
        """Paths outside target_root must be omitted, not copied."""
        outside = tmp_path / "outside.txt"
        outside.write_text("should not be copied")
        builder = AgentWorkspaceBuilder(target_root=target_root)
        ws = builder.build_scoped_copy(
            scope_paths=["main.py", str(outside)],
            workspace_root=tmp_path,
            slug="test-safe1",
            config_allowlist=[],
        )
        # The outside file should NOT be in the workspace
        workspace_files = [str(f.relative_to(ws.workspace_path)) for f in ws.workspace_path.rglob("*") if f.is_file()]
        assert all("outside.txt" not in f for f in workspace_files)
        # And should be in omitted_files
        assert any("outside_target_root" in o for o in ws.omitted_files)

    def test_traversal_path_omitted(self, target_root: Path, tmp_path: Path):
        """Paths with .. traversal must be omitted."""
        builder = AgentWorkspaceBuilder(target_root=target_root)
        ws = builder.build_scoped_copy(
            scope_paths=["main.py", "../outside.txt"],
            workspace_root=tmp_path,
            slug="test-safe2",
            config_allowlist=[],
        )
        assert any("unsafe_relative_path" in o or "outside_target_root" in o for o in ws.omitted_files)

    def test_empty_scope_raises_value_error(self, target_root: Path, tmp_path: Path):
        """Empty workspace must raise ValueError."""
        builder = AgentWorkspaceBuilder(target_root=target_root)
        with pytest.raises(ValueError, match="no files copied"):
            builder.build_scoped_copy(
                scope_paths=[],  # no scope files
                workspace_root=tmp_path,
                slug="test-empty",
                config_allowlist=[],  # no config files either
            )

    def test_all_missing_paths_raises(self, target_root: Path, tmp_path: Path):
        """When all scope paths are missing, must raise ValueError."""
        builder = AgentWorkspaceBuilder(target_root=target_root)
        with pytest.raises(ValueError, match="no files copied"):
            builder.build_scoped_copy(
                scope_paths=["nonexistent.py", "missing/foo.py"],
                workspace_root=tmp_path,
                slug="test-missing",
                config_allowlist=[],
            )

    def test_omitted_files_empty_when_all_valid(self, target_root: Path, tmp_path: Path):
        """When all paths are valid, omitted_files should be empty."""
        builder = AgentWorkspaceBuilder(target_root=target_root)
        ws = builder.build_scoped_copy(
            scope_paths=["main.py", "tests/test_main.py"],
            workspace_root=tmp_path,
            slug="test-omit-empty",
            config_allowlist=["pyproject.toml"],
        )
        assert ws.omitted_files == []

    def test_build_target_repo_worktree(self, target_root: Path, tmp_path: Path):
        """Should create a git worktree from target repo."""
        builder = AgentWorkspaceBuilder(target_root=target_root)
        ws_root = tmp_path / "worktrees"
        ws_root.mkdir()
        ws = builder.build_target_repo_worktree(
            workspace_root=ws_root,
            slug="test-wt-slug",
            branch="agent/test-wt-branch",
            base_ref="HEAD",
        )
        assert ws.workspace_path.exists()
        assert (ws.workspace_path / "main.py").exists()
        assert ws.workspace_mode == "target_repo_worktree"
        assert ws.target_repo_root == target_root
        assert ws.base_sha != ""
        assert ws.copied_files == []
        assert ws.omitted_files == []
        assert ws.commit_semantics == "target_repo_commit"

        d = ws.to_dict()
        assert d["workspace_mode"] == "target_repo_worktree"
        assert d["commit_semantics"] == "target_repo_commit"
        assert d["target_repo_root"] == str(target_root)
