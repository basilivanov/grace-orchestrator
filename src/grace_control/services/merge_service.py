# ############################################################################
# AI_HEADER: merge_service
# ROLE: Orchestrates packet merge: ACCEPTED → MERGED via GitService + PacketService.
# ############################################################################

# START_MODULE_CONTRACT
# purpose: Pure orchestration. No direct git/process calls — all go through
#          GitService. State transitions go through PacketService.
# inputs: Packet ID, target repo path, branch name, target branch.
# returns: MergeResult dataclass.
# side_effects: git operations in target repo, DB state transition, Event record.
# emitted_logs: merge_packet_start, merge_packet_done, merge_packet_failed.
# error_behavior: Returns MergeResult(success=False) on any failure; never raises.
# END_MODULE_CONTRACT

# START_MODULE_MAP
# mapping:
#   - dataclass: MergeResult
#   - function: is_merge_slot_wait
#   - class: MergeService
# END_MODULE_MAP

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from grace_control.config.settings import settings
from grace_control.core.contracts import build_packet_contract
from grace_control.core.stage_instrumentation import stage
from grace_control.core.structured_logger import GraceLogger
from grace_control.db import get_db
from grace_control.db.schema import Packet, PacketRun, PacketState
from grace_control.services.git_service import GitService
from grace_control.services.integration_recheck_service import (
    IntegrationRecheckResult,
    IntegrationRecheckService,
)
from grace_control.services.merge_coordinator_service import (
    MergeCoordinatorService,
    MergeLeaseBusyError,
    MergeLeaseFencedError,
    MergeLeaseTakeoverError,
)

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


@dataclass
class MergeResult:
    success: bool
    packet_id: str
    commit_sha: str
    target_repo: str
    branch: str
    target_branch: str
    error: str = ""

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


class MergeService:
    """Merges accepted packet's branch into target repo's target branch."""

    def __init__(
        self,
        git: GitService | None = None,
        packets=None,
        coordinator: MergeCoordinatorService | None = None,
        integration_recheck: IntegrationRecheckService | None = None,
    ):
        self._git = git or GitService()
        self._packets = packets  # lazy import to avoid cycle
        self._coordinator = coordinator or MergeCoordinatorService(git=self._git)
        self._integration_recheck = integration_recheck or IntegrationRecheckService(
            git=self._git,
            coordinator=self._coordinator,
        )

    # START_FUNCTION_CONTRACT
    # name: merge_packet
    # purpose: Serialize accepted packet checkout, merge, push, and MERGED
    #          transition for one target repository, including shared git
    #          worktree cleanup while the merge lease is held.
    # inputs: packet_id, target_repo_root, branch_name, target_branch, and
    #         optional worktree_path and worker_id fencing identity.
    # returns: MergeResult describing success or a typed-safe failure reason.
    # side_effects: Guarded git mutations, packet transition, and lease release.
    # emitted_logs: merge_packet_start, merge_packet_done, merge_packet_failed.
    # error_behavior: Returns unsuccessful MergeResult and never raises for
    #                 merge/coordinator failures.
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
    ) -> MergeResult:
        from grace_control.services.packet_service import PacketService
        svc = self._packets or PacketService()
        repo = Path(target_repo_root).resolve()
        holder = worker_id or f"merge:{packet_id}"

        _log.info("merge_packet_start",
            packet_id=packet_id, repo=str(repo), branch=branch_name, target_branch=target_branch)

        if not branch_name:
            return MergeResult(False, packet_id, "", str(repo), branch_name, target_branch,
                error="branch_name is required")

        if not self._coordinator.can_merge_now(packet_id, target_repo_root=repo):
            return MergeResult(
                False,
                packet_id,
                "",
                str(repo),
                branch_name,
                target_branch,
                error="waiting_for_merge_slot: deterministic accepted merge order",
            )

        packet_commit_sha = commit_sha or ""
        commit_sha = ""
        try:
            lease = self._coordinator.acquire(
                target_repo_root=repo,
                packet_id=packet_id,
                worker_id=holder,
            )
        except MergeLeaseBusyError as error:
            return MergeResult(
                False,
                packet_id,
                "",
                str(repo),
                branch_name,
                target_branch,
                error=f"waiting_for_merge_slot: {error}",
            )
        except MergeLeaseTakeoverError as error:
            return MergeResult(
                False,
                packet_id,
                "",
                str(repo),
                branch_name,
                target_branch,
                error=f"merge_takeover_blocked: {error}",
            )
        except Exception as error:
            return MergeResult(
                False,
                packet_id,
                "",
                str(repo),
                branch_name,
                target_branch,
                error=f"merge lease acquisition failed: {str(error)[:200]}",
            )

        try:
            info = self._git.validate_repo(repo)
            if not info.is_git:
                return MergeResult(False, packet_id, "", str(repo), branch_name, target_branch,
                    error=f"target_repo_root is not a git repo: {repo}")
            if not info.is_clean:
                return MergeResult(False, packet_id, "", str(repo), branch_name, target_branch,
                    error=f"target_repo is dirty: {repo}")

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

            # TZ05: capture target branch state before any target checkout or
            # merge mutation. The packet run snapshot is written at effective
            # workspace creation by PacketExecutor.
            merge_snapshot = self._merge_snapshot(packet_id)
            base_sha = str(merge_snapshot["base_sha"] or "").strip()
            conflict_keys = merge_snapshot["conflict_keys"]
            current_head = self._target_branch_head(repo, target_branch)
            integration_recheck_enabled = bool(
                getattr(settings, "integration_recheck_on_stale_base", True)
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
            self._update_parallel_execution(packet_id, parallel_execution)

            validated_integration_base = ""
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
                parallel_execution.update(
                    integration_base_sha=current_head,
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
                    worker_id=holder,
                )

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
                                worker_id=holder,
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

                        observed_head = self._target_branch_head(repo, target_branch)
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

                        # One final read occurs immediately before target
                        # checkout, closing the recheck-to-mutation window that
                        # can otherwise merge an obsolete validation result.
                        final_head = self._target_branch_head(repo, target_branch)
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
                        self._update_parallel_execution(
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
                    blocked = await self._block_stale_packet(
                        svc=svc,
                        packet_id=packet_id,
                        failure=failure,
                        parallel_execution=parallel_execution,
                        worktree_path=worktree_path,
                        repo=repo,
                        branch_name=branch_name,
                        target_branch=target_branch,
                        lease=lease,
                        worker_id=holder,
                    )
                    return blocked
            elif stale_base:
                # Explicit backwards-compatible escape hatch. It is visible
                # in result_json and never silently looks like a fresh base.
                parallel_execution["integration_recheck"] = "skipped"
                self._update_parallel_execution(packet_id, parallel_execution)

            if validated_integration_base:
                current_before_checkout = self._target_branch_head(repo, target_branch)
                if current_before_checkout != validated_integration_base:
                    race = IntegrationRecheckResult(
                        status="failed",
                        base_sha=base_sha,
                        integration_base_sha=current_before_checkout,
                        failure_class="stale_base_conflict",
                        evidence={
                            "target_advanced_after_recheck": True,
                            "validated_head": validated_integration_base,
                            "current_head": current_before_checkout,
                        },
                    )
                    parallel_execution.update(
                        integration_base_sha=current_before_checkout,
                        integration_recheck="failed",
                    )
                    return await self._block_stale_packet(
                        svc=svc,
                        packet_id=packet_id,
                        failure=race,
                        parallel_execution=parallel_execution,
                        worktree_path=worktree_path,
                        repo=repo,
                        branch_name=branch_name,
                        target_branch=target_branch,
                        lease=lease,
                        worker_id=holder,
                    )

            checkout = self._coordinator.run_mutation(
                target_repo_key=lease.target_repo_key,
                lease_token=lease.lease_token,
                packet_id=packet_id,
                worker_id=holder,
                step_name="checkout",
                operation=lambda: self._git.checkout(repo, target_branch),
            )
            if not checkout.success:
                return MergeResult(False, packet_id, "", str(repo), branch_name, target_branch,
                    error=f"checkout {target_branch} failed: {checkout.stderr}")

            self._coordinator.run_mutation(
                target_repo_key=lease.target_repo_key,
                lease_token=lease.lease_token,
                packet_id=packet_id,
                worker_id=holder,
                step_name="fetch",
                operation=lambda: self._git.fetch(repo, "origin"),
            )  # best-effort: local repos may not have origin

            if validated_integration_base:
                post_checkout_head = self._target_branch_head(repo, target_branch)
                if post_checkout_head != validated_integration_base:
                    race = IntegrationRecheckResult(
                        status="failed",
                        base_sha=base_sha,
                        integration_base_sha=post_checkout_head,
                        failure_class="stale_base_conflict",
                        evidence={
                            "target_advanced_after_recheck": True,
                            "validated_head": validated_integration_base,
                            "current_head": post_checkout_head,
                        },
                    )
                    parallel_execution.update(
                        integration_base_sha=post_checkout_head,
                        integration_recheck="failed",
                    )
                    return await self._block_stale_packet(
                        svc=svc,
                        packet_id=packet_id,
                        failure=race,
                        parallel_execution=parallel_execution,
                        worktree_path=worktree_path,
                        repo=repo,
                        branch_name=branch_name,
                        target_branch=target_branch,
                        lease=lease,
                        worker_id=holder,
                    )

            merge = self._coordinator.run_mutation(
                target_repo_key=lease.target_repo_key,
                lease_token=lease.lease_token,
                packet_id=packet_id,
                worker_id=holder,
                step_name="merge",
                operation=lambda: self._git.merge(repo, branch_name, target_branch),
            )
            if not merge.success:
                return MergeResult(False, packet_id, "", str(repo), branch_name, target_branch,
                    error=f"merge failed: {merge.stderr}")

            push = self._coordinator.run_mutation(
                target_repo_key=lease.target_repo_key,
                lease_token=lease.lease_token,
                packet_id=packet_id,
                worker_id=holder,
                step_name="push",
                operation=lambda: self._git.push(repo, "origin", target_branch),
            )
            if not push.success:
                # Push optional — local repos (tests, dev) may have no origin.
                if "does not appear to be a git repository" not in push.stderr:
                    return MergeResult(False, packet_id, "", str(repo), branch_name, target_branch,
                        error=f"push failed: {push.stderr}")

            commit_sha = self._git.current_sha(repo)
            self._coordinator.assert_current(
                target_repo_key=lease.target_repo_key,
                lease_token=lease.lease_token,
                packet_id=packet_id,
                worker_id=holder,
            )
            await svc.transition(
                packet_id, PacketState.MERGED, reason=f"merge_complete:{commit_sha[:8]}",
            )

            # TZ_RETENTION_POLICY.md Phase 1: after successful merge, delete
            # all attempt branches for this packet while still holding the
            # serialized target-repository lease.
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
                _log.warn("merge_branch_cleanup_failed",
                    packet_id=packet_id, error=str(error)[:200])

            if worktree_path:
                try:
                    cleanup_path = Path(worktree_path).resolve()
                    self._cleanup_worktree_for_merge(
                        repo,
                        cleanup_path,
                        branch_name,
                        target_repo_key=lease.target_repo_key,
                        lease_token=lease.lease_token,
                        packet_id=packet_id,
                        worker_id=holder,
                    )
                except MergeLeaseFencedError:
                    _log.warn("merge_worktree_cleanup_skipped_fenced", packet_id=packet_id)
                except Exception as error:
                    _log.warn("merge_worktree_cleanup_failed",
                        packet_id=packet_id, error=str(error)[:200])

            _log.info("merge_packet_done",
                packet_id=packet_id, commit_sha=commit_sha[:12], branch=branch_name)
            return MergeResult(True, packet_id, commit_sha, str(repo), branch_name, target_branch)
        except MergeLeaseFencedError as error:
            return MergeResult(
                False,
                packet_id,
                commit_sha,
                str(repo),
                branch_name,
                target_branch,
                error=f"merge_lease_lost: {error}",
            )
        except Exception as error:
            _log.warn("merge_state_transition_failed",
                packet_id=packet_id, error=str(error)[:200])
            return MergeResult(
                False, packet_id, commit_sha, str(repo), branch_name, target_branch,
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
                _log.warn("merge_lease_release_failed",
                    packet_id=packet_id, error=str(error)[:200])

    # START_FUNCTION_CONTRACT
    # name: _target_branch_head
    # purpose: Read the current SHA of the requested target branch without
    #          changing the target checkout.
    # inputs: repo — target repository; target_branch — branch/ref name.
    # returns: Branch SHA, or current HEAD as a compatibility fallback.
    # side_effects: Read-only git commands.
    # emitted_logs: None.
    # error_behavior: Falls back to GitService.current_sha when the branch ref
    #                 cannot be resolved by a test adapter or local repository.
    # END_FUNCTION_CONTRACT
    def _target_branch_head(self, repo: Path, target_branch: str) -> str:
        result = self._git._run(["rev-parse", target_branch], repo)
        stdout = getattr(result, "stdout", "")
        if getattr(result, "success", False) and isinstance(stdout, str) and stdout.strip():
            return stdout.strip()
        fallback = self._git.current_sha(repo)
        return fallback if isinstance(fallback, str) else ""

    # START_FUNCTION_CONTRACT
    # name: _merge_snapshot
    # purpose: Load the latest PacketRun base snapshot, result metadata, packet
    #          conflict keys, and contract needed for stale integration.
    # inputs: packet_id — accepted packet identifier.
    # returns: Detached plain dictionary safe to use across service calls.
    # side_effects: Read-only database queries.
    # emitted_logs: None.
    # error_behavior: Missing run/contract data is represented by empty values;
    #                 stale integration then fails closed before target merge.
    # END_FUNCTION_CONTRACT
    @staticmethod
    def _merge_snapshot(packet_id: str) -> dict[str, Any]:
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
    # name: _update_parallel_execution
    # purpose: Persist TZ05 operational metadata and PacketRun integration SHA.
    # inputs: packet_id, metadata, optional integration_base_sha, evidence,
    #         failure_class, and run status.
    # returns: None.
    # side_effects: Updates the latest PacketRun result_json and nullable SHA
    #                columns.
    # emitted_logs: None.
    # error_behavior: Missing PacketRun is ignored for legacy/manual merges.
    # END_FUNCTION_CONTRACT
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

    # START_FUNCTION_CONTRACT
    # name: _block_stale_packet
    # purpose: Record stale integration evidence, transition an accepted packet
    #          to BLOCKED_RECOVERABLE, release its parallel lease through the
    #          state service, and clean its packet worktree under merge fencing.
    # inputs: PacketService, packet_id, failed recheck, metadata, worktree, and
    #         active merge lease identity.
    # returns: Unsuccessful MergeResult describing the recoverable block.
    # side_effects: DB result/state/lease updates and fenced worktree cleanup.
    # emitted_logs: stale_base_packet_blocked, stale_base_cleanup_failed.
    # error_behavior: Returns a failure result even when cleanup is best effort.
    # END_FUNCTION_CONTRACT
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
        evidence = dict(failure.evidence)
        evidence.setdefault("base_sha", failure.base_sha)
        evidence.setdefault("current_head", failure.integration_base_sha)
        failure_reason = str(evidence.get("reason", "")).strip()
        failure_label = (
            f"{failure.failure_class}:{failure_reason}"
            if failure_reason
            else failure.failure_class
        )
        self._update_parallel_execution(
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
            _log.warn("stale_base_packet_block_failed", packet_id=packet_id, error=str(error)[:300])
            return MergeResult(
                False,
                packet_id,
                "",
                str(repo),
                branch_name,
                target_branch,
                error=f"{failure_label}: unable to block packet: {str(error)[:200]}",
            )
        self._update_parallel_execution(
            packet_id,
            parallel_execution,
            integration_base_sha=failure.integration_base_sha,
            evidence=evidence,
            failure_class=failure.failure_class,
            status=PacketState.BLOCKED_RECOVERABLE.value,
        )
        if worktree_path:
            try:
                self._cleanup_worktree_for_merge(
                    repo,
                    Path(worktree_path).resolve(),
                    branch_name,
                    target_repo_key=lease.target_repo_key,
                    lease_token=lease.lease_token,
                    packet_id=packet_id,
                    worker_id=worker_id,
                )
            except Exception as error:
                _log.warn("stale_base_cleanup_failed", packet_id=packet_id, error=str(error)[:300])
        return MergeResult(
            False,
            packet_id,
            "",
            str(repo),
            branch_name,
            target_branch,
            error=f"{failure_label}: target unchanged at {failure.integration_base_sha[:12]}",
        )

    # START_FUNCTION_CONTRACT
    # name: cleanup_worktree
    # purpose: Best-effort cleanup for callers outside the merge orchestration.
    # inputs: worktree_path, branch, and optional target_repo_root.
    # returns: None.
    # side_effects: Git worktree metadata and filesystem cleanup.
    # emitted_logs: worktree_git_remove_failed, worktree_prune_failed,
    #                worktree_branch_delete_failed, worktree_cleanup_failed.
    # error_behavior: Logs cleanup failures and never raises.
    # END_FUNCTION_CONTRACT
    async def cleanup_worktree(
        self,
        worktree_path: Path,
        branch: str,
        target_repo_root: Path | None = None,
    ) -> None:
        """Best-effort cleanup of worktree after merge. Logs failures, never raises.

        Order (P1#7):
        1. `git worktree remove --force` — unregister from `git worktree list`.
        2. `shutil.rmtree` — fallback if the path still exists.
        3. `git worktree prune` — drop stale admin files in `.git/worktrees/`.
        4. `git branch -D` for the specific merged branch (TZ_RETENTION_POLICY Phase 1).

        If `target_repo_root` is None, falls back to legacy behaviour (rmtree
        only); callers that have a repo handle should pass it.
        """
        try:
            wt = worktree_path.resolve()
            if target_repo_root is not None:
                repo = Path(target_repo_root).resolve()
                self._cleanup_worktree_git(repo, wt, branch)
            self._remove_worktree_filesystem(wt)
        except Exception as e:
            _log.warn("worktree_cleanup_failed", worktree=str(worktree_path), error=str(e)[:200])

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
        """Run each shared cleanup mutation under the current merge fence."""
        remove = self._coordinator.run_mutation(
            target_repo_key=target_repo_key,
            lease_token=lease_token,
            packet_id=packet_id,
            worker_id=worker_id,
            step_name="worktree_remove",
            operation=lambda: self._git.worktree_remove(repo, worktree_path, force=True),
        )
        if not remove.success:
            _log.warn("worktree_git_remove_failed",
                worktree=str(worktree_path), stderr=remove.stderr[:200])

        prune = self._coordinator.run_mutation(
            target_repo_key=target_repo_key,
            lease_token=lease_token,
            packet_id=packet_id,
            worker_id=worker_id,
            step_name="worktree_prune",
            operation=lambda: self._git.worktree_prune(repo),
        )
        if not prune.success:
            _log.warn("worktree_prune_failed",
                repo=str(repo), stderr=prune.stderr[:200])

        if branch:
            del_result = self._coordinator.run_mutation(
                target_repo_key=target_repo_key,
                lease_token=lease_token,
                packet_id=packet_id,
                worker_id=worker_id,
                step_name="worktree_branch_delete",
                operation=lambda: self._git._run(["branch", "-D", branch], repo),
            )
            if not del_result.success:
                _log.warn("worktree_branch_delete_failed",
                    branch=branch, stderr=del_result.stderr[:200])

        self._remove_worktree_filesystem(worktree_path)

    def _cleanup_worktree_git(self, repo: Path, worktree_path: Path, branch: str) -> None:
        remove = self._git.worktree_remove(repo, worktree_path, force=True)
        if not remove.success:
            _log.warn("worktree_git_remove_failed",
                worktree=str(worktree_path), stderr=remove.stderr[:200])
        prune = self._git.worktree_prune(repo)
        if not prune.success:
            _log.warn("worktree_prune_failed",
                repo=str(repo), stderr=prune.stderr[:200])
        # TZ_RETENTION_POLICY Phase 1: delete the merged branch. The full
        # sweep across attempt branches happens in merge_packet.
        if branch:
            del_result = self._git._run(["branch", "-D", branch], repo)
            if not del_result.success:
                _log.warn("worktree_branch_delete_failed",
                    branch=branch, stderr=del_result.stderr[:200])

    @staticmethod
    def _remove_worktree_filesystem(worktree_path: Path) -> None:
        if worktree_path.exists():
            import shutil
            shutil.rmtree(worktree_path, ignore_errors=True)

    def _cleanup_packet_branches(
        self,
        repo: Path,
        packet_id: str,
        *,
        target_repo_key: str,
        lease_token: str,
        worker_id: str,
    ) -> None:
        """Delete ALL `agent/<packet_id>-attempt-*` branches after a successful
        merge (TZ_RETENTION_POLICY.md Phase 1).

        Each branch-list/delete command is a separately fenced mutation so a
        multi-branch cleanup cannot outlive the merge lease. Called from
        `merge_packet` after the state transition to MERGED.
        """
        pattern = f"agent/{packet_id}-attempt-*"
        list_result = self._coordinator.run_mutation(
            target_repo_key=target_repo_key,
            lease_token=lease_token,
            packet_id=packet_id,
            worker_id=worker_id,
            step_name="branch_list",
            operation=lambda: self._git._run(["branch", "--list", pattern], repo),
        )
        if not list_result.success:
            _log.warn("merge_branch_list_failed",
                packet_id=packet_id, pattern=pattern,
                stderr=list_result.stderr[:200])
            return
        for line in list_result.stdout.splitlines():
            branch = line.strip()
            if not branch:
                continue
            if branch.startswith("* "):
                branch = branch[2:].strip()
            if not branch:
                continue
            del_result = self._coordinator.run_mutation(
                target_repo_key=target_repo_key,
                lease_token=lease_token,
                packet_id=packet_id,
                worker_id=worker_id,
                step_name="branch_delete",
                operation=lambda branch=branch: self._git._run(
                    ["branch", "-D", branch], repo
                ),
            )
            if del_result.success:
                _log.info("merge_branch_deleted",
                    packet_id=packet_id, branch=branch)
            else:
                _log.warn("merge_branch_delete_failed",
                    packet_id=packet_id, branch=branch,
                    stderr=del_result.stderr[:200])
