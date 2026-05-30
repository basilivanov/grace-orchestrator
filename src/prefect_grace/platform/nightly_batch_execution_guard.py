# ############################################################################
# AI_HEADER: nightly_batch_execution_guard
# ROLE: Guarded batch execution controller with strict limits and stop conditions.
# ############################################################################

# START_MODULE_CONTRACT
# purpose: Execute safe batch of packets under strict limits with fail-closed opt-in.
# inputs: Batch selection result or project config, execution limits, opt-in flags.
# returns: BatchExecutionResult with bounded per-packet summaries and aggregate status.
# side_effects: May execute packets through single-packet pilot when all gates pass.
# emitted_logs: None.
# error_behavior: Fails closed with structured blockers for missing opt-ins or gate failures.
# END_MODULE_CONTRACT

# START_MODULE_MAP
# mapping:
#   - dataclass: BatchExecutionResult
#   - dataclass: PacketExecutionSummary
#   - function: execute_batch_with_guard
# END_MODULE_MAP

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
import os
from pathlib import Path
from typing import Any, Callable
import concurrent.futures
import signal

from prefect_grace.platform.nightly_batch_selection import (
    BatchSelectionResult,
    select_safe_batch,
)
from prefect_grace.platform.single_live_packet_pilot import (
    SingleLivePacketPilotResult,
    run_single_live_packet_pilot,
)
from prefect_grace.platform.runtime_lock import RuntimeLock
from prefect_grace.platform.project_adapter import load_project_adapter


MAX_PACKET_SUMMARIES = 25
DEFAULT_MAX_PACKETS = 10
DEFAULT_CONCURRENCY = 1
DEFAULT_TIMEOUT_SECONDS = 3600
DEFAULT_MAX_FAILURES = 3


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


@dataclass
class PacketExecutionSummary:
    """Bounded summary of single packet execution."""
    packet_id: str
    status: str
    dry_run: bool
    live_opt_in_confirmed: bool
    git_mutation_requested: bool
    flow_run_id: str | None = None
    agent_count: int = 0
    domain_status: str | None = None
    managed_runner_status: str | None = None
    scope_status: str | None = None
    evidence_status: str | None = None
    review_status: str | None = None
    git_gate_status: str | None = None
    branch_push_status: str | None = None
    blocker_reason: str | None = None
    stop_reason: str | None = None
    changed_files_sample: list[str] = field(default_factory=list)
    execution_time_seconds: float = 0.0

    # START_FUNCTION_CONTRACT
    # name: to_dict
    # purpose: Convert packet execution summary to JSON-safe dictionary.
    # inputs: None.
    # returns: dict with bounded summary fields.
    # side_effects: None.
    # emitted_logs: None.
    # error_behavior: Propagates dataclass serialization errors.
    # END_FUNCTION_CONTRACT
    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class BatchExecutionResult:
    """Result of guarded batch execution with bounded output."""
    ok: bool
    project_key: str
    mode: str = "nightly_batch_execution_guard"
    dry_run: bool = True
    live_opt_in_confirmed: bool = False
    selected_total: int = 0
    executed_total: int = 0
    skipped_total: int = 0
    passed_total: int = 0
    blocked_total: int = 0
    failed_total: int = 0
    stop_reason: str = ""
    lock_acquired: bool = False
    lock_released: bool = False
    live_agents_started: int = 0
    prefect_runs_created: int = 0
    git_mutations_count: int = 0
    packet_summaries: list[PacketExecutionSummary] = field(default_factory=list)
    packet_summaries_total: int = 0
    execution_start: str = ""
    execution_end: str = ""
    execution_time_seconds: float = 0.0
    warnings: list[dict[str, Any]] = field(default_factory=list)
    errors: list[dict[str, Any]] = field(default_factory=list)
    blockers: list[dict[str, Any]] = field(default_factory=list)

    # START_FUNCTION_CONTRACT
    # name: to_dict
    # purpose: Convert batch execution result to JSON-safe dictionary with bounded lists.
    # inputs: None.
    # returns: dict with all result fields and lists truncated to MAX_PACKET_SUMMARIES.
    # side_effects: None.
    # emitted_logs: None.
    # error_behavior: Propagates dataclass serialization errors.
    # END_FUNCTION_CONTRACT
    def to_dict(self) -> dict[str, Any]:
        return {
            "ok": self.ok,
            "project_key": self.project_key,
            "mode": self.mode,
            "dry_run": self.dry_run,
            "live_opt_in_confirmed": self.live_opt_in_confirmed,
            "selected_total": self.selected_total,
            "executed_total": self.executed_total,
            "skipped_total": self.skipped_total,
            "passed_total": self.passed_total,
            "blocked_total": self.blocked_total,
            "failed_total": self.failed_total,
            "stop_reason": self.stop_reason,
            "lock_acquired": self.lock_acquired,
            "lock_released": self.lock_released,
            "live_agents_started": self.live_agents_started,
            "prefect_runs_created": self.prefect_runs_created,
            "git_mutations_count": self.git_mutations_count,
            "packet_summaries": [s.to_dict() for s in self.packet_summaries[:MAX_PACKET_SUMMARIES]],
            "packet_summaries_total": self.packet_summaries_total,
            "execution_start": self.execution_start,
            "execution_end": self.execution_end,
            "execution_time_seconds": self.execution_time_seconds,
            "warnings": self.warnings[:MAX_PACKET_SUMMARIES],
            "errors": self.errors[:MAX_PACKET_SUMMARIES],
            "blockers": self.blockers[:MAX_PACKET_SUMMARIES],
        }


def _error(code: str, message: str, **extra: Any) -> dict[str, Any]:
    payload = {"code": code, "message": message}
    payload.update(extra)
    return payload


def _add_blocker(result: BatchExecutionResult, code: str, message: str, **extra: Any) -> None:
    result.blockers.append(_error(code, message, **extra))


def _pilot_result_to_summary(pilot_result: SingleLivePacketPilotResult, execution_time: float) -> PacketExecutionSummary:
    """Convert pilot result to bounded summary."""
    managed_payload = dict(getattr(pilot_result, "managed_runner_result", {}) or {})
    git_payload = dict(getattr(pilot_result, "git_gate_result", {}) or {})
    changed_files_sample = git_payload.get("changed_files_sample") or managed_payload.get("changed_files_sample")
    if not changed_files_sample:
        changed_files_sample = git_payload.get("changed_files") or managed_payload.get("changed_files") or []
    if not isinstance(changed_files_sample, list):
        changed_files_sample = []
    return PacketExecutionSummary(
        packet_id=pilot_result.packet_id,
        status=pilot_result.status,
        dry_run=pilot_result.dry_run,
        live_opt_in_confirmed=pilot_result.live_opt_in_confirmed,
        git_mutation_requested=pilot_result.git_mutation_requested,
        flow_run_id=managed_payload.get("flow_run_id") or git_payload.get("flow_run_id"),
        agent_count=int(getattr(pilot_result, "live_agents_started", 0) or 0),
        domain_status=managed_payload.get("domain_status") or pilot_result.managed_runner_status,
        managed_runner_status=pilot_result.managed_runner_status,
        scope_status=pilot_result.scope_status,
        evidence_status=pilot_result.evidence_status,
        review_status=pilot_result.review_status,
        git_gate_status=pilot_result.git_gate_status,
        branch_push_status=git_payload.get("status") or pilot_result.git_gate_status,
        blocker_reason=pilot_result.blocker_reason,
        stop_reason=pilot_result.blocker_reason,
        changed_files_sample=[str(path) for path in changed_files_sample[:5]],
        execution_time_seconds=execution_time,
    )


class TimeoutException(Exception):
    """Raised when packet execution times out."""
    pass


def _timeout_handler(signum, frame):
    raise TimeoutException("Packet execution timed out")


def _is_unexpected_degradation(pilot_result: SingleLivePacketPilotResult) -> bool:
    payloads = [
        dict(getattr(pilot_result, "managed_runner_result", {}) or {}),
        dict(getattr(pilot_result, "git_gate_result", {}) or {}),
    ]
    values: list[str] = [
        str(getattr(pilot_result, "status", "") or ""),
        str(getattr(pilot_result, "blocker_reason", "") or ""),
    ]
    for payload in payloads:
        for key in (
            "observability_verdict",
            "post_test_observability_verdict",
            "degradation_status",
            "degradation_verdict",
            "verdict",
        ):
            values.append(str(payload.get(key) or ""))
    normalized = {value.lower().strip().replace("_", "-") for value in values if value}
    return "unexpected-degradation" in normalized


# START_FUNCTION_CONTRACT
# name: execute_batch_with_guard
# purpose: Execute safe batch of packets under strict limits with fail-closed opt-in.
# inputs:
#   project_config: Explicit or default project config path.
#   batch_selection: Optional pre-computed batch selection result.
#   max_packets: Maximum number of packets to execute.
#   concurrency: Maximum concurrent packet executions.
#   timeout_seconds_per_packet: Timeout for each packet execution.
#   max_failures: Stop after this many failures.
#   stop_on_degradation: Stop if unexpected degradation detected.
#   allow_git_commit: Request guarded commit for packets.
#   allow_git_push: Request guarded push for packets.
#   allow_git_merge: Request guarded merge to target branch for packets.
#   dry_run: Safe default, no execution.
#   execute: Explicitly allow execution.
#   acknowledge_live_batch: Required operator acknowledgement flag.
#   opt_in_token: Required token value or None to read GRACE_NIGHTLY_BATCH_EXECUTION_APPROVED.
#   base_ref: Git base reference for worktrees.
#   target_branch: Target branch for Git operations.
#   remote: Remote name for Git push.
#   pilot_runner: Optional test hook for single-packet pilot.
#   lock_factory: Optional test hook for runtime lock.
# returns: BatchExecutionResult with bounded per-packet summaries and aggregate status.
# side_effects: Acquires/releases runtime lock, may execute packets through pilot when all gates pass.
# emitted_logs: None.
# error_behavior: Fails closed with structured blockers for missing opt-ins, lock unavailable, or gate failures.
# END_FUNCTION_CONTRACT
def execute_batch_with_guard(
    *,
    project_config: Path | str | None = None,
    batch_selection: BatchSelectionResult | None = None,
    max_packets: int = DEFAULT_MAX_PACKETS,
    concurrency: int = DEFAULT_CONCURRENCY,
    timeout_seconds_per_packet: int = DEFAULT_TIMEOUT_SECONDS,
    max_failures: int = DEFAULT_MAX_FAILURES,
    stop_on_degradation: bool = True,
    allow_git_commit: bool = False,
    allow_git_push: bool = False,
    allow_git_merge: bool = False,
    dry_run: bool = True,
    execute: bool = False,
    acknowledge_live_batch: bool = False,
    opt_in_token: str | None = None,
    base_ref: str = "origin/master",
    target_branch: str = "master",
    remote: str = "origin",
    pilot_runner: Callable[..., Any] | None = None,
    lock_factory: Callable[..., RuntimeLock] | None = None,
) -> BatchExecutionResult:
    """
    Execute safe batch of packets under strict limits with fail-closed opt-in.

    Sequence:
    1. Load project and acquire runtime lock
    2. Generate or validate batch selection
    3. Check live execution opt-in gates (if execute=True)
    4. Execute packets sequentially or with limited concurrency
    5. Apply stop conditions (max failures, timeout, degradation)
    6. Release runtime lock on all exits
    7. Return BatchExecutionResult with bounded output

    Args:
        project_config: Explicit or default project config path
        batch_selection: Optional pre-computed batch selection result
        max_packets: Maximum number of packets to execute
        concurrency: Maximum concurrent packet executions
        timeout_seconds_per_packet: Timeout for each packet execution
        max_failures: Stop after this many failures
        stop_on_degradation: Stop if unexpected degradation detected
        allow_git_commit: Request guarded commit for packets
        allow_git_push: Request guarded push for packets
        allow_git_merge: Request guarded merge to target branch for packets
        dry_run: Safe default, no execution
        execute: Explicitly allow execution
        acknowledge_live_batch: Required operator acknowledgement flag
        opt_in_token: Required token value or None to read GRACE_NIGHTLY_BATCH_EXECUTION_APPROVED
        base_ref: Git base reference for worktrees
        target_branch: Target branch for Git operations
        remote: Remote name for Git push
        pilot_runner: Optional test hook for single-packet pilot
        lock_factory: Optional test hook for runtime lock

    Returns:
        BatchExecutionResult with bounded per-packet summaries and aggregate status
    """
    execution_start = _utc_now()

    # Load project
    try:
        project = load_project_adapter(project_config)
    except Exception as exc:
        return BatchExecutionResult(
            ok=False,
            project_key="",
            dry_run=dry_run,
            execution_start=execution_start.isoformat(),
            execution_end=_utc_now().isoformat(),
            errors=[_error("PROJECT_LOAD_FAILED", str(exc))],
        )

    result = BatchExecutionResult(
        ok=False,
        project_key=project.project_key,
        dry_run=dry_run,
        execution_start=execution_start.isoformat(),
    )

    # Acquire runtime lock
    lock_builder = lock_factory or RuntimeLock
    lock = lock_builder(
        Path(project.repo_root) / project.runtime_state_root,
        name="nightly-batch-execution",
        max_age_seconds=7200,
        allow_ephemeral=True,
    )

    lock_result = lock.acquire()
    result.lock_acquired = lock_result.acquired

    if not lock_result.acquired:
        _add_blocker(result, "LOCK_UNAVAILABLE", "Runtime lock unavailable")
        result.errors.extend(lock_result.errors)
        result.stop_reason = "lock_unavailable"
        released = lock.release(lock_result)
        result.lock_released = released.released or not lock_result.acquired
        result.execution_end = _utc_now().isoformat()
        result.execution_time_seconds = (_utc_now() - execution_start).total_seconds()
        return result

    try:
        # Generate or validate batch selection
        if batch_selection is None:
            batch_selection = select_safe_batch(
                project_config=project_config,
                max_packets=max_packets,
            )

        if not batch_selection.ok:
            _add_blocker(result, "BATCH_SELECTION_FAILED", "Batch selection failed")
            result.errors.extend(batch_selection.errors)
            result.stop_reason = "batch_selection_failed"
            return result

        result.selected_total = batch_selection.selected_total

        if allow_git_merge:
            _add_blocker(result, "MERGE_UNREACHABLE", "Nightly batch execution cannot request or apply merge")
            result.stop_reason = "merge_blocked"
            return result

        if batch_selection.selected_total == 0:
            result.ok = True
            result.stop_reason = "no_packets_selected"
            return result

        # Check live execution opt-in gates
        if execute and not dry_run:
            token = opt_in_token if opt_in_token is not None else os.environ.get("GRACE_NIGHTLY_BATCH_EXECUTION_APPROVED")

            if not acknowledge_live_batch:
                _add_blocker(result, "LIVE_BATCH_ACK_REQUIRED", "--i-understand-live-batch is required for live batch execution")
            if token != "1":
                _add_blocker(result, "LIVE_BATCH_TOKEN_REQUIRED", "GRACE_NIGHTLY_BATCH_EXECUTION_APPROVED=1 is required for live batch execution")

            if result.blockers:
                result.live_opt_in_confirmed = False
                result.stop_reason = "live_opt_in_blocked"
                return result

            result.live_opt_in_confirmed = True
        else:
            # Dry run or no execution - opt-in not required
            result.live_opt_in_confirmed = True

        # Prepare pilot runner
        if pilot_runner is None:
            pilot_runner = run_single_live_packet_pilot

        # Execute packets
        repo_root = Path(project.repo_root)
        worktree_root = repo_root / ".worktrees"
        packet_root = repo_root / project.packets_dir

        failure_count = 0

        for packet_id in batch_selection.selected_packets[:max_packets]:
            # Check stop conditions before each packet
            if failure_count >= max_failures:
                result.stop_reason = "max_failures_reached"
                break

            # Find packet file - packet_id may include wave suffix, but directory is feature_id
            # Try to find the packet file by looking for the feature directory
            # Packet ID format: FEAT-XXX-YYY-W01-ZZZ, directory is FEAT-XXX-YYY
            feature_id = packet_id
            if "-W" in packet_id:
                # Extract feature_id by removing wave and packet suffix
                parts = packet_id.split("-W")
                if len(parts) >= 2:
                    feature_id = parts[0]

            packet_file = packet_root / feature_id / "EXECUTION_PACKET.md"
            if not packet_file.exists():
                result.skipped_total += 1
                result.warnings.append(_error(
                    "PACKET_NOT_FOUND",
                    f"Packet file not found: {packet_id}",
                    packet_id=packet_id,
                ))
                continue

            # Execute packet with timeout
            packet_start = _utc_now()

            try:
                # Set up timeout signal (Unix only)
                if hasattr(signal, 'SIGALRM'):
                    signal.signal(signal.SIGALRM, _timeout_handler)
                    signal.alarm(timeout_seconds_per_packet)

                pilot_result = pilot_runner(
                    packet=packet_file,
                    repo_root=repo_root,
                    worktree_root=worktree_root,
                    project_key=project.project_key,
                    attempt=1,
                    base_ref=base_ref,
                    target_branch=target_branch,
                    remote=remote,
                    dry_run=dry_run,
                    execute_agent=execute and not dry_run,
                    acknowledge_live_agent=acknowledge_live_batch,
                    opt_in_token=opt_in_token,
                    commit=allow_git_commit,
                    push=allow_git_push,
                    merge=allow_git_merge,
                    apply_git_mutations=not dry_run,
                    timeout_seconds=timeout_seconds_per_packet,
                )

                # Cancel timeout
                if hasattr(signal, 'SIGALRM'):
                    signal.alarm(0)

            except TimeoutException:
                result.skipped_total += 1
                result.warnings.append(_error(
                    "PACKET_TIMEOUT",
                    f"Packet execution timed out after {timeout_seconds_per_packet}s: {packet_id}",
                    packet_id=packet_id,
                ))
                failure_count += 1
                continue
            except Exception as exc:
                result.skipped_total += 1
                result.errors.append(_error(
                    "PACKET_EXECUTION_FAILED",
                    f"Packet execution failed: {packet_id}: {exc}",
                    packet_id=packet_id,
                ))
                failure_count += 1
                continue

            packet_end = _utc_now()
            execution_time = (packet_end - packet_start).total_seconds()

            # Convert to summary
            summary = _pilot_result_to_summary(pilot_result, execution_time)
            result.packet_summaries.append(summary)
            result.packet_summaries_total += 1
            result.executed_total += 1

            # Track aggregate stats
            if pilot_result.live_agents_started > 0:
                result.live_agents_started += pilot_result.live_agents_started
            if pilot_result.prefect_runs_created > 0:
                result.prefect_runs_created += pilot_result.prefect_runs_created
            if pilot_result.git_gate_status in ("applied", "planned"):
                result.git_mutations_count += 1

            if stop_on_degradation and _is_unexpected_degradation(pilot_result):
                result.stop_reason = "unexpected_degradation"
                summary.status = "blocked"
                summary.stop_reason = "unexpected_degradation"
                result.failed_total += 1
                failure_count += 1
                _add_blocker(
                    result,
                    "UNEXPECTED_DEGRADATION",
                    "Packet execution reported unexpected degradation",
                    packet_id=packet_id,
                )
                result.errors.append(_error(
                    "UNEXPECTED_DEGRADATION",
                    "Packet execution reported unexpected degradation",
                    packet_id=packet_id,
                ))
                break

            # Categorize result
            if pilot_result.status in ("completed", "applied", "planned"):
                result.passed_total += 1
            elif pilot_result.status == "blocked":
                # Distinguish between scope/gate blocks and agent failures
                if pilot_result.managed_runner_status == "agent_failed":
                    result.failed_total += 1
                else:
                    result.blocked_total += 1
                failure_count += 1
            else:
                result.failed_total += 1
                failure_count += 1

        # Determine final stop reason if not already set
        if not result.stop_reason:
            if result.executed_total >= result.selected_total:
                result.stop_reason = "all_packets_executed"
            elif result.executed_total >= max_packets:
                result.stop_reason = "max_packets_reached"
            else:
                result.stop_reason = "execution_completed"

        # Success if we executed at least one packet without hitting blockers
        result.ok = (
            result.executed_total > 0
            and len(result.blockers) == 0
            and result.failed_total == 0
            and result.stop_reason != "unexpected_degradation"
        )

    finally:
        # Always release lock
        lock.release(lock_result)
        result.lock_released = lock_result.released

        # Finalize timing
        execution_end = _utc_now()
        result.execution_end = execution_end.isoformat()
        result.execution_time_seconds = (execution_end - execution_start).total_seconds()

    return result
