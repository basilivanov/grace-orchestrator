# ############################################################################
# AI_HEADER: packet_execution_workspace_service — prepare isolated packet workspaces
# ROLE: Owns target-repository resolution, workspace construction, preflight,
#       and rework-seed replay before the packet backend is invoked.
# ############################################################################

# START_MODULE_CONTRACT
# purpose: Build the effective packet workspace and return its runtime metadata.
# inputs: Adapter dependencies, packet contract, attempt/base data, executor settings.
# returns: RuntimeWorkspacePreparation or a controlled backend failure result.
# side_effects: Creates/cleans worktrees, branches, scoped copies, and replay commits.
# emitted_logs: Workspace mode, preflight, branch, worktree, and rework-seed events.
# error_behavior: Returns controlled failed backend results for unsafe workspace setup.
# END_MODULE_CONTRACT

# START_MODULE_MAP
# mapping:
#   - class: RuntimeWorkspacePreparation
#   - class: PacketExecutionWorkspaceService
#     methods:
#       - prepare
# END_MODULE_MAP

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from grace_control.core.structured_logger import GraceLogger

_log = GraceLogger("packet_execution_runtime")


# Canonical worktree/branch naming helpers — single source of truth.
def _attempt_slug(packet_id: str, attempt: int) -> str:
    return f"{packet_id}-attempt-{attempt:04d}"


def _attempt_branch(packet_id: str, attempt: int) -> str:
    return f"agent/{_attempt_slug(packet_id, attempt)}"


def _resolve_worktree_for_contract(
    packet_data: dict,
    executor: dict,
    settings_obj: object,
    project_root: Path,
    worktree_root: Path,
) -> Path:
    """Determine the expected worktree path the same way runtime preparation does."""
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
    workspace_mode = (
        pkt_workspace_mode
        or executor.get("workspace_mode")
        or _s.workspace_mode
        or "full_git_worktree"
    )

    # Sync with workspace preparation: an external target defaults to its own
    # worktree mode unless the packet or executor explicitly selected a mode.
    if _effective_target_repo and str(_effective_target_repo) != str(project_root):
        if not pkt_workspace_mode and not executor.get("workspace_mode"):
            workspace_mode = "target_repo_worktree"

    target_root = Path(_effective_target_repo) if _effective_target_repo else Path(
        _s.target_repo_root or project_root
    )
    if worktree_root.is_absolute():
        wt_root = worktree_root
    else:
        wt_root = Path(_s.worktree_root)
    if not wt_root.is_absolute():
        wt_root = target_root / wt_root
    return wt_root / slug


# Commands that need broader repo context and therefore cannot safely run in a
# scoped copy. The list remains conservative by design.
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
    """Best-effort flattening of structured verification commands."""
    out: list = []
    try:
        verification = getattr(packet_contract, "verification", None) or {}
    except Exception:
        verification = {}
    if not isinstance(verification, dict):
        return out
    for tier in ("t0", "t1", "t2"):
        for command in verification.get(tier) or []:
            if isinstance(command, str):
                out.append(command)
            elif isinstance(command, (list, tuple)):
                out.append([token for token in command if isinstance(token, str)])
            else:
                out.append(str(command))
    return out


def _verification_unsafe_for_scoped(verification_tokens: list, scope: list[str]) -> bool:
    """Return whether verification likely needs files outside a scoped copy."""
    del scope  # Scope is part of the compatibility signature; the check is conservative.
    flat: list[str] = []
    for item in verification_tokens or []:
        if isinstance(item, str):
            flat.append(item)
        elif isinstance(item, (list, tuple)):
            flat.extend(token for token in item if isinstance(token, str))
    if not flat:
        return False
    blob = " ".join(flat).lower()
    return any(pattern in blob for pattern in _BROAD_REPO_VERIFICATION_PATTERNS)


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


# START_BLOCK_WORKSPACE_PREPARATION
class PacketExecutionWorkspaceService:

    # START_FUNCTION_CONTRACT
    # name: prepare
    # purpose: Resolve target workspace, run repository preflight, and create the agent workspace.
    # inputs: adapter, pid, eff, packet contract, attempt, base ref/SHA, executor, run id.
    # returns: RuntimeWorkspacePreparation or a controlled backend failure result.
    # side_effects: Creates/cleans worktrees, branches, scoped copies, and replay seed commits.
    # emitted_logs: Workspace mode, preflight, branch, worktree, and rework-seed events.
    # error_behavior: Returns controlled backend failure results for unsafe workspace setup.
    # END_FUNCTION_CONTRACT
    def prepare(
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

        pkt_metadata = getattr(packet_contract, "metadata", None) or {}
        pkt_target_repo = pkt_metadata.get("target_repo_root", "")
        pkt_workspace_mode = pkt_metadata.get("workspace_mode", "")
        _effective_target_repo = pkt_target_repo or _s.target_repo_root or ""
        workspace_mode = (
            pkt_workspace_mode
            or executor.get("workspace_mode")
            or _s.workspace_mode
            or "full_git_worktree"
        )
        is_minimal = executor.get("minimal_repo", False)

        # An external target defaults to an isolated target-repository worktree
        # unless the packet or executor explicitly selected another mode.
        if _effective_target_repo and str(_effective_target_repo) != str(adapter.project_root):
            if not pkt_workspace_mode and not executor.get("workspace_mode"):
                workspace_mode = "target_repo_worktree"
                _log.info(
                    "workspace_mode_defaulted_to_target_repo_worktree",
                    packet_id=pid,
                    target_repo_root=str(_effective_target_repo),
                )

        target_root = Path(_effective_target_repo) if _effective_target_repo else Path(
            _s.target_repo_root or adapter.project_root
        )

        # Scope paths may name files that the packet is expected to create.
        # Isolation is enforced by resolving the workspace from target_root.
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
                verification = _flatten_verification_for_safety(packet_contract)
            except Exception:
                verification = []
            if _verification_unsafe_for_scoped(verification, eff or []):
                if executor.get("workspace_scope_safety") == "unsafe_allowed_for_fixture":
                    _log.warn(
                        "workspace_scope_unsafe",
                        packet_id=pid,
                        reason="verification_requires_repo_context",
                    )
                else:
                    _log.warn(
                        "workspace_mode_auto_upgraded",
                        packet_id=pid,
                        from_mode="scoped_copy",
                        to_mode="full_git_worktree",
                        reason="verification_requires_repo_context",
                    )
                    workspace_mode = "full_git_worktree"
                    is_minimal = False
                    _workspace_evidence = {
                        "workspace_mode": "full_git_worktree",
                        "reason": "verification_requires_repo_context",
                    }
        if is_minimal:
            workspace_mode = "scoped_copy"

        if adapter.worktree_root.is_absolute():
            wt_root = adapter.worktree_root
        else:
            wt_root = Path(_s.worktree_root)
        if not wt_root.is_absolute():
            wt_root = target_root / wt_root
        wt_path = wt_root / slug

        source_root = Path(os.getenv("GRACE_SOURCE_DIR", str(adapter.project_root))).resolve()
        if workspace_mode == "target_repo_worktree" and str(source_root) != str(target_root.resolve()):
            try:
                wt_path.resolve().relative_to(source_root)
                if os.getenv("GRACE_ALLOW_WORKTREE_INSIDE_GRACE") != "1":
                    error_msg = (
                        f"worktree_root is inside GRACE project root: {wt_path}. "
                        "Set GRACE_ALLOW_WORKTREE_INSIDE_GRACE=1 to override."
                    )
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
        if pkt_metadata.get("origin") == "review_rework" and rework_base_sha:
            valid_sha = len(rework_base_sha) == 40 and all(
                char in "0123456789abcdefABCDEF" for char in rework_base_sha
            )
            commit_check = git._run(
                ["cat-file", "-e", f"{rework_base_sha}^{{commit}}"], target_root
            )
            if valid_sha and commit_check.success:
                # Replay the rejected agent commit after the fresh worktree is
                # created so the current target branch remains the base.
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
            from grace_control.services.packet_materializer import PacketMaterializer

            builder = AgentWorkspaceBuilder(target_root=target_root)
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

            adapter._worktree_cleanup.cleanup_attempt(
                target_root, slug, worktree_root=wt_root
            )
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
            adapter._worktree_cleanup.cleanup_attempt(
                _effective_repo, slug, worktree_root=adapter.worktree_root
            )
            branch_check = git._run(["branch", "--list", branch], _effective_repo)
            if branch_check.stdout.strip():
                git._run(["branch", "-D", branch], _effective_repo)
                _log.info("stale_branch_deleted", branch=branch, packet_id=pid)
            add_result = git.worktree_add(
                _effective_repo, wt_path, branch, base_ref=workspace_base_ref
            )

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

        if not wt_path.exists():
            _log.warn("worktree_missing_after_add", packet_id=pid, worktree=str(wt_path))
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

    # START_FUNCTION_CONTRACT
    # name: _apply_rework_seed
    # purpose: Replay a rejected agent commit on the current target-base worktree.
    # inputs: Git service, target/worktree paths, base ref, seed SHA, packet/branch metadata.
    # returns: None on success or a controlled backend failure result.
    # side_effects: Runs Git merge-base/rev-list/cherry-pick and may abort a failed cherry-pick.
    # emitted_logs: Rework seed selection and replay failure events.
    # error_behavior: Returns a failed backend result when replay cannot be completed.
    # END_FUNCTION_CONTRACT
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
            ["merge-base", workspace_base_ref, rework_seed_sha], target_root
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

# END_BLOCK_WORKSPACE_PREPARATION
