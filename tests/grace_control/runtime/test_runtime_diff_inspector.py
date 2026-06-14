from __future__ import annotations

from pathlib import Path

import pytest

from grace_control.runtime.runtime_diff_inspector import (
    RuntimeDiffInspector,
    RuntimeDiffInspectionRequest,
)


def _making_shell(stdout_map: dict[str, str]) -> callable:
    """Create a shell runner that returns predefined output per command."""

    def _run(cmd: str) -> tuple[int, str, str]:
        for pattern, out in stdout_map.items():
            if pattern in cmd:
                return 0, out, ""
        return 0, "", ""

    return _run


class TestDiffInspectorUnit:

    def test_detects_changed_files(self):
        shell = _making_shell({
            "diff --name-only HEAD": "src/foo.py\nsrc/bar.py",
            "diff --cached --name-only": "",
            "diff --name-only": "",
            "ls-files --others --exclude-standard": "",
            "diff --shortstat HEAD": " 2 files changed, 5 insertions(+)",
        })
        inspector = RuntimeDiffInspector(shell_runner=shell)
        result = inspector.inspect(RuntimeDiffInspectionRequest(
            repo_root="/tmp", worktree_root="/tmp/wt", base_ref="HEAD",
        ))
        assert result.ok
        assert "src/foo.py" in result.changed_files
        assert "src/bar.py" in result.changed_files

    def test_detects_untracked_files(self):
        shell = _making_shell({
            "diff --name-only HEAD": "",
            "diff --cached --name-only": "",
            "diff --name-only": "",
            "ls-files --others --exclude-standard": "new_file.py\nuntracked.py",
            "diff --shortstat HEAD": "",
        })
        inspector = RuntimeDiffInspector(shell_runner=shell)
        result = inspector.inspect(RuntimeDiffInspectionRequest(
            repo_root="/tmp", worktree_root="/tmp/wt", base_ref="HEAD",
        ))
        assert result.ok
        assert "new_file.py" in result.changed_files
        assert "untracked.py" in result.changed_files
        assert "new_file.py" in result.untracked_files

    def test_handles_git_failure(self):
        def _fail(cmd: str) -> tuple[int, str, str]:
            return 128, "", "fatal: not a git repository"
        inspector = RuntimeDiffInspector(shell_runner=_fail)
        result = inspector.inspect(RuntimeDiffInspectionRequest(
            repo_root="/tmp", worktree_root="/tmp/wt", base_ref="main",
        ))
        # Git failure with no files and no git binary — result is ok with empty changes
        # (non-zero git exit returns [], which means no changes detected, not a crash)
        assert result.ok
        assert result.changed_files == []
