# ############################################################################
# AI_HEADER: integration_recheck_service — stale-base combined-state checks
# ROLE: Builds a disposable target-repository integration worktree, applies an
# accepted packet result, and runs profile-aware T1 verification under the
# active MergeCoordinatorService fencing lease.
# ############################################################################

# START_MODULE_CONTRACT
# purpose: Recheck a packet against the current target HEAD before a stale-base
#          merge is allowed to mutate the target repository.
# inputs: Target repository, current target SHA, packet contract, packet branch
#         or commit, merge lease identity, and an optional verification runner.
# returns: IntegrationRecheckResult with passed/conflict/failed status and
#          base/current SHA plus evidence.
# side_effects: Creates and removes a temporary git worktree and branch, runs
#               packet T1 verification, and writes verification artifacts.
# emitted_logs: integration_recheck_start, integration_apply_failed,
#               integration_verification_failed, integration_recheck_done,
#               integration_cleanup_failed.
# error_behavior: Converts git conflicts and verification failures into typed
#                 results; does not mutate the target checkout or branch.
# END_MODULE_CONTRACT

# START_MODULE_MAP
# mapping:
#   - dataclass: IntegrationRecheckResult
#   - class: IntegrationRecheckService
#     methods:
#       - recheck
#       - _run_guarded
#       - _cleanup
# END_MODULE_MAP

from __future__ import annotations

import shutil
import tempfile
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
from uuid import uuid4

from grace_control.core.acceptance_pipeline import run_acceptance_stage_replay
from grace_control.core.structured_logger import GraceLogger
from grace_control.services.git_service import GitResult, GitService

_log = GraceLogger("integration_recheck")


# START_FUNCTION_CONTRACT
# name: IntegrationRecheckResult
# purpose: Carry the deterministic outcome and evidence of one stale-base
#          integration attempt.
# inputs: status, base_sha, integration_base_sha, failure_class, and evidence.
# returns: Immutable result object.
# side_effects: None.
# emitted_logs: None.
# error_behavior: None.
# END_FUNCTION_CONTRACT
@dataclass(frozen=True)
class IntegrationRecheckResult:
    status: str
    base_sha: str
    integration_base_sha: str
    failure_class: str = ""
    evidence: dict[str, Any] = field(default_factory=dict)
    report: dict[str, Any] = field(default_factory=dict)

    # START_FUNCTION_CONTRACT
    # name: passed
    # purpose: Expose whether combined-state verification passed.
    # inputs: None.
    # returns: True only for status="passed".
    # side_effects: None.
    # emitted_logs: None.
    # error_behavior: None.
    # END_FUNCTION_CONTRACT
    @property
    def passed(self) -> bool:
        """Return whether combined-state verification passed."""
        return self.status == "passed"


# START_BLOCK_INTEGRATION_RECHECK_SERVICE
class IntegrationRecheckService:
    """Run stale-base integration in a disposable, fenced worktree."""

    # START_FUNCTION_CONTRACT
    # name: __init__
    # purpose: Configure git, fencing coordinator, and profile-aware verifier.
    # inputs: git, coordinator, verification_runner, and integration_root.
    # returns: None.
    # side_effects: None.
    # emitted_logs: None.
    # error_behavior: Uses GitService and the canonical acceptance replay by
    #                 default.
    # END_FUNCTION_CONTRACT
    def __init__(
        self,
        git: GitService | None = None,
        coordinator=None,
        verification_runner: Callable[..., Any] | None = None,
        integration_root: Path | None = None,
    ) -> None:
        self._git = git or GitService()
        self._coordinator = coordinator
        self._verification_runner = verification_runner or run_acceptance_stage_replay
        self._integration_root = Path(integration_root).resolve() if integration_root else None

    # START_FUNCTION_CONTRACT
    # name: recheck
    # purpose: Apply one accepted packet result to current target HEAD and run
    #          packet T1 verification before any target checkout/merge.
    # inputs: target_repo_root, target_branch, current_head, branch_name,
    #         packet_contract, lease identity, run_dir, and optional commit_sha.
    # returns: IntegrationRecheckResult with stale-base evidence.
    # side_effects: Fenced temporary worktree/branch operations and T1 runs.
    # emitted_logs: integration_recheck_start, integration_apply_failed,
    #                integration_verification_failed, integration_recheck_done.
    # error_behavior: Returns stale_base_conflict for apply conflicts and
    #                 integration_verification_failed for failed T1/error paths.
    # END_FUNCTION_CONTRACT
    def recheck(
        self,
        *,
        target_repo_root: Path,
        target_branch: str,
        base_sha: str,
        current_head: str,
        branch_name: str,
        packet_contract,
        target_repo_key: str,
        lease_token: str,
        packet_id: str,
        worker_id: str | None,
        run_dir: Path | None = None,
        commit_sha: str | None = None,
    ) -> IntegrationRecheckResult:
        repo = Path(target_repo_root).resolve()
        root = self._integration_root or (repo / ".grace" / "integration")
        temp_parent = Path(tempfile.mkdtemp(prefix=f"grace-integration-{packet_id}-", dir=root if root.exists() else None))
        integration_path = temp_parent / "worktree"
        integration_branch = (
            f"grace/integration/{self._safe_name(packet_id)}-{uuid4().hex[:10]}"
        )
        evidence: dict[str, Any] = {
            "base_sha": base_sha,
            "integration_base_sha": current_head,
            "target_branch": target_branch,
            "integration_branch": integration_branch,
            "worktree_path": str(integration_path),
            "target_repo": str(repo),
        }
        _log.info(
            "integration_recheck_start",
            packet_id=packet_id,
            base_sha=evidence["base_sha"],
            integration_base_sha=current_head,
        )
        cleanup_required = True
        try:
            add_result = self._run_guarded(
                target_repo_key=target_repo_key,
                lease_token=lease_token,
                packet_id=packet_id,
                worker_id=worker_id,
                step_name="integration_worktree_add",
                operation=lambda: self._git.worktree_add(
                    repo, integration_path, integration_branch, base_ref=current_head
                ),
            )
            evidence["worktree_add"] = self._git_result_dict(add_result)
            if not add_result.success:
                _log.warn("integration_apply_failed", packet_id=packet_id, reason="worktree_add")
                return IntegrationRecheckResult(
                    status="failed",
                    base_sha=evidence["base_sha"],
                    integration_base_sha=current_head,
                    failure_class="integration_verification_failed",
                    evidence=evidence | {"error": add_result.stderr[:500]},
                )

            apply_result = self._run_guarded(
                target_repo_key=target_repo_key,
                lease_token=lease_token,
                packet_id=packet_id,
                worker_id=worker_id,
                step_name="integration_apply",
                operation=lambda: self._apply_packet(
                    integration_path, integration_branch, branch_name, commit_sha
                ),
            )
            evidence["apply"] = self._git_result_dict(apply_result)
            if not apply_result.success:
                self._abort_apply(
                    target_repo_key=target_repo_key,
                    lease_token=lease_token,
                    packet_id=packet_id,
                    worker_id=worker_id,
                    integration_path=integration_path,
                )
                _log.warn(
                    "integration_apply_failed",
                    packet_id=packet_id,
                    failure_class="stale_base_conflict",
                )
                return IntegrationRecheckResult(
                    status="conflict",
                    base_sha=evidence["base_sha"],
                    integration_base_sha=current_head,
                    failure_class="stale_base_conflict",
                    evidence=evidence,
                )

            verification_dir = Path(run_dir) / "integration_recheck" if run_dir else temp_parent / "evidence"
            verification_dir.mkdir(parents=True, exist_ok=True)
            report = self._run_guarded(
                target_repo_key=target_repo_key,
                lease_token=lease_token,
                packet_id=packet_id,
                worker_id=worker_id,
                step_name="integration_verification",
                operation=lambda: self._verification_runner(
                    packet=packet_contract,
                    legacy_result={"ok": True, "domain_status": "accepted"},
                    project_root=repo,
                    worktree_path=integration_path,
                    branch_name=integration_branch,
                    run_dir=verification_dir,
                    stage="t1",
                    base_ref=current_head,
                    base_sha=current_head,
                ),
            )
            report_dict = report.to_dict() if hasattr(report, "to_dict") else dict(report or {})
            evidence["verification"] = report_dict
            if not self._report_is_accepted(report):
                _log.warn(
                    "integration_verification_failed",
                    packet_id=packet_id,
                    failure_class="integration_verification_failed",
                )
                return IntegrationRecheckResult(
                    status="failed",
                    base_sha=evidence["base_sha"],
                    integration_base_sha=current_head,
                    failure_class="integration_verification_failed",
                    evidence=evidence,
                    report=report_dict,
                )

            _log.info("integration_recheck_done", packet_id=packet_id, status="passed")
            return IntegrationRecheckResult(
                status="passed",
                base_sha=evidence["base_sha"],
                integration_base_sha=current_head,
                evidence=evidence,
                report=report_dict,
            )
        except Exception as error:
            _log.warn(
                "integration_verification_failed",
                packet_id=packet_id,
                failure_class="integration_verification_failed",
                error=str(error)[:300],
            )
            return IntegrationRecheckResult(
                status="failed",
                base_sha=evidence["base_sha"],
                integration_base_sha=current_head,
                failure_class="integration_verification_failed",
                evidence=evidence | {"error": str(error)[:500]},
            )
        finally:
            if cleanup_required:
                self._cleanup(
                    repo=repo,
                    integration_path=integration_path,
                    integration_branch=integration_branch,
                    target_repo_key=target_repo_key,
                    lease_token=lease_token,
                    packet_id=packet_id,
                    worker_id=worker_id,
                )
            shutil.rmtree(temp_parent, ignore_errors=True)

    # START_FUNCTION_CONTRACT
    # name: _run_guarded
    # purpose: Execute integration git work under the active merge fencing lease.
    # inputs: Lease identity, step_name, and synchronous operation.
    # returns: Operation result.
    # side_effects: Delegates to MergeCoordinatorService.run_mutation.
    # emitted_logs: None.
    # error_behavior: Raises fencing errors before/after a stale operation.
    # END_FUNCTION_CONTRACT
    def _run_guarded(self, *, target_repo_key, lease_token, packet_id, worker_id, step_name, operation):
        if self._coordinator is None:
            raise RuntimeError("integration recheck requires a merge coordinator lease")
        return self._coordinator.run_mutation(
            target_repo_key=target_repo_key,
            lease_token=lease_token,
            packet_id=packet_id,
            worker_id=worker_id,
            step_name=step_name,
            operation=operation,
        )

    # START_FUNCTION_CONTRACT
    # name: _cleanup
    # purpose: Remove temporary integration worktree metadata and branch under
    #          the same fencing lease used for the integration attempt.
    # inputs: Repository, temporary path, branch, and lease identity.
    # returns: None.
    # side_effects: Git worktree removal/prune and temporary branch deletion.
    # emitted_logs: integration_cleanup_failed.
    # error_behavior: Logs cleanup errors and never masks the recheck result.
    # END_FUNCTION_CONTRACT
    def _cleanup(self, *, repo, integration_path, integration_branch, target_repo_key, lease_token, packet_id, worker_id):
        try:
            remove = self._run_guarded(
                target_repo_key=target_repo_key,
                lease_token=lease_token,
                packet_id=packet_id,
                worker_id=worker_id,
                step_name="integration_worktree_remove",
                operation=lambda: self._git.worktree_remove(repo, integration_path, force=True),
            )
            if not remove.success:
                _log.warn("integration_cleanup_failed", packet_id=packet_id, step="worktree_remove")
            prune = self._run_guarded(
                target_repo_key=target_repo_key,
                lease_token=lease_token,
                packet_id=packet_id,
                worker_id=worker_id,
                step_name="integration_worktree_prune",
                operation=lambda: self._git.worktree_prune(repo),
            )
            if not prune.success:
                _log.warn("integration_cleanup_failed", packet_id=packet_id, step="worktree_prune")
            delete = self._run_guarded(
                target_repo_key=target_repo_key,
                lease_token=lease_token,
                packet_id=packet_id,
                worker_id=worker_id,
                step_name="integration_branch_delete",
                operation=lambda: self._git._run(["branch", "-D", integration_branch], repo),
            )
            if not delete.success:
                _log.warn("integration_cleanup_failed", packet_id=packet_id, step="branch_delete")
        except Exception as error:
            _log.warn("integration_cleanup_failed", packet_id=packet_id, error=str(error)[:300])

    def _abort_apply(self, *, target_repo_key, lease_token, packet_id, worker_id, integration_path):
        try:
            self._run_guarded(
                target_repo_key=target_repo_key,
                lease_token=lease_token,
                packet_id=packet_id,
                worker_id=worker_id,
                step_name="integration_apply_abort",
                operation=lambda: self._git._run(["merge", "--abort"], integration_path),
            )
        except Exception:
            try:
                self._run_guarded(
                    target_repo_key=target_repo_key,
                    lease_token=lease_token,
                    packet_id=packet_id,
                    worker_id=worker_id,
                    step_name="integration_cherry_pick_abort",
                    operation=lambda: self._git._run(["cherry-pick", "--abort"], integration_path),
                )
            except Exception:
                pass

    def _apply_packet(self, integration_path: Path, integration_branch: str, branch_name: str, commit_sha: str | None):
        branch_exists = self._git._run(
            ["show-ref", "--verify", "--quiet", f"refs/heads/{branch_name}"],
            integration_path,
        )
        if branch_exists.success:
            return self._git.merge(integration_path, branch_name, integration_branch)
        if commit_sha:
            commit_exists = self._git._run(
                ["cat-file", "-e", f"{commit_sha}^{{commit}}"], integration_path
            )
            if commit_exists.success:
                return self._git._run(["cherry-pick", commit_sha], integration_path)
        return self._git.merge(integration_path, branch_name, integration_branch)

    @staticmethod
    def _safe_name(packet_id: str) -> str:
        return "".join(char if char.isalnum() or char in "-_" else "-" for char in packet_id)

    @staticmethod
    def _report_is_accepted(report: Any) -> bool:
        if bool(getattr(report, "is_accepted", False)):
            return True
        if isinstance(report, dict):
            verdict = report.get("final_verdict", report.get("verdict", ""))
            return str(verdict).lower().rsplit(".", 1)[-1] == "accepted"
        return False

    @staticmethod
    def _git_result_dict(result: GitResult) -> dict[str, Any]:
        return {
            "success": bool(result.success),
            "stdout": result.stdout[-4000:],
            "stderr": result.stderr[-4000:],
            "returncode": result.returncode,
        }
# END_BLOCK_INTEGRATION_RECHECK_SERVICE
