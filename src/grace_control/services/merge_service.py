# ############################################################################
# AI_HEADER: merge_service — stable merge facade and lifecycle coordinator
# ROLE: Preserves the public packet merge API while coordinating authoritative
#       merge guards, fenced target mutations, recovery, and cleanup owners.
# ############################################################################

# START_MODULE_CONTRACT
# purpose: Coordinate accepted-packet merges without owning low-level git,
#          stale-base, recovery, or cleanup mechanics inline.
# inputs: Packet ID, target repo path, branch name, target branch, and optional
#         worktree, worker, commit, and parallel lease metadata.
# returns: MergeResult dataclass with the stable merge result shape.
# side_effects: Delegated fenced git operations, packet state transition,
#               PacketRun evidence updates, and merge lease release.
# emitted_logs: merge_packet_start, merge_packet_done, merge_packet_failed,
#               merge lifecycle and recovery logs from owners.
# error_behavior: Returns MergeResult(success=False) on merge/coordinator/state
#                 failures and preserves the existing never-raise boundary.
# END_MODULE_CONTRACT

# START_MODULE_MAP
# mapping:
#   - dataclass: MergeResult
#   - function: is_merge_slot_wait
#   - class: MergeService
#     methods:
#       - merge_packet
#       - cleanup_worktree
# END_MODULE_MAP

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from grace_control.core.stage_instrumentation import stage
from grace_control.core.structured_logger import GraceLogger
from grace_control.db.schema import PacketState
from grace_control.services.git_service import GitService
from grace_control.services.integration_recheck_service import IntegrationRecheckResult, IntegrationRecheckService
from grace_control.services.merge_admission_service import MergeAdmissionService
from grace_control.services.merge_cleanup_service import MergeCleanupService
from grace_control.services.merge_coordinator_service import (
    MergeCoordinatorService,
    MergeLeaseFencedError,
)
from grace_control.services.merge_guard_service import MergeGuardService
from grace_control.services.merge_mutation_service import MergeMutationService
from grace_control.services.merge_recovery_service import MergeRecoveryService
from grace_control.services.parallel_lease_service import ParallelLeaseFencedError

_log = GraceLogger("merge_service")
MERGE_SLOT_WAIT_PREFIX = "waiting_for_merge_slot:"


# START_FUNCTION_CONTRACT
# name: is_merge_slot_wait
# purpose: Identify the non-terminal merge order/lease contention result.
# inputs: error — MergeResult error text.
# returns: True only for coordinator slot/order wait reasons.
# side_effects: None.
# emitted_logs: None.
# error_behavior: False for empty or unrelated errors.
# END_FUNCTION_CONTRACT
def is_merge_slot_wait(error: str) -> bool:
    return str(error).startswith(MERGE_SLOT_WAIT_PREFIX)


# START_BLOCK_MERGE_RESULT
@dataclass
class MergeResult:
    """Stable public result returned by MergeService.merge_packet."""

    success: bool
    packet_id: str
    commit_sha: str
    target_repo: str
    branch: str
    target_branch: str
    error: str = ""

    # START_FUNCTION_CONTRACT
    # name: to_dict
    # purpose: Serialize the stable merge result for API/worker callers.
    # inputs: None.
    # returns: JSON-compatible merge result mapping.
    # side_effects: None.
    # emitted_logs: None.
    # error_behavior: None.
    # END_FUNCTION_CONTRACT
    def to_dict(self) -> dict[str, Any]:
        return {
            "success": self.success,
            "packet_id": self.packet_id,
            "commit_sha": self.commit_sha,
            "target_repo": self.target_repo,
            "branch": self.branch,
            "target_branch": self.target_branch,
            "error": self.error,
        }

# END_BLOCK_MERGE_RESULT


# START_BLOCK_MERGE_FACADE
class MergeService:
    """Stable facade coordinating the bounded merge pipeline owners."""

    # START_FUNCTION_CONTRACT
    # name: __init__
    # purpose: Bind the existing git, packet, coordinator, and integration
    #          collaborators and construct coherent merge responsibility owners.
    # inputs: Optional GitService, PacketService, MergeCoordinatorService, and
    #         IntegrationRecheckService instances.
    # returns: None.
    # side_effects: Instantiates default authoritative collaborators when absent.
    # emitted_logs: None.
    # error_behavior: None.
    # END_FUNCTION_CONTRACT
    def __init__(
        self,
        git: GitService | None = None,
        packets=None,
        coordinator: MergeCoordinatorService | None = None,
        integration_recheck: IntegrationRecheckService | None = None,
    ):
        self._git = git or GitService()
        self._packets = packets
        self._coordinator = coordinator or MergeCoordinatorService(git=self._git)
        self._integration_recheck = integration_recheck or IntegrationRecheckService(
            git=self._git,
            coordinator=self._coordinator,
        )
        self._guards = MergeGuardService(
            self._git,
            self._coordinator,
            self._integration_recheck,
        )
        self._admission = MergeAdmissionService(self._coordinator, self._guards)
        self._mutations = MergeMutationService(
            self._git,
            self._coordinator,
            self._guards,
        )
        self._cleanup = MergeCleanupService(self._git, self._coordinator)
        self._recovery = MergeRecoveryService(self._guards, self._cleanup)

    # START_FUNCTION_CONTRACT
    # name: merge_packet
    # purpose: Serialize accepted packet checkout, merge, push, and MERGED
    #          transition for one target repository, including fenced cleanup.
    # inputs: packet_id, target_repo_root, branch_name, target_branch, and
    #         optional worktree_path, worker_id, commit_sha, parallel lease ID,
    #         and claimed attempt.
    # returns: MergeResult describing success or a typed-safe failure reason.
    # side_effects: Delegated guarded git mutations, packet transition, evidence
    #               updates, and merge lease release.
    # emitted_logs: merge_packet_start, merge_packet_done, and existing owner
    #               lifecycle/recovery messages.
    # error_behavior: Returns unsuccessful MergeResult and never raises for
    #                 merge/coordinator/state-transition failures.
    # END_FUNCTION_CONTRACT
    @stage("merge")
    async def merge_packet(
        self,
        packet_id: str,
        target_repo_root: str,
        branch_name: str,
        target_branch: str,
        worker_id: str | None = None,
        worktree_path: str | Path | None = None,
        commit_sha: str | None = None,
        parallel_lease_id: str | None = None,
        claimed_attempt: int | None = None,
    ) -> MergeResult:
        from grace_control.services.packet_service import PacketService

        svc = self._packets or PacketService()
        repo = Path(target_repo_root).resolve()
        holder = worker_id or f"merge:{packet_id}"

        packet_commit_sha = commit_sha or ""
        merged_commit_sha = ""
        admission = self._admission.admit(
            packet_id=packet_id,
            repo=repo,
            branch_name=branch_name,
            target_branch=target_branch,
            holder=holder,
            parallel_lease_id=parallel_lease_id,
            claimed_attempt=claimed_attempt,
            fencing_check=self._parallel_merge_fencing_error,
            wait_recorder=self._record_merge_wait,
        )
        if not admission.admitted:
            return MergeResult(
                False,
                packet_id,
                "",
                str(repo),
                branch_name,
                target_branch,
                error=admission.error,
            )
        lease = admission.lease

        try:
            if parallel_lease_id:
                self._assert_parallel_lease_current(
                    packet_id=packet_id,
                    worker_id=holder,
                    parallel_lease_id=parallel_lease_id,
                    claimed_attempt=claimed_attempt,
                )
            info = self._git.validate_repo(repo)
            if not info.is_git:
                return MergeResult(
                    False,
                    packet_id,
                    "",
                    str(repo),
                    branch_name,
                    target_branch,
                    error=f"target_repo_root is not a git repo: {repo}",
                )
            if not info.is_clean:
                return MergeResult(
                    False,
                    packet_id,
                    "",
                    str(repo),
                    branch_name,
                    target_branch,
                    error=f"target_repo is dirty: {repo}",
                )

            sanity = self._coordinator.check_repo_sanity(repo)
            if not sanity.ok:
                return MergeResult(
                    False,
                    packet_id,
                    "",
                    str(repo),
                    branch_name,
                    target_branch,
                    error=f"merge_repo_sanity_failed: {sanity.error}",
                )

            preparation = self._guards.prepare(
                packet_id=packet_id,
                repo=repo,
                branch_name=branch_name,
                target_branch=target_branch,
                packet_commit_sha=packet_commit_sha,
                lease=lease,
                worker_id=holder,
                snapshot=self._merge_snapshot(packet_id),
            )
            if preparation.failure is not None:
                return await self._recover_stale_failure(
                    svc=svc,
                    packet_id=packet_id,
                    failure=preparation.failure,
                    parallel_execution=preparation.parallel_execution,
                    worktree_path=worktree_path,
                    repo=repo,
                    branch_name=branch_name,
                    target_branch=target_branch,
                    lease=lease,
                    worker_id=holder,
                )

            pre_checkout_race = self._guards.target_head_race(
                base_sha=preparation.base_sha,
                validated_integration_base=preparation.validated_integration_base,
                current_head=self._target_branch_head(repo, target_branch),
            )
            if pre_checkout_race is not None:
                return await self._recover_stale_failure(
                    svc=svc,
                    packet_id=packet_id,
                    failure=pre_checkout_race,
                    parallel_execution=preparation.parallel_execution,
                    worktree_path=worktree_path,
                    repo=repo,
                    branch_name=branch_name,
                    target_branch=target_branch,
                    lease=lease,
                    worker_id=holder,
                )

            mutation = self._mutations.execute(
                repo=repo,
                packet_id=packet_id,
                branch_name=branch_name,
                target_branch=target_branch,
                lease=lease,
                worker_id=holder,
                parallel_lease_id=parallel_lease_id,
                claimed_attempt=claimed_attempt,
                base_sha=preparation.base_sha,
                current_head=preparation.current_head,
                validated_integration_base=preparation.validated_integration_base,
            )
            if mutation.failure is not None:
                return await self._recover_stale_failure(
                    svc=svc,
                    packet_id=packet_id,
                    failure=mutation.failure,
                    parallel_execution=preparation.parallel_execution,
                    worktree_path=worktree_path,
                    repo=repo,
                    branch_name=branch_name,
                    target_branch=target_branch,
                    lease=lease,
                    worker_id=holder,
                )
            if not mutation.success:
                return MergeResult(
                    False,
                    packet_id,
                    "",
                    str(repo),
                    branch_name,
                    target_branch,
                    error=mutation.error,
                )

            merged_commit_sha = mutation.commit_sha
            self._coordinator.assert_current(
                target_repo_key=lease.target_repo_key,
                lease_token=lease.lease_token,
                packet_id=packet_id,
                worker_id=holder,
            )
            await svc.transition(
                packet_id,
                PacketState.MERGED,
                reason=f"merge_complete:{merged_commit_sha[:8]}",
            )

            try:
                self._cleanup_packet_branches(
                    repo,
                    packet_id,
                    target_repo_key=lease.target_repo_key,
                    lease_token=lease.lease_token,
                    worker_id=holder,
                )
            except MergeLeaseFencedError:
                _log.warn("merge_branch_cleanup_skipped_fenced", packet_id=packet_id)
            except Exception as error:
                _log.warn("merge_branch_cleanup_failed", packet_id=packet_id, error=str(error)[:200])

            if worktree_path:
                try:
                    self._cleanup_worktree_for_merge(
                        repo,
                        Path(worktree_path).resolve(),
                        branch_name,
                        target_repo_key=lease.target_repo_key,
                        lease_token=lease.lease_token,
                        packet_id=packet_id,
                        worker_id=holder,
                    )
                except MergeLeaseFencedError:
                    _log.warn("merge_worktree_cleanup_skipped_fenced", packet_id=packet_id)
                except Exception as error:
                    _log.warn("merge_worktree_cleanup_failed", packet_id=packet_id, error=str(error)[:200])

            _log.info(
                "merge_packet_done",
                packet_id=packet_id,
                commit_sha=merged_commit_sha[:12],
                branch=branch_name,
            )
            return MergeResult(
                True,
                packet_id,
                merged_commit_sha,
                str(repo),
                branch_name,
                target_branch,
            )
        except MergeLeaseFencedError as error:
            return MergeResult(
                False,
                packet_id,
                merged_commit_sha,
                str(repo),
                branch_name,
                target_branch,
                error=f"merge_lease_lost: {error}",
            )
        except ParallelLeaseFencedError as error:
            return MergeResult(
                False,
                packet_id,
                merged_commit_sha,
                str(repo),
                branch_name,
                target_branch,
                error=f"parallel_lease_lost: {error}",
            )
        except Exception as error:
            _log.warn("merge_state_transition_failed", packet_id=packet_id, error=str(error)[:200])
            return MergeResult(
                False,
                packet_id,
                merged_commit_sha,
                str(repo),
                branch_name,
                target_branch,
                error=f"state transition failed: {str(error)[:200]}",
            )
        finally:
            try:
                self._coordinator.release(
                    target_repo_key=lease.target_repo_key,
                    lease_token=lease.lease_token,
                    packet_id=packet_id,
                    worker_id=holder,
                )
            except MergeLeaseFencedError:
                _log.warn("merge_lease_release_skipped_fenced", packet_id=packet_id)
            except Exception as error:
                _log.warn("merge_lease_release_failed", packet_id=packet_id, error=str(error)[:200])

    # START_FUNCTION_CONTRACT
    # name: _recover_stale_failure
    # purpose: Mark stale/integration/merge-conflict metadata failed and route
    #          one typed failure through the existing recoverable block owner.
    # inputs: PacketService, failure result, parallel metadata, worktree, repo,
    #         branch/target refs, active lease, and worker.
    # returns: Unsuccessful MergeResult describing the recoverable block.
    # side_effects: Updates PacketRun evidence/state and performs cleanup.
    # emitted_logs: Existing stale block and cleanup messages.
    # error_behavior: Preserves the recovery owner's stable failure result.
    # END_FUNCTION_CONTRACT
    async def _recover_stale_failure(
        self,
        *,
        svc,
        packet_id: str,
        failure: IntegrationRecheckResult,
        parallel_execution: dict[str, Any],
        worktree_path: str | Path | None,
        repo: Path,
        branch_name: str,
        target_branch: str,
        lease,
        worker_id: str,
    ) -> MergeResult:
        parallel_execution.update(
            integration_base_sha=failure.integration_base_sha,
            integration_recheck="failed",
        )
        return await self._block_stale_packet(
            svc=svc,
            packet_id=packet_id,
            failure=failure,
            parallel_execution=parallel_execution,
            worktree_path=worktree_path,
            repo=repo,
            branch_name=branch_name,
            target_branch=target_branch,
            lease=lease,
            worker_id=worker_id,
        )

    # START_FUNCTION_CONTRACT
    # name: cleanup_worktree
    # purpose: Preserve the public best-effort worktree cleanup seam.
    # inputs: worktree_path, branch, optional target_repo_root.
    # returns: None.
    # side_effects: Delegated git metadata and filesystem cleanup.
    # emitted_logs: Existing worktree cleanup messages.
    # error_behavior: Never raises.
    # END_FUNCTION_CONTRACT
    async def cleanup_worktree(
        self,
        worktree_path: Path,
        branch: str,
        target_repo_root: Path | None = None,
    ) -> None:
        self._cleanup.cleanup_worktree(worktree_path, branch, target_repo_root)

    def _target_branch_head(self, repo: Path, target_branch: str) -> str:
        return self._guards.target_branch_head(repo, target_branch)

    @staticmethod
    def _assert_parallel_lease_current(
        *,
        packet_id: str,
        worker_id: str,
        parallel_lease_id: str,
        claimed_attempt: int | None,
    ) -> None:
        MergeGuardService.assert_parallel_lease_current(
            packet_id=packet_id,
            worker_id=worker_id,
            parallel_lease_id=parallel_lease_id,
            claimed_attempt=claimed_attempt,
        )

    def _parallel_merge_fencing_error(
        self,
        *,
        packet_id: str,
        worker_id: str,
        parallel_lease_id: str | None,
        claimed_attempt: int | None,
    ) -> str | None:
        return self._guards.parallel_merge_fencing_error(
            packet_id=packet_id,
            worker_id=worker_id,
            parallel_lease_id=parallel_lease_id,
            claimed_attempt=claimed_attempt,
        )

    def _guarded_parallel_mutation(
        self,
        *,
        parallel_lease_id: str | None,
        packet_id: str,
        worker_id: str,
        claimed_attempt: int | None,
        operation,
    ):
        return self._guards.guarded_parallel_mutation(
            parallel_lease_id=parallel_lease_id,
            packet_id=packet_id,
            worker_id=worker_id,
            claimed_attempt=claimed_attempt,
            operation=operation,
        )

    @staticmethod
    def _record_merge_wait(packet_id: str, reason: str, *, target_repo_key: str) -> None:
        MergeGuardService.record_merge_wait(packet_id, reason, target_repo_key=target_repo_key)

    @staticmethod
    def _is_merge_conflict(stderr: str | None) -> bool:
        return MergeGuardService.is_merge_conflict(stderr)

    def _abort_failed_merge(
        self,
        repo: Path,
        *,
        target_repo_key: str,
        lease_token: str,
        packet_id: str,
        worker_id: str,
    ) -> None:
        self._guards.abort_failed_merge(
            repo,
            target_repo_key=target_repo_key,
            lease_token=lease_token,
            packet_id=packet_id,
            worker_id=worker_id,
        )

    @staticmethod
    def _merge_snapshot(packet_id: str) -> dict[str, Any]:
        return MergeGuardService.merge_snapshot(packet_id)

    @staticmethod
    def _update_parallel_execution(
        packet_id: str,
        metadata: dict[str, Any],
        *,
        integration_base_sha: str | None = None,
        evidence: dict[str, Any] | None = None,
        failure_class: str = "",
        status: str | None = None,
    ) -> None:
        MergeGuardService.update_parallel_execution(
            packet_id,
            metadata,
            integration_base_sha=integration_base_sha,
            evidence=evidence,
            failure_class=failure_class,
            status=status,
        )

    async def _block_stale_packet(
        self,
        *,
        svc,
        packet_id: str,
        failure: IntegrationRecheckResult,
        parallel_execution: dict[str, Any],
        worktree_path: str | Path | None,
        repo: Path,
        branch_name: str,
        target_branch: str,
        lease,
        worker_id: str,
    ) -> MergeResult:
        error = await self._recovery.block_stale_packet(
            svc=svc,
            packet_id=packet_id,
            failure=failure,
            parallel_execution=parallel_execution,
            worktree_path=worktree_path,
            repo=repo,
            branch_name=branch_name,
            target_branch=target_branch,
            lease=lease,
            worker_id=worker_id,
        )
        return MergeResult(
            False,
            packet_id,
            "",
            str(repo),
            branch_name,
            target_branch,
            error=error,
        )

    def _cleanup_worktree_for_merge(
        self,
        repo: Path,
        worktree_path: Path,
        branch: str,
        *,
        target_repo_key: str,
        lease_token: str,
        packet_id: str,
        worker_id: str,
    ) -> None:
        self._cleanup.cleanup_worktree_for_merge(
            repo,
            worktree_path,
            branch,
            target_repo_key=target_repo_key,
            lease_token=lease_token,
            packet_id=packet_id,
            worker_id=worker_id,
        )

    def _cleanup_worktree_git(self, repo: Path, worktree_path: Path, branch: str) -> None:
        self._cleanup.cleanup_worktree_git(repo, worktree_path, branch)

    @staticmethod
    def _remove_worktree_filesystem(worktree_path: Path) -> None:
        MergeCleanupService.remove_worktree_filesystem(worktree_path)

    def _cleanup_packet_branches(
        self,
        repo: Path,
        packet_id: str,
        *,
        target_repo_key: str,
        lease_token: str,
        worker_id: str,
    ) -> None:
        self._cleanup.cleanup_packet_branches(
            repo,
            packet_id,
            target_repo_key=target_repo_key,
            lease_token=lease_token,
            worker_id=worker_id,
        )

# END_BLOCK_MERGE_FACADE
