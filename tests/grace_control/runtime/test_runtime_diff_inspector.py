from __future__ import annotations

import pytest

from grace_control.runtime.runtime_diff_inspector import (
    RuntimeDiffInspector,
    RuntimeDiffInspectionRequest,
)
from grace_control.runtime.agent_runtime_contract import AgentRuntimeFailureCode

pytestmark = pytest.mark.asyncio


def _making_shell(stdout_map: dict[str, str]):
    """Create an async shell runner that matches on argv content."""

    async def _run(argv: list[str]) -> tuple[int, str, str]:
        joined = " ".join(argv)
        for pattern, out in stdout_map.items():
            if pattern in joined:
                return 0, out, ""
        return 0, "", ""

    return _run


class TestDiffInspectorUnit:

    async def test_detects_changed_files(self):
        shell = _making_shell({
            "diff --name-only HEAD": "src/foo.py\nsrc/bar.py",
            "diff --cached --name-only": "",
            "diff --name-only": "",
            "ls-files --others --exclude-standard": "",
            "diff --shortstat HEAD": " 2 files changed, 5 insertions(+)",
        })
        inspector = RuntimeDiffInspector(shell_runner=shell)
        result = await inspector.inspect(RuntimeDiffInspectionRequest(
            repo_root="/tmp", worktree_root="/tmp/wt", base_ref="HEAD",
        ))
        assert result.ok
        assert "src/foo.py" in result.changed_files
        assert "src/bar.py" in result.changed_files

    async def test_detects_untracked_files(self):
        shell = _making_shell({
            "diff --name-only HEAD": "",
            "diff --cached --name-only": "",
            "diff --name-only": "",
            "ls-files --others --exclude-standard": "new_file.py\nuntracked.py",
            "diff --shortstat HEAD": "",
        })
        inspector = RuntimeDiffInspector(shell_runner=shell)
        result = await inspector.inspect(RuntimeDiffInspectionRequest(
            repo_root="/tmp", worktree_root="/tmp/wt", base_ref="HEAD",
        ))
        assert result.ok
        assert "new_file.py" in result.changed_files
        assert "untracked.py" in result.changed_files
        assert "new_file.py" in result.untracked_files

    async def test_handles_git_failure(self):
        async def _fail(argv: list[str]) -> tuple[int, str, str]:
            return 128, "", "fatal: not a git repository"

        inspector = RuntimeDiffInspector(shell_runner=_fail)
        result = await inspector.inspect(RuntimeDiffInspectionRequest(
            repo_root="/tmp", worktree_root="/tmp/wt", base_ref="main",
        ))
        assert not result.ok
        assert result.failure_code == AgentRuntimeFailureCode.AGENT_DIFF_INSPECTION_FAILED

    async def test_staged_diff_failure_fails_closed(self):
        async def _fail_staged(argv: list[str]) -> tuple[int, str, str]:
            joined = " ".join(argv)
            if "diff --name-only HEAD" in joined:
                return 0, "src/foo.py", ""
            if "diff --cached --name-only" in joined:
                return 1, "", "staged error"
            return 0, "", ""

        inspector = RuntimeDiffInspector(shell_runner=_fail_staged)
        result = await inspector.inspect(RuntimeDiffInspectionRequest(
            repo_root="/tmp", worktree_root="/tmp/wt", base_ref="HEAD",
        ))
        assert not result.ok
        assert result.failure_code == AgentRuntimeFailureCode.AGENT_DIFF_INSPECTION_FAILED

    async def test_shortstat_failure_does_not_hide_changed_files(self):
        async def _fail_shortstat(argv: list[str]) -> tuple[int, str, str]:
            joined = " ".join(argv)
            if "diff --shortstat" in joined:
                return 1, "", "shortstat error"
            if "diff --name-only HEAD" in joined:
                return 0, "src/foo.py\nsrc/bar.py", ""
            return 0, "", ""

        inspector = RuntimeDiffInspector(shell_runner=_fail_shortstat)
        result = await inspector.inspect(RuntimeDiffInspectionRequest(
            repo_root="/tmp", worktree_root="/tmp/wt", base_ref="HEAD",
        ))
        assert result.ok
        assert "src/foo.py" in result.changed_files
