# ############################################################################
# AI_HEADER: merge_recovery_service — stale and conflict packet recovery
# ROLE: Owns the existing BLOCKED_RECOVERABLE routing after stale-base,
#       integration, or merge-conflict failures and coordinates evidence plus
#       fenced worktree cleanup.
# ############################################################################

# START_MODULE_CONTRACT
# purpose: Persist failure evidence, block the packet recoverably through the
#          existing PacketService, and clean merge worktree state.
# inputs: PacketService, MergeGuardService, MergeCleanupService, failure result,
#         merge metadata, repository and lease identities.
# returns: Stable failure text consumed by MergeService's MergeResult wrapper.
# side_effects: PacketRun metadata/state updates and fenced cleanup mutations.
# emitted_logs: stale_base_packet_blocked, stale_base_packet_block_failed,
#               stale_base_cleanup_failed.
# error_behavior: Returns an explicit unable-to-block error when state routing
#                 fails; cleanup remains best effort after successful blocking.
# END_MODULE_CONTRACT

# START_MODULE_MAP
# mapping:
#   - class: MergeRecoveryService
#     methods:
#       - block_stale_packet
# END_MODULE_MAP

from __future__ import annotations

from pathlib import Path

from grace_control.core.structured_logger import GraceLogger
from grace_control.db.schema import PacketState
from grace_control.services.integration_recheck_service import IntegrationRecheckResult
from grace_control.services.merge_cleanup_service import MergeCleanupService
from grace_control.services.merge_guard_service import MergeGuardService

_log = GraceLogger("merge_service")


# START_BLOCK_MERGE_RECOVERY
class MergeRecoveryService:
    """Route stale/conflict failures to the existing recoverable state path."""

    # START_FUNCTION_CONTRACT
    # name: __init__
    # purpose: Bind guard evidence and merge-fenced cleanup owners.
    # inputs: guards, cleanup — authoritative merge owners.
    # returns: None.
    # side_effects: None.
    # emitted_logs: None.
    # error_behavior: None.
    # END_FUNCTION_CONTRACT
    def __init__(self, guards: MergeGuardService, cleanup: MergeCleanupService) -> None:
        self._guards = guards
        self._cleanup = cleanup

    # START_FUNCTION_CONTRACT
    # name: block_stale_packet
    # purpose: Record failure evidence, transition an accepted packet to
    #          BLOCKED_RECOVERABLE, and clean its worktree under fencing.
    # inputs: PacketService, packet_id, failed recheck, metadata, worktree,
    #         repository, branch, target branch, lease, and worker.
    # returns: Stable error text for the facade's unsuccessful MergeResult.
    # side_effects: DB result/state updates and fenced worktree cleanup.
    # emitted_logs: stale_base_packet_blocked, stale_base_packet_block_failed,
    #               stale_base_cleanup_failed.
    # error_behavior: Returns an explicit block failure and skips cleanup when
    #                 PacketService.block cannot complete.
    # END_FUNCTION_CONTRACT
    async def block_stale_packet(
        self,
        *,
        svc,
        packet_id: str,
        failure: IntegrationRecheckResult,
        parallel_execution: dict,
        worktree_path: str | Path | None,
        repo: Path,
        branch_name: str,
        target_branch: str,
        lease,
        worker_id: str,
    ) -> str:
        evidence = dict(failure.evidence)
        evidence.setdefault("base_sha", failure.base_sha)
        evidence.setdefault("current_head", failure.integration_base_sha)
        failure_reason = str(evidence.get("reason", "")).strip()
        failure_label = (
            f"{failure.failure_class}:{failure_reason}"
            if failure_reason
            else failure.failure_class
        )
        self._guards.update_parallel_execution(
            packet_id,
            parallel_execution,
            integration_base_sha=failure.integration_base_sha,
            evidence=evidence,
            failure_class=failure.failure_class,
            status=PacketState.BLOCKED_RECOVERABLE.value,
        )
        try:
            await svc.block(
                packet_id,
                recoverable=True,
                reason=f"{failure_label}:{failure.integration_base_sha[:12]}",
            )
            _log.warn(
                "stale_base_packet_blocked",
                packet_id=packet_id,
                failure_class=failure.failure_class,
                base_sha=failure.base_sha,
                current_head=failure.integration_base_sha,
            )
        except Exception as error:
            _log.warn(
                "stale_base_packet_block_failed",
                packet_id=packet_id,
                error=str(error)[:300],
            )
            return f"{failure_label}: unable to block packet: {str(error)[:200]}"

        self._guards.update_parallel_execution(
            packet_id,
            parallel_execution,
            integration_base_sha=failure.integration_base_sha,
            evidence=evidence,
            failure_class=failure.failure_class,
            status=PacketState.BLOCKED_RECOVERABLE.value,
        )
        if worktree_path:
            try:
                self._cleanup.cleanup_worktree_for_merge(
                    repo,
                    Path(worktree_path).resolve(),
                    branch_name,
                    target_repo_key=lease.target_repo_key,
                    lease_token=lease.lease_token,
                    packet_id=packet_id,
                    worker_id=worker_id,
                )
            except Exception as error:
                _log.warn(
                    "stale_base_cleanup_failed",
                    packet_id=packet_id,
                    error=str(error)[:300],
                )
        return f"{failure_label}: target unchanged at {failure.integration_base_sha[:12]}"

# END_BLOCK_MERGE_RECOVERY
