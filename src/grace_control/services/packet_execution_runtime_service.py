# ############################################################################
# AI_HEADER: packet_execution_runtime_service — runtime workspace and backend execution
# ROLE: Owns packet runtime preparation details that must stay consistent across
#       workspace creation, session resume, backend execution, and diagnostics.
# ############################################################################

# START_MODULE_CONTRACT
# purpose: Execute a materialized packet in its resolved runtime workspace.
# inputs: Packet contract, execution attempt metadata, adapter dependency facade.
# returns: Backend ExecutionResult with workspace, diagnostics, and session evidence.
# side_effects: Creates worktrees or scoped copies, invokes the backend, writes DB
#               session/base metadata through injected adapter services.
# emitted_logs: Runtime workspace, session, preflight, failure, and diagnostics msg names.
# error_behavior: Returns controlled backend failure results for preflight/workspace
#                 failures and propagates backend exceptions.
# END_MODULE_CONTRACT

# START_MODULE_MAP
# mapping:
#   - class: PacketExecutionRuntimeService
#     methods:
#       - run
#   - function: classify_failure
# END_MODULE_MAP

from __future__ import annotations

import os
from pathlib import Path

from grace_control.core.structured_logger import GraceLogger
from grace_control.db import get_db
from grace_control.services.packet_execution_workspace_service import (
    _BROAD_REPO_VERIFICATION_PATTERNS,
    _attempt_branch,
    _attempt_slug,
    _flatten_verification_for_safety,
    _resolve_worktree_for_contract,
    _verification_unsafe_for_scoped,
    PacketExecutionWorkspaceService,
    RuntimeWorkspacePreparation,
)

_log = GraceLogger("packet_execution_runtime")


# ── Failure classification (TZ §6.7) ─────────────────────────────────────────

import re as _re_classify


def _is_git_worktree(path: str) -> bool:
    """Quick check if a directory is inside a git repo (handles worktrees)."""
    try:
        p = Path(path).resolve()
        while True:
            git_path = p / ".git"
            if git_path.exists():
                return True
            if p.parent == p:
                return False
            p = p.parent
    except Exception:
        return False


def _redact_secrets(text: str) -> str:
    """Redact obvious secrets from log tails. Never expose API keys.

    Conservative: redact long token-like substrings, bearer-style auth
    headers, and URLs with embedded credentials.
    """
    if not text:
        return text
    # Bearer / Authorization headers.
    text = _re_classify.sub(
        r"(?i)(authorization\s*:\s*bearer\s+)[A-Za-z0-9._\-]+",
        r"\1***REDACTED***", text)
    # ENV_VAR=value where value is long and token-like.
    text = _re_classify.sub(
        r"(?i)(\b[A-Z][A-Z0-9_]*(?:_KEY|_TOKEN|_SECRET|_PASSWORD|_URL))\s*=\s*([^\s\"']{12,})",
        r"\1***REDACTED***", text)
    # URL with embedded user:pass@.
    text = _re_classify.sub(
        r"([A-Za-z][A-Za-z0-9+\-.]*://)([^\s/@:]+):([^\s/@]+)@",
        r"\1***:***@", text)
    # Long opaque tokens (40+ alnum/dash/underscore).
    text = _re_classify.sub(
        r"\b[A-Za-z0-9_\-]{40,}\b", "***REDACTED***", text)
    return text


_STDOUT_TAIL_LIMIT = 4000
_STDERR_TAIL_LIMIT = 4000


def _tail(s: str, limit: int) -> str:
    if not s:
        return ""
    if len(s) <= limit:
        return s
    return s[-limit:]


# Diagnostics contract surface (TZ §6.6). Keys persisted at top-level of
# result_json["diagnostics"] for UI/admin/trace to consume without traversing
# legacy_result.evidence.
_DIAGNOSTICS_KEYS = (
    "stdout_tail",
    "stderr_tail",
    "exit_code",
    "duration_ms",
    "failure_stage",
    "failure_class",
    "workspace",
    "session_resume",
)


def _extract_diagnostics(result) -> dict:
    """Pull TZ §6.6 diagnostics out of result.evidence into a top-level dict.

    Always returns a dict; missing keys are simply absent. The legacy
    evidence sub-dict is still kept for back-compat with anything reading
    result_json.legacy_result.evidence.
    """
    out: dict = {}
    try:
        ev = getattr(result, "evidence", {}) or {}
    except Exception:
        ev = {}
    for k in _DIAGNOSTICS_KEYS:
        if k in ev:
            out[k] = ev[k]
    return out


# START_FUNCTION_CONTRACT
# name: classify_failure
# purpose: Classify backend failure output into the stable runtime failure categories.
# inputs: stdout, stderr, exit_code, stage — backend diagnostics and execution stage.
# returns: Stable failure classification string.
# side_effects: None.
# emitted_logs: None.
# error_behavior: Returns "unknown" when no specific category matches.
# END_FUNCTION_CONTRACT
def classify_failure(
    stdout: str,
    stderr: str,
    exit_code: int | None,
    stage: str,
) -> str:
    """Deterministic failure classification (TZ §6.7).

    Returns one of: session_not_found, auth_error, timeout, no_changes,
    scope_violation, t1_failed, agent_commit_failed,
    worktree_preflight_failed, unknown.
    """
    blob = ((stdout or "") + "\n" + (stderr or "")).lower()
    if exit_code is None or exit_code != 0:
        if "timed_out" in stage or "timeout" in stage:
            return "timeout"
    if "session not found" in blob:
        return "session_not_found"
    if any(t in blob for t in ("401", "403", "unauthorized", "api key", "missing key", "authentication")):
        return "auth_error"
    if "timed_out" in stage or "timeout" in stage:
        return "timeout"
    if "no changes" in stage or "no_changes" in stage:
        return "no_changes"
    if "scope_violation" in stage or "scope violation" in blob:
        return "scope_violation"
    if "t1" in stage and "fail" in stage:
        return "t1_failed"
    if "git commit" in blob and "fail" in blob:
        return "agent_commit_failed"
    if "preflight" in stage and "fail" in stage:
        return "worktree_preflight_failed"
    if "worktree" in stage and "issue" in stage:
        return "worktree_issue"
    return "unknown"


# START_BLOCK_RUNTIME_EXECUTION
class PacketExecutionRuntimeService:

    def __init__(self, workspace_service: PacketExecutionWorkspaceService | None = None):
        self._workspace_service = workspace_service or PacketExecutionWorkspaceService()

    # START_FUNCTION_CONTRACT
    # name: run
    # purpose: Prepare a packet workspace, invoke the execution backend, and attach runtime evidence.
    # inputs: adapter, packet_path, packet_contract, attempt, base_ref, base_sha, executor,
    #          evidence_dir, run_id — facade dependencies and execution inputs.
    # returns: Backend ExecutionResult with workspace/session/diagnostics evidence.
    # side_effects: Worktree/scoped-copy creation, backend invocation, DB session/base persistence.
    # emitted_logs: workspace, session, failure classification, and diagnostics events.
    # error_behavior: Returns controlled failed results for unsafe workspace setup; backend errors propagate.
    # END_FUNCTION_CONTRACT
    async def run(self, adapter, packet_path: Path, packet_contract, attempt: int,
                              base_ref: str, base_sha: str, executor: dict,
                              evidence_dir: Path | None = None,
                              run_id: str | None = None,
                              db_factory=None):
        from grace_control.agent.backend import ExecutionRequest
        pid = packet_path.parent.name
        eff = packet_contract.allowed_write_scope

        workspace = self._prepare_workspace(
            adapter,
            pid=pid,
            eff=eff,
            packet_contract=packet_contract,
            attempt=attempt,
            base_ref=base_ref,
            base_sha=base_sha,
            executor=executor,
            run_id=run_id,
        )
        if not isinstance(workspace, RuntimeWorkspacePreparation):
            return workspace

        _preflight_result = workspace.preflight_result
        wt_path = workspace.worktree_path
        branch = workspace.branch_name
        base_sha = workspace.base_sha
        workspace_mode = workspace.workspace_mode
        _workspace_evidence = workspace.workspace_evidence
        _workspace_result = workspace.workspace_result
        _parallel_execution = workspace.parallel_execution

        from grace_control.config.settings import settings

        # TZ_SESSION_RESUME.md Phase 3: resolve resume session before run
        resume_session_id: str | None = None
        prev_internal_id: str | None = None
        fork = False
        resume_mode = executor.get("resume_mode", "never")
        role = executor.get("role", "coder")
        executor_id = executor.get("executor_id", "")

        # TZ: attempt 7+ with NEW_ARCHITECT → fresh session (no resume).
        # Also initial architect (attempt 0) has no session to resume.
        force_fresh = (role == "architect" and attempt >= 7)

        if not force_fresh and resume_mode in ("always", "on_retry", "on_fork") and attempt > 0:
            with (db_factory or get_db)() as db:
                if resume_mode == "on_retry":
                    prev = adapter._session_store.find_latest(
                        db, pid, role, executor_id=executor_id)
                    if prev:
                        resume_session_id = prev.external_id
                        prev_internal_id = prev.id
                elif resume_mode == "on_fork":
                    prev = adapter._session_store.find_for_fork(db, pid, role)
                    if prev:
                        resume_session_id = prev.external_id
                        prev_internal_id = prev.id
                        fork = True
                elif resume_mode == "always":
                    prev = adapter._session_store.find_latest(db, pid, role)
                    if prev:
                        resume_session_id = prev.external_id
                        prev_internal_id = prev.id
                _log.info("session_resolved",
                          packet_id=pid, attempt=attempt, role=role,
                          resume_session_id=resume_session_id, fork=fork)

        try:
            inactivity_timeout = int(os.getenv(
                "GRACE_AGENT_TIMEOUT", str(settings.agent_timeout_seconds)))
        except ValueError:
            inactivity_timeout = settings.agent_timeout_seconds
        req = ExecutionRequest(packet_id=pid,
            spec={"attempt_count":attempt,"base_ref":base_ref,"allowed_write_scope":eff or [],"frozen_scope":packet_contract.frozen_scope or []},
            worktree_path=wt_path, branch_name=branch,
            scope_paths=list(eff or []), executor=executor, timeout_s=inactivity_timeout,
            session_dir=getattr(adapter, "state_root"), evidence_dir=evidence_dir,
            resume_session_id=resume_session_id, fork_session=fork)
        result = await adapter._backend.run(req)

        # TZ_SESSION_RESUME.md Phase 3: save session after run
        if result.evidence.get("session_id"):
            with (db_factory or get_db)() as db:
                adapter._session_store.save(
                    db,
                    packet_id=pid,
                    run_id=f"{pid}-R{attempt:02d}",
                    role=role,
                    executor_id=executor_id,
                    backend=executor.get("backend", "cli"),
                    attempt_number=attempt,
                    external_id=result.evidence.get("session_id"),
                    parent_session_id=prev_internal_id if fork else None,
                    status="completed" if result.accepted else "failed",
                )
        # Persist session_resume audit info in evidence so it appears
        # in PacketRun.result_json for trace and recovery audit trail.
        if resume_session_id:
            result.evidence["session_resume"] = {
                "resume_session_id": resume_session_id,
                "fork": fork,
                "prev_internal_id": prev_internal_id,
            }
        # Persist workspace report in evidence
        _parallel_execution["base_sha"] = base_sha
        result.evidence["parallel_execution"] = dict(_parallel_execution)
        if _workspace_evidence:
            result.evidence["workspace"] = _workspace_evidence
        elif _workspace_result is not None:
            result.evidence["workspace"] = _workspace_result.to_dict()
        elif workspace_mode == "full_git_worktree":
            result.evidence["workspace"] = {"workspace_mode": "full_git_worktree"}

        # TZ §6.6: persist diagnostics contract in evidence for every
        # terminal run. Use fields already on the ExecutionResult.
        try:
            _stdout = getattr(result, "stdout", "") or ""
            _stderr = getattr(result, "stderr", "") or ""
            _stage = "agent_run"
            if not result.accepted:
                # Best-effort stage detection.
                if "agent_commit_failed" in _stderr or "cannot commit" in _stderr:
                    _stage = "agent_commit"
                elif "worktree" in _stderr.lower() and "missing" in _stderr.lower():
                    _stage = "worktree_inspection"
            result.evidence["stdout_tail"] = _redact_secrets(_tail(_stdout, _STDOUT_TAIL_LIMIT))
            result.evidence["stderr_tail"] = _redact_secrets(_tail(_stderr, _STDERR_TAIL_LIMIT))
            result.evidence["exit_code"] = getattr(result, "exit_code", None)
            result.evidence["duration_ms"] = getattr(result, "duration_ms", None)
            result.evidence["failure_stage"] = _stage
            result.evidence["failure_class"] = classify_failure(
                _stdout, _stderr, result.evidence["exit_code"], _stage)
            if result.evidence["failure_class"] != "unknown":
                _log.warn(
                    "failure_classified",
                    packet_id=pid,
                    failure_class=result.evidence["failure_class"],
                    failure_stage=_stage,
                    exit_code=result.evidence["exit_code"],
                )
            else:
                _log.debug("failure_classified",
                           packet_id=pid,
                           failure_class="unknown",
                           failure_stage=_stage)
        except Exception as _e:
            _log.warn("diagnostics_persist_failed", packet_id=pid, reason=str(_e))

        # TZ §6.6: snapshot top-level diagnostics for the upcoming
        # update_run_result call. Anything in result.evidence under one of
        # _DIAGNOSTICS_KEYS is lifted to result_json["diagnostics"] (see
        # evidence_service.update_run_result). This makes UI / admin /
        # trace read the same shape regardless of which code path called
        # the persistence layer.
        #
        # session_resume is included here too: AgentRunService.run() writes
        # the resume decision into the returned dict, UniversalCliAgentBackend
        # stores that dict in ExecutionResult.evidence, and _extract_diagnostics
        # lifts it to the top-level result_json.diagnostics.session_resume.
        try:
            adapter._last_diagnostics = _extract_diagnostics(result)
        except Exception:
            adapter._last_diagnostics = {}

        _log.info("run_diagnostics_persisted",
                  packet_id=pid,
                  accepted=result.accepted,
                  failure_class=result.evidence.get("failure_class"),
                  failure_stage=result.evidence.get("failure_stage"),
                  exit_code=result.evidence.get("exit_code"),
                  has_stderr_tail=bool(result.evidence.get("stderr_tail")),
                  has_stdout_tail=bool(result.evidence.get("stdout_tail")))
        # Persist preflight report if it exists
        if _preflight_result is not None:
            result.evidence["target_repo_preflight"] = _preflight_result.to_dict()
        return result

    # START_FUNCTION_CONTRACT
    # name: _prepare_workspace
    # purpose: Delegate workspace construction to the dedicated workspace service.
    # inputs: adapter, pid, eff, packet contract, attempt, base ref/SHA, executor, run id.
    # returns: RuntimeWorkspacePreparation or a controlled backend failure result.
    # side_effects: Creates/cleans worktrees, branches, scoped copies, and replay seed commits.
    # emitted_logs: workspace mode, preflight, branch, worktree, and rework seed messages.
    # error_behavior: Returns controlled backend failure results for unsafe workspace setup.
    # END_FUNCTION_CONTRACT
    def _prepare_workspace(
        self,
        adapter,
        *,
        pid: str,
        eff,
        packet_contract,
        attempt: int,
        base_ref: str,
        base_sha: str,
        executor: dict,
        run_id: str | None,
    ):
        return self._workspace_service.prepare(
            adapter,
            pid=pid,
            eff=eff,
            packet_contract=packet_contract,
            attempt=attempt,
            base_ref=base_ref,
            base_sha=base_sha,
            executor=executor,
            run_id=run_id,
        )

# END_BLOCK_RUNTIME_EXECUTION
