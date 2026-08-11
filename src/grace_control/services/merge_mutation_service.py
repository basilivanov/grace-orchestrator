# ############################################################################
# AI_HEADER: merge_mutation_service — fenced target checkout and merge
# ROLE: Owns the ordered checkout/fetch/merge/push mechanics for one accepted
#       packet while MergeService coordinates state and recovery decisions.
# ############################################################################

# START_MODULE_CONTRACT
# purpose: Execute the target-repository mutations of an accepted packet under
#          the active MergeCoordinatorService lease.
# inputs: Git adapter, merge coordinator, MergeGuardService, target paths and
#         branch/lease metadata.
# returns: MergeTargetResult with commit SHA, ordinary error, or typed stale/
#          conflict failure for recovery routing.
# side_effects: Fenced checkout, fetch, merge, push, and current-SHA reads.
# emitted_logs: None; lifecycle logs remain owned by MergeService.
# error_behavior: Converts git command failures into result values and leaves
#                 conflict recovery to the existing stale-packet path.
# END_MODULE_CONTRACT

# START_MODULE_MAP
# mapping:
#   - dataclass: MergeTargetResult
#   - class: MergeMutationService
#     methods:
#       - execute
# END_MODULE_MAP

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from grace_control.core.structured_logger import GraceLogger
from grace_control.services.integration_recheck_service import IntegrationRecheckResult
from grace_control.services.merge_coordinator_service import MergeCoordinatorService
from grace_control.services.merge_guard_service import MergeGuardService

_log = GraceLogger("merge_service")


# START_BLOCK_MERGE_MUTATION
@dataclass(frozen=True)
class MergeTargetResult:
    """Result of fenced target git mutations before packet state transition."""

    success: bool
    commit_sha: str = ""
    error: str = ""
    failure: IntegrationRecheckResult | None = None


class MergeMutationService:
    """Execute one ordered, fenced target merge mutation sequence."""

    # START_FUNCTION_CONTRACT
    # name: __init__
    # purpose: Bind the existing git adapter, merge lease coordinator, and
    #          guard owner used by target mutation checks.
    # inputs: git, coordinator, guards — authoritative merge collaborators.
    # returns: None.
    # side_effects: None.
    # emitted_logs: None.
    # error_behavior: None.
    # END_FUNCTION_CONTRACT
    def __init__(
        self,
        git,
        coordinator: MergeCoordinatorService,
        guards: MergeGuardService,
    ) -> None:
        self._git = git
        self._coordinator = coordinator
        self._guards = guards

    # START_FUNCTION_CONTRACT
    # name: execute
    # purpose: Checkout the target, best-effort fetch, merge and optionally push
    #          one accepted packet under lease and parallel fencing.
    # inputs: repo, packet/branch refs, lease identity, and validated stale-base
    #         SHA metadata.
    # returns: MergeTargetResult with success SHA, ordinary error, or a typed
    #          stale/conflict failure requiring packet recovery.
    # side_effects: Target checkout/fetch/merge/push and merge-abort on conflict.
    # emitted_logs: None; caller retains existing merge lifecycle logs.
    # error_behavior: Git failures are returned without raising.
    # END_FUNCTION_CONTRACT
    def execute(
        self,
        *,
        repo: Path,
        packet_id: str,
        branch_name: str,
        target_branch: str,
        lease,
        worker_id: str,
        parallel_lease_id: str | None,
        claimed_attempt: int | None,
        base_sha: str,
        current_head: str,
        validated_integration_base: str,
    ) -> MergeTargetResult:
        checkout = self._coordinator.run_mutation(
            target_repo_key=lease.target_repo_key,
            lease_token=lease.lease_token,
            packet_id=packet_id,
            worker_id=worker_id,
            step_name="checkout",
            operation=lambda: self._guards.guarded_parallel_mutation(
                parallel_lease_id=parallel_lease_id,
                packet_id=packet_id,
                worker_id=worker_id,
                claimed_attempt=claimed_attempt,
                operation=lambda: self._git.checkout(repo, target_branch),
            ),
        )
        if not checkout.success:
            return MergeTargetResult(
                False,
                error=f"checkout {target_branch} failed: {checkout.stderr}",
            )

        self._coordinator.run_mutation(
            target_repo_key=lease.target_repo_key,
            lease_token=lease.lease_token,
            packet_id=packet_id,
            worker_id=worker_id,
            step_name="fetch",
            operation=lambda: self._guards.guarded_parallel_mutation(
                parallel_lease_id=parallel_lease_id,
                packet_id=packet_id,
                worker_id=worker_id,
                claimed_attempt=claimed_attempt,
                operation=lambda: self._git.fetch(repo),
            ),
        )

        if validated_integration_base:
            post_checkout_head = self._guards.target_branch_head(repo, target_branch)
            failure = self._guards.target_head_race(
                base_sha=base_sha,
                validated_integration_base=validated_integration_base,
                current_head=post_checkout_head,
            )
            if failure is not None:
                return MergeTargetResult(False, failure=failure)

        merge = self._coordinator.run_mutation(
            target_repo_key=lease.target_repo_key,
            lease_token=lease.lease_token,
            packet_id=packet_id,
            worker_id=worker_id,
            step_name="merge",
            operation=lambda: self._guards.guarded_parallel_mutation(
                parallel_lease_id=parallel_lease_id,
                packet_id=packet_id,
                worker_id=worker_id,
                claimed_attempt=claimed_attempt,
                operation=lambda: self._git.merge(repo, branch_name, target_branch),
            ),
        )
        if not merge.success:
            if self._guards.is_merge_conflict(merge.stderr):
                self._guards.abort_failed_merge(
                    repo,
                    target_repo_key=lease.target_repo_key,
                    lease_token=lease.lease_token,
                    packet_id=packet_id,
                    worker_id=worker_id,
                )
                failure = IntegrationRecheckResult(
                    status="failed",
                    base_sha=base_sha,
                    integration_base_sha=current_head,
                    failure_class="merge_conflict",
                    evidence={
                        "stderr": merge.stderr[:1000],
                        "target_unchanged": True,
                        "target_branch": target_branch,
                    },
                )
                return MergeTargetResult(False, failure=failure)
            return MergeTargetResult(False, error=f"merge failed: {merge.stderr}")

        push = self._coordinator.run_mutation(
            target_repo_key=lease.target_repo_key,
            lease_token=lease.lease_token,
            packet_id=packet_id,
            worker_id=worker_id,
            step_name="push",
            operation=lambda: self._guards.guarded_parallel_mutation(
                parallel_lease_id=parallel_lease_id,
                packet_id=packet_id,
                worker_id=worker_id,
                claimed_attempt=claimed_attempt,
                operation=lambda: self._git.push(repo, branch=target_branch),
            ),
        )
        if not push.success and "does not appear to be a git repository" not in push.stderr:
            return MergeTargetResult(False, error=f"push failed: {push.stderr}")

        return MergeTargetResult(True, commit_sha=self._git.current_sha(repo))

# END_BLOCK_MERGE_MUTATION
