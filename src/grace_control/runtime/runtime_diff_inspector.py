from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any, Callable

from pydantic import BaseModel

from grace_control.core.runtime_artifacts import RuntimeArtifactRef, RuntimeArtifactStore
from grace_control.core.runtime_redaction import RuntimeRedactor
from grace_control.core.runtime_trace import RuntimeTraceContext
from grace_control.core.structured_logger import GraceLogger
from grace_control.runtime.agent_runtime_contract import AgentRuntimeFailureCode

_log = GraceLogger("runtime_diff_inspector")

AsyncShellRunner = Callable[[str], tuple[int, str, str]]


async def _real_shell(cmd: str) -> tuple[int, str, str]:
    """Run a shell command via asyncio subprocess — no direct import subprocess."""
    try:
        proc = await asyncio.create_subprocess_exec(
            *cmd.split(), stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        try:
            stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=30)
            return proc.returncode or 0, stdout.decode("utf-8").strip(), stderr.decode("utf-8").strip()
        except asyncio.TimeoutError:
            try:
                proc.kill()
                await proc.wait()
            except Exception:
                pass
            return 1, "", "timeout"
    except FileNotFoundError:
        return 127, "", "binary not found"


async def _noop_shell(cmd: str) -> tuple[int, str, str]:
    return 0, "", ""


class RuntimeDiffInspectionRequest(BaseModel):
    repo_root: str
    worktree_root: str
    base_ref: str | None = None
    allowed_scope: list[str] = []
    frozen_scope: list[str] = []


class RuntimeDiffInspectionResult(BaseModel):
    ok: bool
    changed_files: list[str]
    staged_files: list[str] = []
    unstaged_files: list[str] = []
    untracked_files: list[str] = []
    diff_stat: dict[str, int] = {}
    patch_artifact_ref: RuntimeArtifactRef | None = None
    failure_code: str | None = None
    summary: str = ""


class RuntimeDiffInspector:

    def __init__(self, shell_runner: AsyncShellRunner | None = None):
        self._shell = shell_runner or _real_shell

    async def inspect(self, request: RuntimeDiffInspectionRequest) -> RuntimeDiffInspectionResult:
        cwd = request.worktree_root
        base = request.base_ref or "HEAD"

        try:
            # Critical: base diff must succeed. If git can't compute diff, hard fail.
            rc, out, stderr = await self._run_git(cwd, "diff", "--name-only", base)
            if rc != 0:
                return RuntimeDiffInspectionResult(
                    ok=False, changed_files=[],
                    failure_code=AgentRuntimeFailureCode.AGENT_DIFF_INSPECTION_FAILED,
                    summary=f"git diff failed (rc={rc}): {stderr or out or 'unknown'}",
                )

            changed = [l.strip() for l in out.split("\n") if l.strip()]
            staged = await self._get_staged_files(cwd)
            unstaged = await self._get_unstaged_files(cwd)
            untracked = await self._get_untracked_files(cwd)
            diff_stat = await self._get_diff_stat(cwd, base)

            all_changed = _dedupe(changed + staged + unstaged + untracked)
            return RuntimeDiffInspectionResult(
                ok=True,
                changed_files=all_changed,
                staged_files=staged,
                unstaged_files=unstaged,
                untracked_files=untracked,
                diff_stat=diff_stat,
                summary=f"Found {len(all_changed)} changed files",
            )
        except Exception as e:
            return RuntimeDiffInspectionResult(
                ok=False, changed_files=[],
                failure_code=AgentRuntimeFailureCode.AGENT_DIFF_INSPECTION_FAILED,
                summary=str(e),
            )

    async def _run_git(self, cwd: str, *args: str) -> tuple[int, str, str]:
        cmd = "git -C " + _quote(cwd) + " " + " ".join(_quote(a) for a in args)
        return await self._shell(cmd)

    async def _get_changed_files(self, cwd: str, base: str) -> list[str]:
        rc, out, _ = await self._run_git(cwd, "diff", "--name-only", base)
        if rc != 0:
            return []
        return [l.strip() for l in out.split("\n") if l.strip()]

    async def _get_staged_files(self, cwd: str) -> list[str]:
        rc, out, _ = await self._run_git(cwd, "diff", "--cached", "--name-only")
        if rc != 0:
            return []
        return [l.strip() for l in out.split("\n") if l.strip()]

    async def _get_unstaged_files(self, cwd: str) -> list[str]:
        rc, out, _ = await self._run_git(cwd, "diff", "--name-only")
        if rc != 0:
            return []
        return [l.strip() for l in out.split("\n") if l.strip()]

    async def _get_untracked_files(self, cwd: str) -> list[str]:
        rc, out, _ = await self._run_git(cwd, "ls-files", "--others", "--exclude-standard")
        if rc != 0:
            return []
        return [l.strip() for l in out.split("\n") if l.strip()]

    async def _get_diff_stat(self, cwd: str, base: str) -> dict[str, int]:
        rc, out, _ = await self._run_git(cwd, "diff", "--shortstat", base)
        if rc != 0:
            return {}
        stat: dict[str, int] = {}
        parts = out.split(",")
        for part in parts:
            part = part.strip()
            if "insertion" in part:
                nums = [int(s) for s in part.split() if s.isdigit()]
                if nums:
                    stat["insertions"] = nums[0]
            elif "deletion" in part:
                nums = [int(s) for s in part.split() if s.isdigit()]
                if nums:
                    stat["deletions"] = nums[0]
            elif "file" in part:
                nums = [int(s) for s in part.split() if s.isdigit()]
                if nums:
                    stat["files_changed"] = nums[0]
        return stat


def _quote(s: str) -> str:
    return s.replace("'", "'\\''")


def _dedupe(items: list[str]) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for item in items:
        if item not in seen:
            seen.add(item)
            out.append(item)
    return out
