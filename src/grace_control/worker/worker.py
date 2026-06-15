# ############################################################################
# AI_HEADER: worker
# ROLE: Worker loop — claim→execute→release→merge with heartbeat, lease renewal,
#       fencing tokens, classified failures, and correct retry semantics.
# W07: Refactored into clear phases with ExecutionState, FailureClassification,
#      removed dead exception branches, merge failure observability.
# ############################################################################

from __future__ import annotations

import asyncio
import os
import uuid
import traceback
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any

from grace_control.adapters.packet_executor import PacketExecutionAdapter, ExecutionResult
from grace_control.core.git_context import resolve_git_execution_context, GitExecutionContext
from grace_control.core.structured_logger import GraceLogger, trace_context
from grace_control.worker.api_client import WorkerAPIClient


# ── W07: Failure classification ────────────────────────────────────────────

class WorkerFailureType(str, Enum):
    """W07: Classified failure types for the worker execution loop.

    Each type maps to a specific release/retry behavior:
    - agent_timeout: Agent exceeded timeout → retryable if attempts remain
    - agent_nonzero: Agent returned non-zero exit → retryable if safe
    - scope_violation: Agent wrote outside scope → blocked (not blindly retried)
    - worktree_preflight_failed: Git worktree setup failed → retryable
    - stale_lease: Lease expired, another worker claimed → abandon, do not retry
    - api_error: API call failed → retryable with backoff
    """
    AGENT_TIMEOUT = "agent_timeout"
    AGENT_NONZERO = "agent_nonzero"
    SCOPE_VIOLATION = "scope_violation"
    WORKTREE_PREFLIGHT_FAILED = "worktree_preflight_failed"
    STALE_LEASE = "stale_lease"
    API_ERROR = "api_error"


def classify_worker_failure(
    *,
    timeout: bool = False,
    result: ExecutionResult | None = None,
    release_stale: bool = False,
    api_error: bool = False,
    preflight_failed: bool = False,
) -> WorkerFailureType:
    """W07: Classify a worker failure into a typed failure category.

    This determines the correct release status and retry behavior.
    """
    if release_stale:
        return WorkerFailureType.STALE_LEASE
    if timeout:
        return WorkerFailureType.AGENT_TIMEOUT
    if preflight_failed:
        return WorkerFailureType.WORKTREE_PREFLIGHT_FAILED
    if api_error:
        return WorkerFailureType.API_ERROR
    if result is not None:
        # Check for scope violation from domain_status
        ds = (result.domain_status or "").lower()
        reason = (result.reason or "").lower()
        if "scope" in ds or "scope" in reason or "frozen" in reason:
            return WorkerFailureType.SCOPE_VIOLATION
        if result.domain_status == "blocked" or "blocked" in ds:
            return WorkerFailureType.SCOPE_VIOLATION
        # Non-zero agent exit (anything not accepted and not scope)
        if not result.accepted:
            return WorkerFailureType.AGENT_NONZERO
    # Default: API error for unclassified failures
    return WorkerFailureType.API_ERROR


def is_failure_retryable(failure_type: WorkerFailureType) -> bool:
    """W07: Determine if a failure type should be released as retryable.

    - STALE_LEASE: NOT retryable — another worker owns the packet.
    - SCOPE_VIOLATION: NOT automatically retryable — needs human/recovery.
    - All others: retryable when attempts remain.
    """
    if failure_type in (WorkerFailureType.STALE_LEASE, WorkerFailureType.SCOPE_VIOLATION):
        return False
    return True


# ── W07: Execution state object ─────────────────────────────────────────────

@dataclass
class ExecutionState:
    """W07: Tracks the current phase and metadata of a single packet execution.

    Replaces ad-hoc status handling with an explicit state object that
    records the current phase, failure classification, and all metadata
    needed for release/merge/retry decisions.
    """
    packet_id: str
    worker_id: str
    phase: str = "claimed"  # claimed → executing → releasing → merging → done
    failure_type: WorkerFailureType | None = None
    release_status: str = ""  # accepted, rejected, blocked
    result_data: dict[str, Any] = field(default_factory=dict)
    error_message: str = ""

    # Claim metadata
    lease_id: int | None = None
    claimed_attempt: int | None = None
    attempt: int = 0
    max_attempts: int = 0

    @property
    def has_attempts_remaining(self) -> bool:
        """Whether the packet can be retried (attempts remaining)."""
        if self.max_attempts <= 0:
            return True  # unlimited attempts
        return self.attempt < self.max_attempts

    def determine_release_status(self) -> str:
        """W07: Determine the release status based on execution result and
        failure classification.

        Rules:
        - No failure → use result-based status (accepted/rejected/blocked)
        - STALE_LEASE → do not release (already abandoned)
        - SCOPE_VIOLATION → blocked (not blindly retried)
        - Retryable failure + attempts remaining → rejected (retryable)
        - Retryable failure + no attempts remaining → failed (terminal)
        """
        if self.failure_type is None:
            # No failure — use the result
            return self.release_status or "rejected"

        if self.failure_type == WorkerFailureType.STALE_LEASE:
            # Don't release — another worker owns this packet
            return ""

        if self.failure_type == WorkerFailureType.SCOPE_VIOLATION:
            return "blocked"

        if is_failure_retryable(self.failure_type):
            if self.has_attempts_remaining:
                return "rejected"  # retryable
            else:
                return "failed"  # terminal — no attempts left

        # Default: rejected (retryable) — safe default
        return "rejected"

    def to_release_result(self) -> dict[str, Any]:
        """Build the result dict for the release API call."""
        result = dict(self.result_data)
        result["failure_type"] = self.failure_type.value if self.failure_type else None
        result["retryable"] = is_failure_retryable(self.failure_type) if self.failure_type else None
        if self.error_message:
            result["reason"] = self.error_message
        return result


# ── Release status from ExecutionResult (kept for backward compat) ──────────

def release_status_from_result(result: ExecutionResult, *, max_attempts: int = 0, attempt_count: int = 0) -> str:
    """Determine release status from execution result.

    W01/W07: Timeout/runtime failure with attempts remaining → "rejected" (retryable),
    not "failed" (terminal). Only truly terminal cases become "failed".
    Scope violations → "blocked" (not blindly retried).
    """
    if result.accepted:
        return "accepted"
    if result.domain_status == "blocked":
        return "blocked"
    # W07: Check for scope violation — block instead of blind retry
    reason = (result.reason or "").lower()
    ds = (result.domain_status or "").lower()
    if "scope" in ds or "scope" in reason or "frozen" in reason:
        return "blocked"
    # W01: Default to rejected (retryable) rather than failed (terminal).
    # The queue/owner will decide if attempts are exhausted and mark FAILED.
    return "rejected"


# ── Worker class ────────────────────────────────────────────────────────────

class Worker:
    def __init__(
        self,
        worker_id: str | None = None,
        api_url: str | None = None,
        heartbeat_interval: int = 30,
        project_root: Path | None = None,
        state_root: Path | None = None,
        worktree_root: Path | None = None,
        git_context: GitExecutionContext | None = None,
    ):
        from grace_control.config.settings import settings as _settings
        self.worker_id = worker_id or f"worker-{uuid.uuid4().hex[:8]}"
        self.api = WorkerAPIClient(api_url or _settings.api_url)
        self.heartbeat_interval = heartbeat_interval
        self.running = False
        self.log = GraceLogger("worker")

        # W01: Active claim fencing tokens — stored after claim, used in release
        self._active_packet_id: str | None = None
        self._active_lease_id: int | None = None
        self._active_claimed_attempt: int | None = None

        effective_target_repo: str | Path = (
            _settings.target_repo_root
            or os.environ.get("GRACE_TARGET_REPO_ROOT", "")
            or project_root
        )
        self._git_context = git_context or resolve_git_execution_context(
            control_plane_root=project_root,
            target_repo_root=Path(effective_target_repo) if isinstance(effective_target_repo, str) else effective_target_repo,
            runtime_state_root=state_root,
            worktree_root=worktree_root,
        )
        self.log.info("git_context",
            target_repo_root=str(self._git_context.target_repo_root),
            runtime_state_root=str(self._git_context.runtime_state_root),
            worktree_root=str(self._git_context.worktree_root),
            base_ref=self._git_context.base_ref)

        self.executor = PacketExecutionAdapter(
            project_root=self._git_context.target_repo_root,
            state_root=self._git_context.runtime_state_root,
            worktree_root=self._git_context.worktree_root,
        )

    async def start(self):
        self.log.info("worker_starting", worker_id=self.worker_id)
        from grace_control.db import init_db as _init_db
        _init_db()
        await self.api.register(self.worker_id)
        self.log.info("worker_registered", worker_id=self.worker_id)
        self.running = True

        heartbeat_task = asyncio.create_task(self._heartbeat_loop())
        try:
            await self._main_loop()
        finally:
            self.running = False
            heartbeat_task.cancel()
            try:
                await heartbeat_task
            except asyncio.CancelledError:
                pass
            await self.api.close()
            self.log.info("worker_stopped", worker_id=self.worker_id)

    async def _main_loop(self):
        from grace_control.config.settings import settings
        agent_timeout = int(os.environ.get(
            "GRACE_AGENT_TIMEOUT", str(settings.agent_timeout_seconds)))
        while self.running:
            try:
                await self._run_one_cycle(agent_timeout)
            except Exception:
                # W07: Single top-level catch for truly unexpected errors
                # (claim/API failures). Inner phases handle their own errors.
                self.log.error("main_loop_error", worker_id=self.worker_id,
                    error=traceback.format_exc()[:500])
                await asyncio.sleep(10)

    async def _run_one_cycle(self, agent_timeout: int):
        """W07: Single claim→execute→release→merge cycle.

        Refactored into clear phases with explicit ExecutionState tracking.
        Each phase sets state.phase and handles its own errors.
        """
        # ── Phase 1: CLAIM ──────────────────────────────────────────────
        claim = await self._phase_claim()
        if claim is None:
            self.log.debug("no_packets_available", worker_id=self.worker_id)
            await asyncio.sleep(5)
            return

        # Initialize execution state
        exec_state = ExecutionState(
            packet_id=claim.packet_id,
            worker_id=self.worker_id,
            phase="claimed",
            lease_id=claim.lease_id,
            claimed_attempt=claim.claimed_attempt,
            attempt=claim.attempt,
            max_attempts=claim.max_attempts,
        )

        self.log.info("packet_claimed", worker_id=self.worker_id,
            packet_id=claim.packet_id, lease_id=claim.lease_id,
            claimed_attempt=claim.claimed_attempt,
            attempt=claim.attempt)

        try:
            with trace_context(claim.packet_id):
                # ── Phase 2: EXECUTE ────────────────────────────────────
                result = await self._phase_execute(claim, exec_state, agent_timeout)

                # ── Phase 3: RELEASE ────────────────────────────────────
                await self._phase_release(exec_state, result)

                # ── Phase 4: MERGE (only on accepted) ───────────────────
                if exec_state.release_status == "accepted":
                    await self._phase_merge(exec_state, result)

                # ── Phase 5: POST-RELEASE (retry/recovery) ──────────────
                await self._phase_post_release(exec_state)

        finally:
            # W01: Clear active claim tokens
            self._active_packet_id = None
            self._active_lease_id = None
            self._active_claimed_attempt = None

    # ── Phase 1: CLAIM ──────────────────────────────────────────────────────

    async def _phase_claim(self):
        """Claim a packet from the queue. Returns PacketClaim or None."""
        try:
            claim = await self.api.claim_packet(self.worker_id)
            if claim:
                # W01: Store fencing tokens for this claim
                self._active_packet_id = claim.packet_id
                self._active_lease_id = claim.lease_id
                self._active_claimed_attempt = claim.claimed_attempt
            return claim
        except Exception as e:
            self.log.warn("claim_api_error", worker_id=self.worker_id,
                error=str(e)[:200])
            return None

    # ── Phase 2: EXECUTE ────────────────────────────────────────────────────

    async def _phase_execute(self, claim, exec_state: ExecutionState, agent_timeout: int) -> ExecutionResult | None:
        """Execute the claimed packet. Returns ExecutionResult or None on timeout/error.

        W07: Sets exec_state.failure_type on timeout/error.
        """
        exec_state.phase = "executing"
        packet_id = claim.packet_id

        try:
            self.log.info("execution_started", packet_id=packet_id, timeout_s=agent_timeout)
            result = await asyncio.wait_for(
                self.executor.execute(packet_id, self.worker_id,
                    claim_data=claim.model_dump()),
                timeout=agent_timeout,
            )
            self.log.info("execution_completed",
                packet_id=packet_id, accepted=result.accepted,
                domain_status=result.domain_status,
                duration_ms=result.duration_ms)

            # Set release status from result
            exec_state.release_status = release_status_from_result(result)
            exec_state.result_data = result.model_dump()
            return result

        except asyncio.TimeoutError:
            self.log.error("execution_timed_out", packet_id=packet_id,
                timeout_s=agent_timeout)
            # W07: Classify as agent_timeout
            exec_state.failure_type = WorkerFailureType.AGENT_TIMEOUT
            exec_state.error_message = f"Agent timed out after {agent_timeout}s"
            exec_state.result_data = {"accepted": False, "reason": "timeout"}
            return None

        except Exception as exc:
            self.log.error("execution_failed", packet_id=packet_id,
                error=traceback.format_exc()[:5000])
            # W07: Classify as agent_nonzero for generic failures
            # (retryable when attempts remain)
            exec_state.failure_type = WorkerFailureType.AGENT_NONZERO
            exec_state.error_message = str(exc)[:500]
            exec_state.result_data = {"accepted": False, "reason": "execution_error"}
            return None

    # ── Phase 3: RELEASE ────────────────────────────────────────────────────

    async def _phase_release(self, exec_state: ExecutionState, result: ExecutionResult | None):
        """Release the packet with the determined status.

        W07: Uses ExecutionState to determine the correct release status.
        Stale lease → abandon, no retry.
        """
        exec_state.phase = "releasing"
        packet_id = exec_state.packet_id

        # Determine final release status
        status = exec_state.determine_release_status()

        if not status:
            # STALE_LEASE — don't release
            self.log.warn("release_skipped_stale_lease", packet_id=packet_id)
            return

        try:
            release_result = await self._release_with_fencing(
                packet_id, status, exec_state.to_release_result(),
            )

            if release_result.get("stale_lease"):
                # W07: Stale lease — classify and abandon
                exec_state.failure_type = WorkerFailureType.STALE_LEASE
                self.log.warn("release_stale_abandoning_result",
                    packet_id=packet_id, status=status,
                    worker_id=self.worker_id)
            else:
                exec_state.release_status = status
                self.log.info("packet_released", packet_id=packet_id, status=status)

        except Exception as e:
            # W07: Release API error — classify as api_error
            exec_state.failure_type = WorkerFailureType.API_ERROR
            exec_state.error_message = f"Release failed: {str(e)[:200]}"
            self.log.warn("release_api_error",
                packet_id=packet_id, error=exec_state.error_message)

    # ── Phase 4: MERGE ──────────────────────────────────────────────────────

    async def _phase_merge(self, exec_state: ExecutionState, result: ExecutionResult | None):
        """Merge the accepted packet into the target repo.

        W07: Merge failure records an explicit observable event for manual action.
        """
        exec_state.phase = "merging"
        packet_id = exec_state.packet_id

        if result is None:
            self.log.warn("merge_skipped_no_result", packet_id=packet_id)
            return

        target_repo = str(self._git_context.target_repo_root)
        self.log.info("merging", packet_id=packet_id,
            worktree=result.worktree_path, branch=result.branch_name,
            target_repo=target_repo, sha=result.commit_sha[:12])
        try:
            await self.api.merge_packet(packet_id,
                target_repo_root=target_repo,
                worktree_path=result.worktree_path,
                branch_name=result.branch_name,
                commit_sha=result.commit_sha)
            self.log.info("merged", packet_id=packet_id)
        except Exception as merge_exc:
            # W07: Merge failure — record explicit observable event
            # so humans can take manual action. Don't silently swallow.
            merge_error = str(merge_exc)[:500]
            self.log.error("merge_failed_action_required",
                packet_id=packet_id,
                branch=result.branch_name,
                commit_sha=result.commit_sha[:12],
                error=merge_error)
            # Record the merge failure as an event for observability
            try:
                from grace_control.core.event_recorder import record_event
                record_event("packet_merge_failed", "packet", packet_id, {
                    "action_required": True,
                    "branch": result.branch_name,
                    "commit_sha": result.commit_sha[:12],
                    "target_repo": target_repo,
                    "error": merge_error,
                    "manual_action": f"Manually merge branch {result.branch_name} into target",
                })
            except Exception as evt_err:
                self.log.warn("merge_event_record_failed",
                    packet_id=packet_id, error=str(evt_err)[:200])

    # ── Phase 5: POST-RELEASE ───────────────────────────────────────────────

    async def _phase_post_release(self, exec_state: ExecutionState):
        """W07: Handle rejection retry and recovery based on failure classification.

        - Rejected + retryable → retry via API
        - Blocked → apply recovery controller
        - Stale lease → do nothing (already abandoned)
        """
        exec_state.phase = "post_release"
        packet_id = exec_state.packet_id
        status = exec_state.release_status

        if exec_state.failure_type == WorkerFailureType.STALE_LEASE:
            # W07: Stale lease — already handled, don't retry or recover
            self.log.info("stale_lease_skip_post_release", packet_id=packet_id)
            return

        if status == "rejected":
            self.log.warn("packet_rejected", packet_id=packet_id,
                reason=exec_state.error_message,
                failure_type=exec_state.failure_type.value if exec_state.failure_type else None)
            await self._handle_rejection(packet_id)
        elif status == "blocked":
            self.log.warn("packet_blocked", packet_id=packet_id,
                reason=exec_state.error_message,
                failure_type=exec_state.failure_type.value if exec_state.failure_type else None)
            await self._maybe_apply_recovery(packet_id)

    # ── Release with fencing ────────────────────────────────────────────────

    async def _release_with_fencing(
        self, packet_id: str, status: str, result: dict,
    ) -> dict:
        """W01: Release packet with lease fencing tokens.

        Returns a dict with:
          - "stale_lease": True if release was rejected due to stale lease.
            Caller MUST NOT proceed to merge/retry/recovery in this case.
          - "released": True if release succeeded.
        """
        try:
            resp = await self.api.release_packet(
                packet_id, self.worker_id, status, result,
                lease_id=self._active_lease_id,
                claimed_attempt=self._active_claimed_attempt,
            )
            # Successful release — flatten response for caller check
            resp["stale_lease"] = False
            resp["released"] = True
            return resp
        except Exception as e:
            # Check if this is a stale lease rejection (409)
            err_str = str(e)
            if "409" in err_str or "stale_lease" in err_str:
                self.log.warn("release_rejected_stale_lease",
                    packet_id=packet_id,
                    worker_id=self.worker_id,
                    lease_id=self._active_lease_id,
                    claimed_attempt=self._active_claimed_attempt,
                    error=err_str[:200])
                # W01/W07: Do not retry — another worker owns this packet now.
                # Return stale_lease flag so caller knows NOT to merge.
                return {"stale_lease": True, "released": False}
            raise

    # ── Rejection and recovery ──────────────────────────────────────────────

    async def _handle_rejection(self, packet_id: str):
        """W07: Retry a rejected packet via the API.

        The API decides if attempts are exhausted and marks FAILED.
        Worker never makes the terminal decision.
        """
        try:
            await self.api.retry_packet(packet_id, self.worker_id)
            self.log.info("packet_retried", packet_id=packet_id)
        except Exception as e:
            self.log.warn("retry_via_api_failed", packet_id=packet_id, error=str(e)[:200])

    async def _maybe_apply_recovery(self, packet_id: str):
        """W07: Apply recovery controller for blocked packets.

        Only runs when recovery controller is enabled. Bounded timeout
        prevents recovery from hanging the worker.
        """
        from grace_control.config.settings import settings
        controller_enabled = os.environ.get(
            "GRACE_RECOVERY_CONTROLLER_ENABLED",
            "true" if settings.recovery_controller_enabled else "false",
        ) == "true"
        self.log.info("recovery_check",
            packet_id=packet_id,
            controller_enabled=controller_enabled,
        )
        if not controller_enabled:
            return
        from grace_control.core.recovery_controller import RecoveryController
        ctrl = RecoveryController()
        try:
            decision = await asyncio.wait_for(
                ctrl.evaluate(packet_id, allow_apply=True),
                timeout=30,
            )
            self.log.info("recovery_applied",
                packet_id=packet_id,
                action=decision.action.value,
                reason=decision.reason,
            )
        except Exception as e:
            self.log.error("recovery_apply_failed",
                packet_id=packet_id,
                error=str(e)[:500],
            )

    # ── Heartbeat loop ──────────────────────────────────────────────────────

    async def _heartbeat_loop(self):
        """W01: Heartbeat now also renews the active lease if a packet is running."""
        while self.running:
            try:
                await self.api.heartbeat(self.worker_id)
                self.log.debug("heartbeat_sent", worker_id=self.worker_id)

                # W01: Renew active lease during execution
                if self._active_packet_id and self._active_lease_id is not None:
                    try:
                        renew_result = await self.api.renew_lease(
                            self._active_packet_id,
                            self.worker_id,
                            self._active_lease_id,
                        )
                        if renew_result:
                            self.log.debug("lease_renewed",
                                packet_id=self._active_packet_id,
                                expires_at=renew_result.get("data", {}).get("expires_at", ""),
                            )
                        else:
                            self.log.warn("lease_renewal_failed",
                                packet_id=self._active_packet_id,
                                lease_id=self._active_lease_id,
                            )
                    except Exception as e:
                        self.log.warn("lease_renewal_error",
                            packet_id=self._active_packet_id,
                            error=str(e)[:200],
                        )

            except Exception:
                self.log.warn("heartbeat_failed", worker_id=self.worker_id)
            await asyncio.sleep(self.heartbeat_interval)


async def main():
    worker = Worker()
    await worker.start()


if __name__ == "__main__":
    asyncio.run(main())
