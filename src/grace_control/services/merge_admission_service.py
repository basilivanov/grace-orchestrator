# ############################################################################
# AI_HEADER: merge_admission_service — merge slot and fencing admission
# ROLE: Owns the pre-mutation admission sequence for MergeService: runtime
#       safety, parallel fencing, deterministic ordering, and merge lease.
# ############################################################################

# START_MODULE_CONTRACT
# purpose: Admit one accepted packet to the serialized target-repository merge
#          pipeline or return its stable non-mutating failure reason.
# inputs: Target path, packet/branch identities, worker identity, lease fields,
#         MergeCoordinatorService, and MergeGuardService.
# returns: MergeAdmissionResult with an acquired merge lease or error text.
# side_effects: Read-only runtime/packet checks, wait event, and merge lease
#               acquisition; no target git mutation.
# emitted_logs: merge_rejected_unsafe_parallel_mode,
#               merge_rejected_parallel_fencing, merge_packet_start.
# error_behavior: Converts admission contention and lease failures to typed
#                 result values without raising.
# END_MODULE_CONTRACT

# START_MODULE_MAP
# mapping:
#   - dataclass: MergeAdmissionResult
#   - class: MergeAdmissionService
#     methods:
#       - admit
# END_MODULE_MAP

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from grace_control.config.settings import parallel_runtime_safety_error
from grace_control.core.structured_logger import GraceLogger
from grace_control.services.merge_coordinator_service import (
    MergeCoordinatorService,
    MergeLeaseBusyError,
    MergeLeaseTakeoverError,
)
from grace_control.services.merge_guard_service import MergeGuardService

_log = GraceLogger("merge_service")


# START_BLOCK_MERGE_ADMISSION
@dataclass(frozen=True)
class MergeAdmissionResult:
    """Admission outcome carrying either a merge lease or stable error text."""

    lease: object | None = None
    error: str = ""

    # START_FUNCTION_CONTRACT
    # name: admitted
    # purpose: Expose whether admission acquired a usable merge lease.
    # inputs: None.
    # returns: True only when lease acquisition succeeded without an error.
    # side_effects: None.
    # emitted_logs: None.
    # error_behavior: None.
    # END_FUNCTION_CONTRACT
    @property
    def admitted(self) -> bool:
        return self.lease is not None and not self.error


class MergeAdmissionService:
    """Own non-mutating merge admission and serialized lease acquisition."""

    # START_FUNCTION_CONTRACT
    # name: __init__
    # purpose: Bind the merge coordinator and guard owner.
    # inputs: coordinator, guards — authoritative merge collaborators.
    # returns: None.
    # side_effects: None.
    # emitted_logs: None.
    # error_behavior: None.
    # END_FUNCTION_CONTRACT
    def __init__(self, coordinator: MergeCoordinatorService, guards: MergeGuardService) -> None:
        self._coordinator = coordinator
        self._guards = guards

    # START_FUNCTION_CONTRACT
    # name: admit
    # purpose: Run runtime safety, parallel fencing, deterministic merge-order,
    #          and target merge-lease admission in the existing order.
    # inputs: packet_id, repo, branch/target refs, worker, optional parallel
    #         identity, and compatibility callbacks for facade seams.
    # returns: MergeAdmissionResult with lease or stable failure text.
    # side_effects: Records wait event and acquires/reclaims merge lease.
    # emitted_logs: Existing merge admission lifecycle messages.
    # error_behavior: Contention and lease failures become result errors.
    # END_FUNCTION_CONTRACT
    def admit(
        self,
        *,
        packet_id: str,
        repo: Path,
        branch_name: str,
        target_branch: str,
        holder: str,
        parallel_lease_id: str | None,
        claimed_attempt: int | None,
        fencing_check: Callable[..., str | None] | None = None,
        wait_recorder: Callable[..., None] | None = None,
    ) -> MergeAdmissionResult:
        safety_error = parallel_runtime_safety_error()
        if safety_error:
            _log.error(
                "merge_rejected_unsafe_parallel_mode",
                packet_id=packet_id,
                reason=safety_error,
            )
            return MergeAdmissionResult(error=safety_error)

        check_fencing = fencing_check or self._guards.parallel_merge_fencing_error
        parallel_fencing_error = check_fencing(
            packet_id=packet_id,
            worker_id=holder,
            parallel_lease_id=parallel_lease_id,
            claimed_attempt=claimed_attempt,
        )
        if parallel_fencing_error:
            _log.warn(
                "merge_rejected_parallel_fencing",
                packet_id=packet_id,
                reason=parallel_fencing_error,
            )
            return MergeAdmissionResult(error=parallel_fencing_error)

        _log.info(
            "merge_packet_start",
            packet_id=packet_id,
            repo=str(repo),
            branch=branch_name,
            target_branch=target_branch,
        )
        if not branch_name:
            return MergeAdmissionResult(error="branch_name is required")

        record_wait = wait_recorder or self._guards.record_merge_wait
        if not self._coordinator.can_merge_now(packet_id, target_repo_root=repo):
            record_wait(
                packet_id,
                "waiting_for_merge_slot: deterministic accepted merge order",
                target_repo_key=str(repo),
            )
            return MergeAdmissionResult(
                error="waiting_for_merge_slot: deterministic accepted merge order"
            )

        try:
            lease = self._coordinator.acquire(
                target_repo_root=repo,
                packet_id=packet_id,
                worker_id=holder,
            )
        except MergeLeaseBusyError as error:
            record_wait(
                packet_id,
                f"waiting_for_merge_slot: {error}",
                target_repo_key=str(repo),
            )
            return MergeAdmissionResult(error=f"waiting_for_merge_slot: {error}")
        except MergeLeaseTakeoverError as error:
            return MergeAdmissionResult(error=f"merge_takeover_blocked: {error}")
        except Exception as error:
            return MergeAdmissionResult(
                error=f"merge lease acquisition failed: {str(error)[:200]}"
            )
        return MergeAdmissionResult(lease=lease)

# END_BLOCK_MERGE_ADMISSION
