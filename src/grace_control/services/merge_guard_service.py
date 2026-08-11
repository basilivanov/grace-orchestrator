# ############################################################################
# AI_HEADER: merge_guard_service — merge eligibility and stale-base guards
# ROLE: Owns merge admission checks, packet/run evidence snapshots, parallel
#       fencing, and stale-base integration decisions for MergeService.
# ############################################################################

# START_MODULE_CONTRACT
# purpose: Centralize non-mutating merge consistency decisions and the fenced
#          merge-abort operation used when target mutation detects a conflict.
# inputs: GitService, MergeCoordinatorService, IntegrationRecheckService,
#         packet identifiers, target paths, lease identities, and snapshots.
# returns: MergePreparation, typed integration failures, and persisted evidence.
# side_effects: Read-only git/DB queries, packet-run metadata writes, and a
#               fenced `git merge --abort` when a merge conflict is detected.
# emitted_logs: integration_target_advanced, merge_abort_failed,
#               merge_wait_event_failed, parallel fencing diagnostics.
# error_behavior: Fails closed for missing/stale fencing and missing packet
#                 contracts; never mutates a target without a current lease.
# END_MODULE_CONTRACT

# START_MODULE_MAP
# mapping:
#   - dataclass: MergePreparation
#   - class: MergeGuardService
#     methods:
#       - prepare
#       - target_head_race
#       - target_branch_head
#       - assert_parallel_lease_current
#       - parallel_merge_fencing_error
#       - guarded_parallel_mutation
#       - record_merge_wait
#       - is_merge_conflict
#       - abort_failed_merge
#       - merge_snapshot
#       - update_parallel_execution
# END_MODULE_MAP

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from grace_control.config.settings import get_parallel_runtime_config
from grace_control.core.contracts import build_packet_contract
from grace_control.core.structured_logger import GraceLogger
from grace_control.db import get_db
from grace_control.db.schema import Event, Packet, PacketRun, PacketState, ParallelLease
from grace_control.services.integration_recheck_service import (
    IntegrationRecheckResult,
    IntegrationRecheckService,
)
from grace_control.services.merge_coordinator_service import (
    MergeCoordinatorService,
    MergeLeaseFencedError,
)
from grace_control.services.parallel_lease_service import (
    ParallelLeaseFencedError,
    ParallelLeaseService,
)

_log = GraceLogger("merge_service")


# START_BLOCK_MERGE_GUARD
@dataclass(frozen=True)
class MergePreparation:
    """Carry one merge's snapshot, stale-base metadata, and guard result."""

    snapshot: dict[str, Any]
    base_sha: str
    conflict_keys: list[str]
    current_head: str
    parallel_execution: dict[str, Any]
    validated_integration_base: str = ""
    failure: IntegrationRecheckResult | None = None


class MergeGuardService:
    """Own merge eligibility, evidence, and stale-base consistency policy."""

    # START_FUNCTION_CONTRACT
    # name: __init__
    # purpose: Bind the git adapter, merge lease coordinator, and stale-base
    #          integration recheck owner used by guard decisions.
    # inputs: git, coordinator, integration_recheck — existing authoritative
    #         merge collaborators.
    # returns: None.
    # side_effects: None.
    # emitted_logs: None.
    # error_behavior: None.
    # END_FUNCTION_CONTRACT
    def __init__(
        self,
        git,
        coordinator: MergeCoordinatorService,
        integration_recheck: IntegrationRecheckService,
    ) -> None:
        self._git = git
        self._coordinator = coordinator
        self._integration_recheck = integration_recheck

    # START_FUNCTION_CONTRACT
    # name: prepare
    # purpose: Resolve the packet snapshot, record parallel execution metadata,
    #          and perform bounded stale-base integration rechecks.
    # inputs: packet_id, repo, branch/target refs, packet commit, active lease,
    #         and optional preloaded snapshot.
    # returns: MergePreparation; failure is populated when target merge must
    #          be blocked before checkout or merge.
    # side_effects: Read-only git/DB checks, PacketRun metadata updates, and
    #               calls to the existing IntegrationRecheckService.
    # emitted_logs: integration_target_advanced.
    # error_behavior: Missing base/contract or failed recheck is represented as
    #                 an IntegrationRecheckResult and fails closed.
    # END_FUNCTION_CONTRACT
    def prepare(
        self,
        *,
        packet_id: str,
        repo: Path,
        branch_name: str,
        target_branch: str,
        packet_commit_sha: str,
        lease,
        worker_id: str,
        snapshot: dict[str, Any] | None = None,
    ) -> MergePreparation:
        merge_snapshot = snapshot or self.merge_snapshot(packet_id)
        base_sha = str(merge_snapshot["base_sha"] or "").strip()
        conflict_keys = merge_snapshot["conflict_keys"]
        current_head = self.target_branch_head(repo, target_branch)
        integration_recheck_enabled = bool(
            get_parallel_runtime_config()["integration_recheck_on_stale_base"]
        )
        missing_base_sha = not base_sha
        stale_base = bool(base_sha and current_head and base_sha != current_head)
        if missing_base_sha and integration_recheck_enabled:
            stale_base = True
        parallel_execution = {
            "base_sha": base_sha,
            "integration_base_sha": None,
            "stale_base": stale_base,
            "conflict_keys": conflict_keys,
            "integration_recheck": "skipped",
        }
        if not integration_recheck_enabled:
            parallel_execution.update(
                {
                    "integration_recheck_disabled": True,
                    "integration_recheck_skip_reason": (
                        "GRACE_INTEGRATION_RECHECK_ON_STALE_BASE=false"
                    ),
                }
            )
        self.update_parallel_execution(packet_id, parallel_execution)

        if missing_base_sha and integration_recheck_enabled:
            failure = IntegrationRecheckResult(
                status="failed",
                base_sha=base_sha,
                integration_base_sha=current_head,
                failure_class="integration_verification_failed",
                evidence={
                    "reason": "missing_base_sha",
                    "base_sha": base_sha,
                    "current_head": current_head,
                    "target_branch": target_branch,
                },
            )
            return MergePreparation(
                snapshot=merge_snapshot,
                base_sha=base_sha,
                conflict_keys=conflict_keys,
                current_head=current_head,
                parallel_execution=parallel_execution,
                failure=failure,
            )

        validated_integration_base = ""
        if stale_base and integration_recheck_enabled:
            contract = merge_snapshot["packet_contract"]
            if contract is None:
                failure = IntegrationRecheckResult(
                    status="failed",
                    base_sha=base_sha,
                    integration_base_sha=current_head,
                    failure_class="integration_verification_failed",
                    evidence={"error": "packet contract could not be reconstructed"},
                )
            else:
                failure = None
                candidate_head = current_head
                for recheck_attempt in range(3):
                    try:
                        checked = self._integration_recheck.recheck(
                            target_repo_root=repo,
                            target_branch=target_branch,
                            base_sha=base_sha,
                            current_head=candidate_head,
                            branch_name=branch_name,
                            packet_contract=contract,
                            target_repo_key=lease.target_repo_key,
                            lease_token=lease.lease_token,
                            packet_id=packet_id,
                            worker_id=worker_id,
                            run_dir=merge_snapshot["run_dir"],
                            commit_sha=packet_commit_sha,
                        )
                    except Exception as error:
                        checked = IntegrationRecheckResult(
                            status="failed",
                            base_sha=base_sha,
                            integration_base_sha=candidate_head,
                            failure_class="integration_verification_failed",
                            evidence={"error": str(error)[:500]},
                        )
                    if not checked.passed:
                        failure = checked
                        break

                    observed_head = self.target_branch_head(repo, target_branch)
                    if observed_head != checked.integration_base_sha:
                        _log.warn(
                            "integration_target_advanced",
                            packet_id=packet_id,
                            previous_head=checked.integration_base_sha,
                            current_head=observed_head,
                            attempt=recheck_attempt + 1,
                        )
                        candidate_head = observed_head
                        if recheck_attempt == 2:
                            failure = IntegrationRecheckResult(
                                status="failed",
                                base_sha=base_sha,
                                integration_base_sha=observed_head,
                                failure_class="stale_base_conflict",
                                evidence={
                                    **checked.evidence,
                                    "target_advanced_after_recheck": True,
                                    "validated_head": checked.integration_base_sha,
                                    "current_head": observed_head,
                                },
                            )
                            break
                        continue

                    final_head = self.target_branch_head(repo, target_branch)
                    if final_head != checked.integration_base_sha:
                        candidate_head = final_head
                        if recheck_attempt == 2:
                            failure = IntegrationRecheckResult(
                                status="failed",
                                base_sha=base_sha,
                                integration_base_sha=final_head,
                                failure_class="stale_base_conflict",
                                evidence={
                                    **checked.evidence,
                                    "target_advanced_after_recheck": True,
                                    "validated_head": checked.integration_base_sha,
                                    "current_head": final_head,
                                },
                            )
                            break
                        continue
                    validated_integration_base = checked.integration_base_sha
                    parallel_execution.update(
                        integration_base_sha=validated_integration_base,
                        integration_recheck="passed",
                    )
                    self.update_parallel_execution(
                        packet_id,
                        parallel_execution,
                        integration_base_sha=validated_integration_base,
                        evidence=checked.evidence,
                    )
                    break

            if failure is not None:
                parallel_execution.update(
                    integration_base_sha=failure.integration_base_sha,
                    integration_recheck="failed",
                )
                return MergePreparation(
                    snapshot=merge_snapshot,
                    base_sha=base_sha,
                    conflict_keys=conflict_keys,
                    current_head=current_head,
                    parallel_execution=parallel_execution,
                    failure=failure,
                )
        elif stale_base:
            parallel_execution["integration_recheck"] = "skipped"
            self.update_parallel_execution(packet_id, parallel_execution)

        return MergePreparation(
            snapshot=merge_snapshot,
            base_sha=base_sha,
            conflict_keys=conflict_keys,
            current_head=current_head,
            parallel_execution=parallel_execution,
            validated_integration_base=validated_integration_base,
        )

    # START_FUNCTION_CONTRACT
    # name: target_head_race
    # purpose: Convert a target-head movement after stale integration validation
    #          into the existing stale_base_conflict result.
    # inputs: base_sha, validated_integration_base, and observed current_head.
    # returns: IntegrationRecheckResult or None when the validated head remains.
    # side_effects: None.
    # emitted_logs: None.
    # error_behavior: None.
    # END_FUNCTION_CONTRACT
    @staticmethod
    def target_head_race(
        *,
        base_sha: str,
        validated_integration_base: str,
        current_head: str,
    ) -> IntegrationRecheckResult | None:
        if not validated_integration_base or current_head == validated_integration_base:
            return None
        return IntegrationRecheckResult(
            status="failed",
            base_sha=base_sha,
            integration_base_sha=current_head,
            failure_class="stale_base_conflict",
            evidence={
                "target_advanced_after_recheck": True,
                "validated_head": validated_integration_base,
                "current_head": current_head,
            },
        )

    # START_FUNCTION_CONTRACT
    # name: target_branch_head
    # purpose: Read a target branch SHA without changing the target checkout.
    # inputs: repo — target repository; target_branch — branch/ref name.
    # returns: Branch SHA, or current HEAD as compatibility fallback.
    # side_effects: Read-only git commands.
    # emitted_logs: None.
    # error_behavior: Falls back to GitService.current_sha for test adapters or
    #                 repositories that cannot resolve the branch ref.
    # END_FUNCTION_CONTRACT
    def target_branch_head(self, repo: Path, target_branch: str) -> str:
        result = self._git._run(["rev-parse", target_branch], repo)
        stdout = getattr(result, "stdout", "")
        if getattr(result, "success", False) and isinstance(stdout, str) and stdout.strip():
            return stdout.strip()
        fallback = self._git.current_sha(repo)
        return fallback if isinstance(fallback, str) else ""

    # START_FUNCTION_CONTRACT
    # name: assert_parallel_lease_current
    # purpose: Fence a worker merge against a lost or reclaimed parallel lease.
    # inputs: packet_id, worker_id, parallel_lease_id, claimed_attempt.
    # returns: None when the exact identity is current.
    # side_effects: Read-only query against parallel_leases.
    # emitted_logs: parallel_lease_fenced.
    # error_behavior: Raises ParallelLeaseFencedError for stale identity.
    # END_FUNCTION_CONTRACT
    @staticmethod
    def assert_parallel_lease_current(
        *,
        packet_id: str,
        worker_id: str,
        parallel_lease_id: str,
        claimed_attempt: int | None,
    ) -> None:
        if claimed_attempt is None:
            raise ParallelLeaseFencedError("claimed_attempt is required")
        with get_db() as db:
            ParallelLeaseService().assert_current(
                db,
                packet_id=packet_id,
                worker_id=worker_id,
                lease_id=parallel_lease_id,
                claimed_attempt=claimed_attempt,
            )

    # START_FUNCTION_CONTRACT
    # name: parallel_merge_fencing_error
    # purpose: Require and validate retained TZ03 identity before multi-worker
    #          ACCEPTED packets enter merge coordination.
    # inputs: packet_id, worker_id, parallel lease ID, and claimed attempt.
    # returns: None for compatible/current identity, otherwise a typed reason.
    # side_effects: Read-only packet and parallel-lease queries.
    # emitted_logs: None; caller emits the rejection log.
    # error_behavior: Fails closed for ACCEPTED packets or retained leases when
    #                 effective concurrency is greater than one.
    # END_FUNCTION_CONTRACT
    def parallel_merge_fencing_error(
        self,
        *,
        packet_id: str,
        worker_id: str,
        parallel_lease_id: str | None,
        claimed_attempt: int | None,
    ) -> str | None:
        config = get_parallel_runtime_config()
        if int(config["max_concurrency"]) <= 1:
            return None
        with get_db() as db:
            packet = db.query(Packet).filter_by(id=packet_id).first()
            parallel_lease = db.query(ParallelLease).filter_by(packet_id=packet_id).first()
            expected = parallel_lease is not None or (
                packet is not None and packet.state == PacketState.ACCEPTED.value
            )
        if not expected:
            return None
        if not parallel_lease_id or claimed_attempt is None:
            return "parallel_lease_lost: fencing identity is required"
        try:
            self.assert_parallel_lease_current(
                packet_id=packet_id,
                worker_id=worker_id,
                parallel_lease_id=parallel_lease_id,
                claimed_attempt=claimed_attempt,
            )
        except ParallelLeaseFencedError as error:
            return f"parallel_lease_lost: {error}"
        return None

    # START_FUNCTION_CONTRACT
    # name: guarded_parallel_mutation
    # purpose: Recheck parallel ownership immediately before a target mutation.
    # inputs: Optional parallel identity and a synchronous operation.
    # returns: Operation result.
    # side_effects: Read-only lease check followed by the provided mutation.
    # emitted_logs: parallel_lease_fenced.
    # error_behavior: Raises before mutation when supplied identity is stale.
    # END_FUNCTION_CONTRACT
    def guarded_parallel_mutation(
        self,
        *,
        parallel_lease_id: str | None,
        packet_id: str,
        worker_id: str,
        claimed_attempt: int | None,
        operation,
    ):
        if parallel_lease_id:
            self.assert_parallel_lease_current(
                packet_id=packet_id,
                worker_id=worker_id,
                parallel_lease_id=parallel_lease_id,
                claimed_attempt=claimed_attempt,
            )
        return operation()

    # START_FUNCTION_CONTRACT
    # name: record_merge_wait
    # purpose: Persist merge-slot contention as a non-terminal typed wait.
    # inputs: packet_id, reason, target_repo_key.
    # returns: None.
    # side_effects: Inserts one packet_wait Event row.
    # emitted_logs: merge_wait_event_failed on contained persistence failure.
    # error_behavior: Read/write failures are contained so WAIT remains valid.
    # END_FUNCTION_CONTRACT
    @staticmethod
    def record_merge_wait(packet_id: str, reason: str, *, target_repo_key: str) -> None:
        try:
            with get_db() as db:
                db.add(Event(
                    event_type="packet_wait",
                    entity_type="packet",
                    entity_id=packet_id,
                    payload_json={
                        "reason": "waiting_for_merge_slot",
                        "detail": reason,
                        "target_repo_key": target_repo_key,
                        "packet_id": packet_id,
                        "expected_wait": True,
                    },
                    timestamp=datetime.now(UTC),
                ))
        except Exception as error:
            _log.warn("merge_wait_event_failed", packet_id=packet_id, error=str(error)[:200])

    # START_FUNCTION_CONTRACT
    # name: is_merge_conflict
    # purpose: Classify a failed git merge as a recoverable text conflict.
    # inputs: stderr — git merge diagnostic text.
    # returns: True when git reports a conflict or unresolved merge state.
    # side_effects: None.
    # emitted_logs: None.
    # error_behavior: Empty/non-string diagnostics are not classified.
    # END_FUNCTION_CONTRACT
    @staticmethod
    def is_merge_conflict(stderr: str | None) -> bool:
        text = str(stderr or "").lower()
        return any(
            marker in text
            for marker in (
                "conflict",
                "automatic merge failed",
                "fix conflicts",
                "unmerged files",
            )
        )

    # START_FUNCTION_CONTRACT
    # name: abort_failed_merge
    # purpose: Abort only the current fenced failed merge before recovery block.
    # inputs: repo and current merge lease identity.
    # returns: None.
    # side_effects: Executes fenced `git merge --abort`.
    # emitted_logs: merge_abort_failed.
    # error_behavior: Logs failed abort and leaves takeover blocked by sanity.
    # END_FUNCTION_CONTRACT
    def abort_failed_merge(
        self,
        repo: Path,
        *,
        target_repo_key: str,
        lease_token: str,
        packet_id: str,
        worker_id: str,
    ) -> None:
        try:
            result = self._coordinator.run_mutation(
                target_repo_key=target_repo_key,
                lease_token=lease_token,
                packet_id=packet_id,
                worker_id=worker_id,
                step_name="merge_abort",
                operation=lambda: self._git._run(["merge", "--abort"], repo),
            )
            if not getattr(result, "success", False):
                _log.warn(
                    "merge_abort_failed",
                    packet_id=packet_id,
                    error=getattr(result, "stderr", "")[:300],
                )
        except Exception as error:
            _log.warn("merge_abort_failed", packet_id=packet_id, error=str(error)[:300])

    # START_FUNCTION_CONTRACT
    # name: merge_snapshot
    # purpose: Load the latest PacketRun base snapshot, result metadata, packet
    #          conflict keys, and contract needed for stale integration.
    # inputs: packet_id — accepted packet identifier.
    # returns: Detached plain dictionary safe across service calls.
    # side_effects: Read-only database queries.
    # emitted_logs: None.
    # error_behavior: Missing run/contract data becomes empty values and stale
    #                 integration fails closed before target merge.
    # END_FUNCTION_CONTRACT
    @staticmethod
    def merge_snapshot(packet_id: str) -> dict[str, Any]:
        with get_db() as db:
            packet = db.query(Packet).filter_by(id=packet_id).first()
            run = (
                db.query(PacketRun)
                .filter_by(packet_id=packet_id)
                .order_by(PacketRun.run_number.desc())
                .first()
            )
            if packet is None:
                return {
                    "base_sha": "",
                    "conflict_keys": [],
                    "packet_contract": None,
                    "run_dir": None,
                }
            spec = packet.spec_json if isinstance(packet.spec_json, dict) else {}
            result_json = run.result_json if run and isinstance(run.result_json, dict) else {}
            parallel = result_json.get("parallel_execution")
            if not isinstance(parallel, dict):
                parallel = {}
            conflict_keys = parallel.get("conflict_keys", spec.get("conflict_keys", []))
            if not isinstance(conflict_keys, list):
                conflict_keys = []
            packet_data = {
                "id": packet.id,
                "feature_id": packet.feature_id,
                "wave_id": packet.wave_id,
                "slug": packet.slug,
                "title": packet.title,
                "description": packet.description,
                "spec_json": spec,
                "acceptance_profile": packet.acceptance_profile,
                "attempt_count": packet.attempt_count,
                "max_attempts": packet.max_attempts,
            }
            try:
                packet_contract = build_packet_contract(packet_data)
            except Exception:
                packet_contract = None
            evidence_path = run.evidence_path if run else ""
            run_dir = Path(evidence_path) if evidence_path else None
            return {
                "base_sha": (run.base_sha if run and run.base_sha else parallel.get("base_sha", "")),
                "conflict_keys": list(conflict_keys),
                "packet_contract": packet_contract,
                "run_dir": run_dir,
            }

    # START_FUNCTION_CONTRACT
    # name: update_parallel_execution
    # purpose: Persist TZ05 operational metadata and PacketRun integration SHA.
    # inputs: packet_id, metadata, optional integration SHA/evidence/failure/status.
    # returns: None.
    # side_effects: Updates latest PacketRun result_json and SHA/status columns.
    # emitted_logs: None.
    # error_behavior: Missing PacketRun is ignored for legacy/manual merges.
    # END_FUNCTION_CONTRACT
    @staticmethod
    def update_parallel_execution(
        packet_id: str,
        metadata: dict[str, Any],
        *,
        integration_base_sha: str | None = None,
        evidence: dict[str, Any] | None = None,
        failure_class: str = "",
        status: str | None = None,
    ) -> None:
        with get_db() as db:
            run = (
                db.query(PacketRun)
                .filter_by(packet_id=packet_id)
                .order_by(PacketRun.run_number.desc())
                .first()
            )
            if run is None:
                return
            result_json = dict(run.result_json) if isinstance(run.result_json, dict) else {}
            parallel = dict(result_json.get("parallel_execution") or {})
            parallel.update(metadata)
            result_json["parallel_execution"] = parallel
            if failure_class:
                result_json["failure_class"] = failure_class
            if evidence:
                result_json["integration_recheck_evidence"] = dict(evidence)
            run.result_json = result_json
            if metadata.get("base_sha") and not run.base_sha:
                run.base_sha = metadata["base_sha"]
            if integration_base_sha is not None:
                run.integration_base_sha = integration_base_sha
            if status:
                run.status = status
                run.finished_at = datetime.now(UTC)

# END_BLOCK_MERGE_GUARD
