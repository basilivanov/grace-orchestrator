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
        # The workspace is built from target_root, not from the orchestrator root
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
