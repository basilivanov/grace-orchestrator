from __future__ import annotations

import json
import os
import subprocess
import tempfile
from pathlib import Path
from typing import Any, Callable

from pydantic import BaseModel

from grace_control.config.settings import settings
from grace_control.core.runtime_artifacts import RuntimeArtifactRef, RuntimeArtifactStore
from grace_control.core.runtime_trace import RuntimeTraceContext
from grace_control.runtime.agent_runtime_contract import (
    AgentRuntimeContract,
    AgentRuntimeFailureCode,
)
from grace_control.core.structured_logger import GraceLogger

_log = GraceLogger("runtime_selftest")


class RuntimeCheck(BaseModel):
    check_id: str
    ok: bool
    expected: str | None = None
    actual: str | None = None
    details: str | None = None
    failure_code: str | None = None


class AgentRuntimeSelftestResult(BaseModel):
    ok: bool
    failure_code: str | None = None
    summary: str
    checks: list[RuntimeCheck]


# Shell runner abstraction for CI/mockability
ShellRunner = Callable[[str], tuple[int, str, str]]


def _real_shell(cmd: str) -> tuple[int, str, str]:
    try:
        r = subprocess.run(
            cmd, shell=False, capture_output=True, text=True, timeout=30,
        )
        return r.returncode, r.stdout.strip(), r.stderr.strip()
    except subprocess.TimeoutExpired:
        return 1, "", "timeout"
    except FileNotFoundError:
        return 127, "", "binary not found"


def _noop_shell(cmd: str) -> tuple[int, str, str]:
    return 0, "", ""


# ── Check IDs ────────────────────────────────────────────────────────────

CHECK_CONTRACT_HAS_PACKET_ID = "CHECK_CONTRACT_HAS_PACKET_ID"
CHECK_CONTRACT_HAS_TARGET_REPO_ROOT = "CHECK_CONTRACT_HAS_TARGET_REPO_ROOT"
CHECK_TARGET_REPO_EXISTS = "CHECK_TARGET_REPO_EXISTS"
CHECK_ORCHESTRATOR_REPO_EXISTS = "CHECK_ORCHESTRATOR_REPO_EXISTS"
CHECK_WORKTREE_ROOT_EXISTS = "CHECK_WORKTREE_ROOT_EXISTS"
CHECK_CWD_EQUALS_WORKTREE_ROOT = "CHECK_CWD_EQUALS_WORKTREE_ROOT"
CHECK_GIT_ROOT_EQUALS_WORKTREE_ROOT = "CHECK_GIT_ROOT_EQUALS_WORKTREE_ROOT"
CHECK_TARGET_REPO_NOT_ORCHESTRATOR_REPO_WHEN_TARGET_MODE = (
    "CHECK_TARGET_REPO_NOT_ORCHESTRATOR_REPO_WHEN_TARGET_MODE"
)
CHECK_PACKET_SCOPE_RELATIVE = "CHECK_PACKET_SCOPE_RELATIVE"
CHECK_SCOPE_PARENT_EXISTS_OR_CREATABLE = "CHECK_SCOPE_PARENT_EXISTS_OR_CREATABLE"
CHECK_FROZEN_SCOPE_NO_OVERLAP = "CHECK_FROZEN_SCOPE_NO_OVERLAP"
CHECK_ARTIFACT_DIR_WRITABLE = "CHECK_ARTIFACT_DIR_WRITABLE"
CHECK_WORKTREE_DIRTY_BEFORE_RUN = "CHECK_WORKTREE_DIRTY_BEFORE_RUN"
CHECK_OPENCODE_BINARY_AVAILABLE = "CHECK_OPENCODE_BINARY_AVAILABLE"
CHECK_OPENCODE_AUTH_VISIBLE = "CHECK_OPENCODE_AUTH_VISIBLE"
CHECK_OPENCODE_MODEL_CONFIG_PRESENT = "CHECK_OPENCODE_MODEL_CONFIG_PRESENT"


class AgentRuntimeSelftest:

    def __init__(
        self,
        shell_runner: ShellRunner | None = None,
        store: RuntimeArtifactStore | None = None,
    ):
        self._shell = shell_runner or _real_shell
        self._store = store or RuntimeArtifactStore()
        self._checks: list[RuntimeCheck] = []

    def run(
        self,
        contract: AgentRuntimeContract,
        trace: RuntimeTraceContext,
    ) -> AgentRuntimeSelftestResult:
        self._checks = []

        self._check(CHECK_CONTRACT_HAS_PACKET_ID,
                     ok=bool(contract.packet_id),
                     expected="non-empty packet_id",
                     actual=contract.packet_id or "(empty)",
                     failure_code=AgentRuntimeFailureCode.AGENT_RUNTIME_CONTRACT_INVALID if not contract.packet_id else None)

        self._check(CHECK_CONTRACT_HAS_TARGET_REPO_ROOT,
                     ok=bool(contract.target_repo_root),
                     expected="non-empty target_repo_root",
                     actual=contract.target_repo_root or "(empty)",
                     failure_code=AgentRuntimeFailureCode.AGENT_RUNTIME_CONTRACT_INVALID if not contract.target_repo_root else None)

        target_repo_exists = Path(contract.target_repo_root).is_dir()
        self._check(CHECK_TARGET_REPO_EXISTS,
                     ok=target_repo_exists,
                     expected=f"directory exists: {contract.target_repo_root}",
                     actual="exists" if target_repo_exists else "not found",
                     failure_code=AgentRuntimeFailureCode.AGENT_TARGET_REPO_NOT_FOUND if not target_repo_exists else None)

        orchestrator_repo_exists = Path(contract.orchestrator_repo_root).is_dir()
        self._check(CHECK_ORCHESTRATOR_REPO_EXISTS,
                     ok=orchestrator_repo_exists,
                     expected=f"directory exists: {contract.orchestrator_repo_root}",
                     actual="exists" if orchestrator_repo_exists else "not found",
                     failure_code=AgentRuntimeFailureCode.AGENT_ORCHESTRATOR_REPO_NOT_FOUND if not orchestrator_repo_exists else None)

        # The worktree slug directory is created inside _call_executor.
        # Check that the parent worktree root infrastructure exists.
        wt_infra = Path(contract.worktree_root).parent
        wt_infra_exists = wt_infra.is_dir()
        self._check(CHECK_WORKTREE_ROOT_EXISTS,
                     ok=wt_infra_exists,
                     expected=f"worktree infra dir exists: {wt_infra}",
                     actual="exists" if wt_infra_exists else "not found",
                     failure_code=AgentRuntimeFailureCode.AGENT_WORKTREE_INVALID if not wt_infra_exists else None)

        cwd_matches = contract.cwd == contract.worktree_root
        self._check(CHECK_CWD_EQUALS_WORKTREE_ROOT,
                     ok=cwd_matches,
                     expected=f"cwd == worktree_root ({contract.worktree_root})",
                     actual=contract.cwd,
                     failure_code=AgentRuntimeFailureCode.AGENT_ENV_BAD_CWD if not cwd_matches and getattr(settings, "agent_runtime_fail_on_bad_cwd", True) else None)

        # Git root check — use the target repo root (worktree not yet created)
        git_check_root = contract.target_repo_root
        rc, git_root, _ = self._shell(f"git -C {_quote(git_check_root)} rev-parse --show-toplevel 2>/dev/null")
        git_root_ok = rc == 0 and git_root == git_check_root
        self._check(CHECK_GIT_ROOT_EQUALS_WORKTREE_ROOT,
                     ok=git_root_ok,
                     expected=f"git root == target_repo_root ({git_check_root})",
                     actual=git_root if rc == 0 else "(not a git repo)",
                     failure_code=AgentRuntimeFailureCode.AGENT_ENV_BAD_GIT_ROOT if not git_root_ok and getattr(settings, "agent_runtime_fail_on_bad_git_root", True) else None)

        # Dirty worktree check on target repo (soft warning by default)
        if rc == 0:
            _, status_out, _ = self._shell(f"git -C {_quote(git_check_root)} status --porcelain 2>/dev/null")
            dirty = bool(status_out.strip())
            self._check(CHECK_WORKTREE_DIRTY_BEFORE_RUN,
                             ok=not dirty,
                             expected="clean worktree",
                             actual="dirty" if dirty else "clean",
                             failure_code=AgentRuntimeFailureCode.AGENT_WORKTREE_DIRTY_BEFORE_RUN if dirty and getattr(settings, "agent_runtime_fail_on_dirty_worktree", False) else None)

        # Target repo != orchestrator repo check
        try:
            are_same = Path(contract.target_repo_root).resolve() == Path(contract.orchestrator_repo_root).resolve()
        except Exception:
            are_same = contract.target_repo_root == contract.orchestrator_repo_root
        is_target_mode = contract.target_repo_root != contract.orchestrator_repo_root
        self._check(CHECK_TARGET_REPO_NOT_ORCHESTRATOR_REPO_WHEN_TARGET_MODE,
                     ok=not is_target_mode or not are_same,
                     expected="target_repo_root != orchestrator_repo_root when in target mode",
                     actual="same path" if are_same else "different",
                     failure_code=None)

        # Scope checks
        all_scope = list(contract.packet_scope) + list(contract.frozen_scope)
        for p in contract.packet_scope:
            is_rel = not p.startswith("/") and ".." not in p.split("/")
            self._check_custom(
                CHECK_PACKET_SCOPE_RELATIVE,
                ok=is_rel,
                expected=f"relative path, no '..': {p}",
                actual=p,
                failure_code=AgentRuntimeFailureCode.AGENT_SCOPE_PATH_INVALID if not is_rel else None,
            )
            if is_rel:
                parent = Path(contract.worktree_root) / Path(p).parent if Path(p).parent != Path(".") else Path(contract.worktree_root)
                creatable = parent.exists() or _is_creatable(parent)
                self._check(CHECK_SCOPE_PARENT_EXISTS_OR_CREATABLE,
                             ok=creatable,
                             expected=f"parent exists or creatable: {parent}",
                             actual="exists" if parent.exists() else "creatable" if creatable else "not creatable",
                             failure_code=AgentRuntimeFailureCode.AGENT_SCOPE_PARENT_NOT_CREATABLE if not creatable else None)

        # Frozen scope overlap check
        overlap = [s for s in contract.frozen_scope if s in contract.packet_scope]
        self._check(CHECK_FROZEN_SCOPE_NO_OVERLAP,
                     ok=not overlap,
                     expected="no overlap between frozen_scope and packet_scope",
                     actual=f"overlapping: {overlap}" if overlap else "none",
                     failure_code=AgentRuntimeFailureCode.AGENT_FROZEN_SCOPE_OVERLAP if overlap else None)

        # Artifact dir writability — try to create dir + probe file
        try:
            probe_dir = Path(contract.runtime_artifacts_dir)
            probe_dir.mkdir(parents=True, exist_ok=True)
            probe = probe_dir / ".w3_selftest_probe"
            probe.write_text("probe")
            probe.unlink()
            writable = True
            # Remove empty dir to avoid orphaned directories when selftest
            # runs without observability (no artifacts will be written later).
            try:
                probe_dir.rmdir()
            except OSError:
                pass  # not empty — another process wrote something, leave it
        except Exception:
            writable = False
        self._check(CHECK_ARTIFACT_DIR_WRITABLE,
                     ok=writable,
                     expected=f"writable: {probe_dir}",
                     actual="writable" if writable else "not writable",
                     failure_code=AgentRuntimeFailureCode.AGENT_ARTIFACT_DIR_NOT_WRITABLE if not writable else None)

        # OpenCode checks
        self._run_opencode_checks(contract)

        # Determine overall result — build critical set dynamically
        critical_codes = [
            AgentRuntimeFailureCode.AGENT_ENV_BAD_USER,
            AgentRuntimeFailureCode.AGENT_ENV_BAD_HOME,
            AgentRuntimeFailureCode.AGENT_ENV_BAD_CWD,
            AgentRuntimeFailureCode.AGENT_ENV_BAD_GIT_ROOT,
            AgentRuntimeFailureCode.AGENT_WORKTREE_INVALID,
            AgentRuntimeFailureCode.AGENT_SCOPE_PARENT_NOT_CREATABLE,
            AgentRuntimeFailureCode.AGENT_ARTIFACT_DIR_NOT_WRITABLE,
            AgentRuntimeFailureCode.AGENT_RUNTIME_CONTRACT_INVALID,
            AgentRuntimeFailureCode.AGENT_SCOPE_PATH_INVALID,
            AgentRuntimeFailureCode.AGENT_FROZEN_SCOPE_OVERLAP,
            AgentRuntimeFailureCode.AGENT_TARGET_REPO_NOT_FOUND,
            AgentRuntimeFailureCode.AGENT_ORCHESTRATOR_REPO_NOT_FOUND,
        ]
        if getattr(settings, "agent_runtime_require_opencode_auth", False):
            critical_codes.append(AgentRuntimeFailureCode.AGENT_ENV_MISSING_AUTH)
        if getattr(settings, "agent_runtime_require_model_config", False):
            critical_codes.append(AgentRuntimeFailureCode.AGENT_MODEL_UNAVAILABLE)
        critical = self._checks_failing_with_codes(critical_codes)

        if critical:
            fc = critical[0].failure_code
            return AgentRuntimeSelftestResult(
                ok=False, failure_code=fc,
                summary=f"Runtime selftest failed: {fc}",
                checks=self._checks,
            )

        return AgentRuntimeSelftestResult(
            ok=True, failure_code=None, summary="All runtime checks passed",
            checks=self._checks,
        )

    def persist(
        self,
        result: AgentRuntimeSelftestResult,
        trace: RuntimeTraceContext,
    ) -> RuntimeArtifactRef | None:
        try:
            return self._store.write_packet_json(
                trace=trace,
                packet_id=trace.packet_id or "",
                name="runtime_selftest.json",
                payload=result.model_dump(),
                kind="runtime_selftest",
            )
        except Exception as exc:
            _log.warn("selftest_persist_failed", error=str(exc)[:200])
            return None

    def _check(
        self,
        check_id: str,
        ok: bool,
        expected: str | None = None,
        actual: str | None = None,
        failure_code: str | None = None,
    ) -> RuntimeCheck:
        c = RuntimeCheck(check_id=check_id, ok=ok, expected=expected, actual=actual, failure_code=failure_code)
        self._checks.append(c)
        return c

    def _check_custom(self, check_id: str, ok: bool, expected: str | None = None, actual: str | None = None, failure_code: str | None = None) -> RuntimeCheck:
        return self._check(check_id, ok, expected, actual, failure_code)

    def _checks_failing_with_codes(self, codes: list[str]) -> list[RuntimeCheck]:
        return [c for c in self._checks if not c.ok and c.failure_code in codes]

    def _run_opencode_checks(self, contract: AgentRuntimeContract) -> None:
        strict_auth = getattr(settings, "agent_runtime_require_opencode_auth", False)
        strict_model = getattr(settings, "agent_runtime_require_model_config", False)

        # Check opencode binary
        rc, out, _ = self._shell("command -v opencode 2>/dev/null")
        opencode_available = rc == 0
        self._check(CHECK_OPENCODE_BINARY_AVAILABLE,
                     ok=opencode_available,
                     expected="opencode binary on PATH",
                     actual=out if opencode_available else "not found",
                     failure_code=None)

        if opencode_available:
            # Auth check
            rc_auth, auth_out, _ = self._shell("opencode auth list 2>/dev/null")
            auth_ok = rc_auth == 0 and bool(auth_out.strip())
            auth_failure = AgentRuntimeFailureCode.AGENT_ENV_MISSING_AUTH if strict_auth else None
            self._check(CHECK_OPENCODE_AUTH_VISIBLE,
                         ok=auth_ok or not strict_auth,
                         expected="opencode auth configured" if strict_auth else "opencode auth (soft)",
                         actual=auth_out if auth_out else "(none detected)",
                         failure_code=auth_failure)

            # Model config check
            rc_model, model_out, _ = self._shell("opencode models 2>/dev/null")
            model_ok = rc_model == 0 and bool(model_out.strip())
            model_failure = AgentRuntimeFailureCode.AGENT_MODEL_UNAVAILABLE if strict_model else None
            self._check(CHECK_OPENCODE_MODEL_CONFIG_PRESENT,
                         ok=model_ok or not strict_model,
                         expected="opencode models configured" if strict_model else "opencode models (soft)",
                         actual=model_out if model_out else "(none detected)",
                         failure_code=model_failure)


def _quote(s: str) -> str:
    return s.replace("'", "'\\''")


def _is_creatable(path: Path) -> bool:
    try:
        parent = path.parent if not path.exists() else path
        while not parent.exists():
            parent = parent.parent
        return os.access(str(parent), os.W_OK | os.X_OK)
    except Exception:
        return False
