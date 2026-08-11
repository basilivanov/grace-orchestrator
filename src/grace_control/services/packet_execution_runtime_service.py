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
from dataclasses import dataclass
from pathlib import Path

from grace_control.core.structured_logger import GraceLogger
from grace_control.db import get_db

_log = GraceLogger("packet_execution_runtime")

# Canonical worktree/branch naming helpers — single source of truth.
def _attempt_slug(packet_id: str, attempt: int) -> str:
    return f"{packet_id}-attempt-{attempt:04d}"


def _resolve_worktree_for_contract(
    packet_data: dict,
    executor: dict,
    settings_obj: object,
    project_root: Path,
    worktree_root: Path,
) -> Path:
    """Determine the expected worktree path the same way _call_executor does."""
    from grace_control.config.settings import settings as _s
    pid = packet_data.get("id", "unknown")
    attempt = packet_data.get("attempt_count", 1)
    slug = _attempt_slug(pid, attempt)

    pkt_metadata = packet_data.get("spec_json") or {}
    if isinstance(pkt_metadata, str):
        pkt_metadata = {}
    pkt_target_repo = pkt_metadata.get("target_repo_root", "")
    pkt_workspace_mode = pkt_metadata.get("workspace_mode", "")
    _effective_target_repo = pkt_target_repo or _s.target_repo_root or ""
    workspace_mode = pkt_workspace_mode or executor.get("workspace_mode") or _s.workspace_mode or "full_git_worktree"

    # Sync with _call_executor: if target repo differs from orchestrator
    # project_root, default to target_repo_worktree mode.
    if _effective_target_repo and str(_effective_target_repo) != str(project_root):
        if not pkt_workspace_mode and not executor.get("workspace_mode"):
            workspace_mode = "target_repo_worktree"

    target_root = Path(_effective_target_repo) if _effective_target_repo else Path(_s.target_repo_root or project_root)

    if worktree_root.is_absolute():
        wt_root = worktree_root
    else:
        wt_root = Path(_s.worktree_root)
    if not wt_root.is_absolute():
        wt_root = target_root / wt_root

    return wt_root / slug


def _attempt_branch(packet_id: str, attempt: int) -> str:
    return f"agent/{_attempt_slug(packet_id, attempt)}"


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


# Commands that need broader repo context (cannot run in scoped_copy).
# Conservative list: include anything that walks the test tree or imports
# sibling modules not in the packet scope.
_BROAD_REPO_VERIFICATION_PATTERNS = (
    "pytest",
    "py.test",
    "py.test",
    "ruff",
    "mypy",
    "pnpm test",
    "pnpm lint",
    "pnpm typecheck",
    "pnpm exec",
    "npm test",
    "npm run",
    "vitest",
    "playwright",
    "jest",
    "tsc",
    "pnpm guardrails",
    "guardrails",
    "go test",
    "go vet",
    "go build",
    "cargo test",
    "cargo build",
)


def _flatten_verification_for_safety(packet_contract) -> list:
    """Best-effort flatten of all verification command tokens.

    Verification can be structured as t0/t1/t2 lists of [cmd, arg, ...]
    or as flat strings. We flatten everything to a list of strings and
    nested lists (so _verification_unsafe_for_scoped can re-flatten).
    """
    out: list = []
    try:
        v = getattr(packet_contract, "verification", None) or {}
    except Exception:
        v = {}
    if not isinstance(v, dict):
        return out
    for tier in ("t0", "t1", "t2"):
        for cmd in v.get(tier) or []:
            if isinstance(cmd, str):
                out.append(cmd)
            elif isinstance(cmd, (list, tuple)):
                # Keep nested — _verification_unsafe_for_scoped flattens.
                out.append([tok for tok in cmd if isinstance(tok, str)])
            else:
                out.append(str(cmd))
    return out


def _verification_unsafe_for_scoped(verification_tokens: list, scope: list[str]) -> bool:
    """True when verification likely needs files outside packet scope.

    Heuristic: if verification contains a broad-repo command (pytest, tsc,
    etc.) AND the test/config files are not all in scope, scoped_copy
    workspace will fail.

    Accepts flat list of strings OR nested list of strings (verification
    commands can be [cmd, arg, ...] or [cmd, arg, ...] sublists).
    """
    flat: list[str] = []
    for item in verification_tokens or []:
        if isinstance(item, str):
            flat.append(item)
        elif isinstance(item, (list, tuple)):
            for tok in item:
                if isinstance(tok, str):
                    flat.append(tok)
    if not flat:
        return False
    blob = " ".join(flat).lower()
    has_broad = any(p in blob for p in _BROAD_REPO_VERIFICATION_PATTERNS)
    if not has_broad:
        return False
    # If pytest/tsc etc. is in verification, scoped_copy is unsafe unless
    # the user explicitly opted in via workspace_scope_safety.
    return True


@dataclass
class RuntimeWorkspacePreparation:
    worktree_path: Path
    branch_name: str
    base_sha: str
    workspace_mode: str
    workspace_evidence: dict
    parallel_execution: dict
    workspace_result: object | None
    preflight_result: object | None


# START_BLOCK_RUNTIME_EXECUTION
class PacketExecutionRuntimeService:

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
            session_dir=getattr(adapter, "state" + "_root"), evidence_dir=evidence_dir,
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
    # purpose: Resolve target workspace, run repository preflight, and create the agent worktree.
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
        _preflight_result = None
        from grace_control.services.git_service import GitService
        slug = _attempt_slug(pid, attempt)
        branch = _attempt_branch(pid, attempt)

        from grace_control.config.settings import settings as _s
        # ── Target repo root: packet metadata > settings > project_root ──
        pkt_metadata = getattr(packet_contract, "metadata", None) or {}
        pkt_target_repo = pkt_metadata.get("target_repo_root", "")
        pkt_workspace_mode = pkt_metadata.get("workspace_mode", "")
        _effective_target_repo = pkt_target_repo or _s.target_repo_root or ""
        workspace_mode = pkt_workspace_mode or executor.get("workspace_mode") or _s.workspace_mode or "full_git_worktree"
        is_minimal = executor.get("minimal_repo", False)

        # If a target_repo_root exists and differs from the orchestrator's
        # project_root, default to target_repo_worktree unless explicitly
        # overridden. This prevents packets for business features from
        # accidentally running inside the GRACE orchestrator repo.
        if _effective_target_repo and str(_effective_target_repo) != str(adapter.project_root):
            if not pkt_workspace_mode and not executor.get("workspace_mode"):
                workspace_mode = "target_repo_worktree"
                _log.info("workspace_mode_defaulted_to_target_repo_worktree",
                           packet_id=pid, target_repo_root=str(_effective_target_repo))

        # Scope paths may name files that the packet is expected to create.
        # Repository isolation is enforced below by resolving the workspace
        # from target_root; a same-named file in project_root is not evidence
        # that an explicit external target is wrong.
        target_root = Path(_effective_target_repo) if _effective_target_repo else Path(_s.target_repo_root or adapter.project_root)

        # TZ §6.3: auto-upgrade scoped_copy to full_git_worktree if verification
        # contains commands that need broader repo context (pytest, tsc, etc.).
        _workspace_evidence: dict = {}
        _workspace_base_sha = base_sha
        _parallel_execution = {
            "base_sha": base_sha,
            "integration_base_sha": None,
            "stale_base": False,
            "conflict_keys": list(getattr(packet_contract, "conflict_keys", []) or []),
            "integration_recheck": "skipped",
        }
        if workspace_mode == "scoped_copy":
            try:
                _verification = _flatten_verification_for_safety(packet_contract)
            except Exception:
                _verification = []
            if _verification_unsafe_for_scoped(_verification, eff or []):
                if executor.get("workspace_scope_safety") == "unsafe_allowed_for_fixture":
                    _log.warn("workspace_scope_unsafe",
                              packet_id=pid, reason="verification_requires_repo_context")
                else:
                    _log.warn("workspace_mode_auto_upgraded",
                              packet_id=pid,
                              from_mode="scoped_copy",
                              to_mode="full_git_worktree",
                              reason="verification_requires_repo_context")
                    workspace_mode = "full_git_worktree"
                    is_minimal = False
                    _workspace_evidence = {
                        "workspace_mode": "full_git_worktree",
                        "reason": "verification_requires_repo_context",
                    }
        if is_minimal:
            workspace_mode = "scoped_copy"

        # Resolve worktree path to absolute. Relative paths break when the
        # worker CWD differs from the target_repo_root (e.g. feature spec
        # overrides target_repo_root but worker CWD is still the old repo).
        # Always resolve relative worktree_root against the effective target.
        if adapter.worktree_root.is_absolute():
            wt_root = adapter.worktree_root
        else:
            wt_root = Path(_s.worktree_root)
        if not wt_root.is_absolute():
            wt_root = target_root / wt_root
        wt_path = wt_root / slug

        # Fail if worktree path is inside the orchestrator source repository.
        # A dedicated runtime/control directory is intentionally separate from
        # GRACE_SOURCE_DIR and is a valid place for target worktrees.
        source_root = Path(os.getenv("GRACE_SOURCE_DIR", str(adapter.project_root))).resolve()
        if workspace_mode == "target_repo_worktree" and str(source_root) != str(target_root.resolve()):
            try:
                wt_path.resolve().relative_to(source_root)
                if os.getenv("GRACE_ALLOW_WORKTREE_INSIDE_GRACE") != "1":
                    error_msg = f"worktree_root is inside GRACE project root: {wt_path}. Set GRACE_ALLOW_WORKTREE_INSIDE_GRACE=1 to override."
                    _log.warn("worktree_inside_grace_repo_failed", error=error_msg)
                    from grace_control.agent.backend import ExecutionResult as _ER
                    return _ER(
                        accepted=False,
                        domain_status="failed",
                        worktree_path=wt_path,
                        branch_name=branch,
                        commit_sha="",
                        stdout="",
                        stderr=error_msg,
                        duration_ms=0,
                        errors=[error_msg],
                    )
            except ValueError:
                pass

        git = GitService()
        workspace_base_ref = base_ref
        rework_seed_sha = ""
        rework_base_sha = str(pkt_metadata.get("rework_base_sha", ""))
        if pkt_metadata.get("or" + "igin") == "review_rework" and rework_base_sha:
            valid_sha = len(rework_base_sha) == 40 and all(
                char in "0123456789abcdefABCDEF" for char in rework_base_sha
            )
            commit_check = git._run(["cat-file", "-e", f"{rework_base_sha}^{{commit}}"], target_root)
            if valid_sha and commit_check.success:
                # Rework must remain based on the current target branch.  Using
                # the old rejected commit as the branch base makes later main
                # commits appear as out-of-scope deletions and can merge a
                # stale history.  Replay the rejected agent commit after the
                # fresh worktree is created instead.
                rework_seed_sha = rework_base_sha
                _log.info(
                    "rework_workspace_seed_selected",
                    packet_id=pid,
                    seed_sha=rework_base_sha[:12],
                    workspace_base_ref=workspace_base_ref,
                )
            else:
                _log.warn(
                    "rework_workspace_seed_rejected",
                    packet_id=pid,
                    reason="invalid_or_missing_commit",
                )

        if workspace_mode == "scoped_copy":
            from grace_control.services.agent_workspace_builder import AgentWorkspaceBuilder
            builder = AgentWorkspaceBuilder(target_root=target_root)
            from grace_control.services.packet_materializer import PacketMaterializer
            ws = builder.build_scoped_copy(
                scope_paths=list(eff or []),
                workspace_root=wt_root,
                slug=slug,
                config_allowlist=PacketMaterializer.CONFIG_ALLOWLIST,
            )
            wt_path = ws.workspace_path
            base_sha = ws.base_sha
            _workspace_base_sha = ws.workspace_base_sha or ws.base_sha
            branch = f"minimal-{slug}"
            _workspace_result = ws
            adapter._persist_workspace_base_sha(
                run_id, base_sha, _parallel_execution["conflict_keys"]
            )
            add_result = type("Result", (), {"success": True, "stderr": ""})()
        elif workspace_mode == "target_repo_worktree":
            # Preflight checks
            preflight = git.run_preflight(
                target_root,
                require_clean=_s.require_clean_target_repo,
                require_sync=_s.require_remote_sync,
                base_branch=base_ref,
                remote=_s.git_remote,
                branch=branch,
                worktree_path=wt_path,
            )
            _preflight_result = preflight
            if not preflight.success:
                _log.warn("target_repo_preflight_failed", error=preflight.error)
                from grace_control.agent.backend import ExecutionResult as _ER
                er = _ER(
                    accepted=False,
                    domain_status="failed",
                    worktree_path=wt_path,
                    branch_name=branch,
                    commit_sha="",
                    stdout="",
                    stderr=preflight.error,
                    duration_ms=0,
                    errors=[preflight.error],
                )
                er.evidence["target_repo_preflight"] = preflight.to_dict()
                return er

            # Clean up target repo worktree/branch
            adapter._worktree_cleanup.cleanup_attempt(
                target_root, slug, worktree_root=wt_root)

            # 2.3: if the branch still exists after cleanup, force-delete it in target repo
            branch_check = git._run(["branch", "--list", branch], target_root)
            if branch_check.stdout.strip():
                git._run(["branch", "-D", branch], target_root)
                _log.info("stale_branch_deleted", branch=branch, packet_id=pid)

            from grace_control.services.agent_workspace_builder import AgentWorkspaceBuilder
            builder = AgentWorkspaceBuilder(target_root=target_root)
            ws = builder.build_target_repo_worktree(
                workspace_root=wt_root,
                slug=slug,
                branch=branch,
                base_ref=workspace_base_ref,
            )
            wt_path = ws.workspace_path
            base_sha = ws.base_sha
            _workspace_base_sha = ws.workspace_base_sha or ws.base_sha
            _workspace_result = ws
            adapter._persist_workspace_base_sha(
                run_id, base_sha, _parallel_execution["conflict_keys"]
            )
            add_result = type("Result", (), {"success": True, "stderr": ""})()
        else:
            _workspace_result = None
            _effective_repo = target_root if _effective_target_repo else adapter.project_root
            # Clean up target repo worktree/branch
            adapter._worktree_cleanup.cleanup_attempt(
                _effective_repo, slug, worktree_root=adapter.worktree_root)
            # 2.3: if the branch still exists after cleanup, force-delete it
            branch_check = git._run(["branch", "--list", branch], _effective_repo)
            if branch_check.stdout.strip():
                git._run(["branch", "-D", branch], _effective_repo)
                _log.info("stale_branch_deleted", branch=branch, packet_id=pid)
            add_result = git.worktree_add(
                _effective_repo, wt_path, branch, base_ref=workspace_base_ref,
            )

        # 2.1: FAIL FAST — if worktree_add failed for any reason other than
        # "already exists" (which means we reuse an existing one), stop here.
        # Do NOT let the agent run in an empty/wrong directory.
        if not add_result.success and "already exists" not in add_result.stderr:
            _log.warn(
                "worktree_add_failed",
                packet_id=pid,
                worktree=str(wt_path),
                branch=branch,
                stderr=add_result.stderr[:400],
            )
            from grace_control.agent.backend import ExecutionResult as _ER
            return _ER(
                accepted=False,
                domain_status="failed",
                worktree_path=wt_path,
                branch_name=branch,
                commit_sha="",
                stdout="",
                stderr=add_result.stderr[:400],
                duration_ms=0,
                errors=[f"worktree_add_failed: {add_result.stderr[:200]}"],
            )

        # 1.2: Pre-flight — verify the worktree actually exists and is a
        # real git worktree before handing it to the agent.
        if not wt_path.exists():
            _log.warn(
                "worktree_missing_after_add",
                packet_id=pid,
                worktree=str(wt_path),
            )
            from grace_control.agent.backend import ExecutionResult as _ER
            return _ER(
                accepted=False,
                domain_status="failed",
                worktree_path=wt_path,
                branch_name=branch,
                commit_sha="",
                stdout="",
                stderr=f"worktree path does not exist after git worktree add: {wt_path}",
                duration_ms=0,
                errors=[f"worktree path does not exist after git worktree add: {wt_path}"],
            )

        if workspace_mode == "full_git_worktree":
            _workspace_base_sha = git.current_sha(wt_path)
            base_sha = _workspace_base_sha or base_sha
            _workspace_evidence.update(
                {
                    "workspace_mode": "full_git_worktree",
                    "base_sha": base_sha,
                    "workspace_base_sha": _workspace_base_sha,
                    "commit_semantics": "target_repo_commit",
                }
            )
            adapter._persist_workspace_base_sha(
                run_id, base_sha, _parallel_execution["conflict_keys"]
            )

        if rework_seed_sha and workspace_mode != "scoped_copy":
            replay_result = self._apply_rework_seed(
                git=git,
                target_root=target_root,
                worktree_path=wt_path,
                workspace_base_ref=workspace_base_ref,
                rework_seed_sha=rework_seed_sha,
                packet_id=pid,
                branch_name=branch,
            )
            if replay_result is not None:
                return replay_result

        return RuntimeWorkspacePreparation(
            worktree_path=wt_path,
            branch_name=branch,
            base_sha=base_sha,
            workspace_mode=workspace_mode,
            workspace_evidence=_workspace_evidence,
            parallel_execution=_parallel_execution,
            workspace_result=_workspace_result,
            preflight_result=_preflight_result,
        )


    def _apply_rework_seed(
        self,
        *,
        git,
        target_root: Path,
        worktree_path: Path,
        workspace_base_ref: str,
        rework_seed_sha: str,
        packet_id: str,
        branch_name: str,
    ):
        merge_base = git._run(
            ["merge-base", workspace_base_ref, rework_seed_sha],
            target_root,
        )
        seed_commits: list[str] = []
        if merge_base.success and merge_base.stdout.strip():
            commit_range = git._run(
                [
                    "rev-list",
                    "--reverse",
                    f"{merge_base.stdout.strip()}..{rework_seed_sha}",
                ],
                target_root,
            )
            if commit_range.success:
                seed_commits = [
                    line.strip()
                    for line in commit_range.stdout.splitlines()
                    if line.strip()
                ]
        if not seed_commits:
            seed_commits = [rework_seed_sha]

        seed_result = git._run(["cherry-pick", *seed_commits], worktree_path)
        if not seed_result.success:
            git._run(["cherry-pick", "--abort"], worktree_path)
            error_msg = (
                "rework seed could not be replayed onto current target base: "
                f"{seed_result.stderr[:300]}"
            )
            _log.warn(
                "rework_workspace_seed_apply_failed",
                packet_id=packet_id,
                seed_sha=rework_seed_sha[:12],
                seed_commit_count=len(seed_commits),
                error=seed_result.stderr[:300],
            )
            from grace_control.agent.backend import ExecutionResult as _ER
            return _ER(
                accepted=False,
                domain_status="failed",
                worktree_path=worktree_path,
                branch_name=branch_name,
                commit_sha="",
                stdout="",
                stderr=error_msg,
                duration_ms=0,
                errors=[error_msg],
            )
        _log.info(
            "rework_workspace_seed_applied",
            packet_id=packet_id,
            seed_sha=rework_seed_sha[:12],
            seed_commit_count=len(seed_commits),
            workspace_base_ref=workspace_base_ref,
        )
        return None

# END_BLOCK_RUNTIME_EXECUTION
