# ############################################################################
# AI_HEADER: nightly_controlled_batch_run
# ROLE: First controlled nightly batch runner with fail-closed live gates.
# ############################################################################

# START_MODULE_CONTRACT
# purpose: Run a small rechecked nightly batch with dry-run default, concurrency one, and no merge path.
# inputs: Project config, optional saved selection, bounded limits, live opt-in flags, injected runners.
# returns: NightlyControlledBatchRunResult with bounded operator JSON.
# side_effects: Acquires/releases a runtime lock; live mode delegates packet execution to guarded runner.
# emitted_logs: None.
# error_behavior: Fails closed before live execution on missing approval, dirty recheck, lock, or limit blockers.
# END_MODULE_CONTRACT

# START_MODULE_MAP
# mapping:
#   - dataclass: ControlledPacketSummary
#   - dataclass: NightlyControlledBatchRunResult
#   - function: run_nightly_controlled_batch
# END_MODULE_MAP

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
import os
from pathlib import Path
from typing import Any, Callable

from prefect_grace.platform.nightly_batch_execution_guard import (
    BatchExecutionResult,
    execute_batch_with_guard,
)
from prefect_grace.platform.nightly_batch_recheck import (
    NightlyBatchRecheckResult,
    recheck_nightly_batch,
)
from prefect_grace.platform.nightly_batch_selection import (
    BatchLimits,
    BatchSelectionResult,
)
from prefect_grace.platform.project_adapter import load_project_adapter
from prefect_grace.platform.runtime_lock import RuntimeLock


MAX_ITEMS = 25
MAX_CHANGED_FILES_SAMPLE = 5
DEFAULT_MAX_PACKETS = 3
DEFAULT_CONCURRENCY = 1
DEFAULT_TIMEOUT_SECONDS_PER_PACKET = 1800
DEFAULT_MAX_FAILURES = 1
MAX_TIMEOUT_SECONDS_PER_PACKET = 7200


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _error(code: str, message: str, **extra: Any) -> dict[str, Any]:
    payload = {"code": code, "message": message}
    payload.update(extra)
    return payload


def _as_dict(value: Any) -> dict[str, Any]:
    if value is None:
        return {}
    if hasattr(value, "to_dict"):
        return dict(value.to_dict())
    if isinstance(value, dict):
        return dict(value)
    return {}


def _sample_changed_files(payload: dict[str, Any]) -> list[str]:
    sample = payload.get("changed_files_sample")
    if not sample:
        sample = payload.get("changed_files")
    if not isinstance(sample, list):
        return []
    return [str(item) for item in sample[:MAX_CHANGED_FILES_SAMPLE]]


@dataclass
class ControlledPacketSummary:
    packet_id: str
    status: str
    flow_run_id: str | None = None
    agent_count: int = 0
    domain_status: str | None = None
    evidence_status: str | None = None
    review_status: str | None = None
    scope_status: str | None = None
    branch_push_status: str | None = None
    stop_reason: str | None = None
    changed_files_sample: list[str] = field(default_factory=list)

    # START_FUNCTION_CONTRACT
    # name: to_dict
    # purpose: Serialize bounded per-packet operator summary.
    # inputs: None.
    # returns: Dict with bounded fields only.
    # side_effects: None.
    # emitted_logs: None.
    # error_behavior: None.
    # END_FUNCTION_CONTRACT
    def to_dict(self) -> dict[str, Any]:
        return {
            "packet_id": self.packet_id,
            "status": self.status,
            "flow_run_id": self.flow_run_id,
            "agent_count": self.agent_count,
            "domain_status": self.domain_status,
            "evidence_status": self.evidence_status,
            "review_status": self.review_status,
            "scope_status": self.scope_status,
            "branch_push_status": self.branch_push_status,
            "stop_reason": self.stop_reason,
            "changed_files_sample": self.changed_files_sample[:MAX_CHANGED_FILES_SAMPLE],
        }


@dataclass
class NightlyControlledBatchRunResult:
    ok: bool
    project_key: str
    mode: str = "nightly_controlled_batch_run"
    dry_run: bool = True
    live_opt_in_confirmed: bool = False
    selected_total: int = 0
    confirmed_total: int = 0
    executed_total: int = 0
    passed_total: int = 0
    blocked_total: int = 0
    failed_total: int = 0
    skipped_total: int = 0
    stop_reason: str = ""
    lock_acquired: bool = False
    lock_released: bool = False
    live_agents_started: int = 0
    prefect_runs_created: int = 0
    git_mutations_count: int = 0
    allow_merge: bool = False
    controls: dict[str, Any] = field(default_factory=dict)
    recheck: dict[str, Any] = field(default_factory=dict)
    packet_summaries: list[ControlledPacketSummary] = field(default_factory=list)
    packet_summaries_total: int = 0
    execution_start: str = ""
    execution_end: str = ""
    execution_time_seconds: float = 0.0
    warnings: list[dict[str, Any]] = field(default_factory=list)
    errors: list[dict[str, Any]] = field(default_factory=list)
    blockers: list[dict[str, Any]] = field(default_factory=list)

    # START_FUNCTION_CONTRACT
    # name: to_dict
    # purpose: Convert result to bounded JSON-safe dictionary.
    # inputs: None.
    # returns: Dict with result fields and bounded lists.
    # side_effects: None.
    # emitted_logs: None.
    # error_behavior: None.
    # END_FUNCTION_CONTRACT
    def to_dict(self) -> dict[str, Any]:
        return {
            "ok": self.ok,
            "project_key": self.project_key,
            "mode": self.mode,
            "dry_run": self.dry_run,
            "live_opt_in_confirmed": self.live_opt_in_confirmed,
            "selected_total": self.selected_total,
            "confirmed_total": self.confirmed_total,
            "executed_total": self.executed_total,
            "passed_total": self.passed_total,
            "blocked_total": self.blocked_total,
            "failed_total": self.failed_total,
            "skipped_total": self.skipped_total,
            "stop_reason": self.stop_reason,
            "lock_acquired": self.lock_acquired,
            "lock_released": self.lock_released,
            "live_agents_started": self.live_agents_started,
            "prefect_runs_created": self.prefect_runs_created,
            "git_mutations_count": self.git_mutations_count,
            "allow_merge": self.allow_merge,
            "controls": dict(self.controls),
            "recheck": dict(self.recheck),
            "packet_summaries": [item.to_dict() for item in self.packet_summaries[:MAX_ITEMS]],
            "packet_summaries_total": self.packet_summaries_total,
            "execution_start": self.execution_start,
            "execution_end": self.execution_end,
            "execution_time_seconds": self.execution_time_seconds,
            "warnings": self.warnings[:MAX_ITEMS],
            "errors": self.errors[:MAX_ITEMS],
            "blockers": self.blockers[:MAX_ITEMS],
        }


def _controls(
    *,
    max_packets: int,
    concurrency: int,
    timeout_seconds_per_packet: int,
    max_failures: int,
    stop_on_degradation: bool,
    allow_git_commit: bool,
    allow_git_push: bool,
) -> dict[str, Any]:
    return {
        "max_packets": max_packets,
        "concurrency": concurrency,
        "timeout_seconds_per_packet": timeout_seconds_per_packet,
        "max_failures": max_failures,
        "stop_on_degradation": stop_on_degradation,
        "allow_git_commit": allow_git_commit,
        "allow_git_push": allow_git_push,
        "allow_merge": False,
    }


def _validate_controls(
    *,
    max_packets: int,
    concurrency: int,
    timeout_seconds_per_packet: int,
    max_failures: int,
) -> list[dict[str, Any]]:
    blockers: list[dict[str, Any]] = []
    if max_packets < 1:
        blockers.append(_error("MAX_PACKETS_INVALID", "max_packets must be at least 1", blocker_class="limits"))
    if concurrency != DEFAULT_CONCURRENCY:
        blockers.append(_error("CONCURRENCY_MUST_BE_ONE", "Controlled nightly batch requires concurrency=1", blocker_class="limits"))
    if timeout_seconds_per_packet < 1 or timeout_seconds_per_packet > MAX_TIMEOUT_SECONDS_PER_PACKET:
        blockers.append(_error(
            "TIMEOUT_OUT_OF_BOUNDS",
            f"timeout_seconds_per_packet must be between 1 and {MAX_TIMEOUT_SECONDS_PER_PACKET}",
            blocker_class="limits",
        ))
    if max_failures < 1:
        blockers.append(_error("MAX_FAILURES_INVALID", "max_failures must be at least 1", blocker_class="limits"))
    return blockers


def _recheck_summary(recheck_result: NightlyBatchRecheckResult) -> dict[str, Any]:
    payload = recheck_result.to_dict()
    return {
        "ok": bool(payload.get("ok")),
        "preflight_status": payload.get("preflight_status"),
        "selected_total": payload.get("selected_total"),
        "confirmed_total": payload.get("confirmed_total"),
        "blocked_total": payload.get("blocked_total"),
        "blocker_classes": list(payload.get("blocker_classes") or [])[:MAX_ITEMS],
        "plan_hash": payload.get("plan_hash"),
        "recheck_hash": payload.get("recheck_hash"),
        "lock_status": dict(payload.get("lock_status") or {}),
        "side_effects": dict(payload.get("side_effects") or {}),
    }


def _planned_summaries(recheck_result: NightlyBatchRecheckResult) -> list[ControlledPacketSummary]:
    return [
        ControlledPacketSummary(
            packet_id=sample.packet_id,
            status=sample.status,
            stop_reason=";".join(sample.blocker_codes[:3]) if sample.blocker_codes else None,
        )
        for sample in recheck_result.packet_samples[:MAX_ITEMS]
    ]


def _execution_summaries(execution_result: BatchExecutionResult) -> list[ControlledPacketSummary]:
    summaries: list[ControlledPacketSummary] = []
    for summary in execution_result.packet_summaries[:MAX_ITEMS]:
        payload = summary.to_dict()
        summaries.append(ControlledPacketSummary(
            packet_id=str(payload.get("packet_id") or ""),
            status=str(payload.get("status") or ""),
            flow_run_id=payload.get("flow_run_id"),
            agent_count=int(payload.get("agent_count") or 0),
            domain_status=payload.get("domain_status") or payload.get("managed_runner_status"),
            evidence_status=payload.get("evidence_status"),
            review_status=payload.get("review_status"),
            scope_status=payload.get("scope_status"),
            branch_push_status=payload.get("branch_push_status") or payload.get("git_gate_status"),
            stop_reason=payload.get("stop_reason") or payload.get("blocker_reason"),
            changed_files_sample=_sample_changed_files(payload),
        ))
    return summaries


def _selection_from_recheck(
    *,
    project_key: str,
    recheck_result: NightlyBatchRecheckResult,
    max_packets: int,
) -> BatchSelectionResult:
    confirmed_packets = [
        sample.packet_id
        for sample in recheck_result.packet_samples
        if sample.status == "confirmed"
    ][:max_packets]
    return BatchSelectionResult(
        ok=True,
        project_key=project_key,
        selected_packets=confirmed_packets,
        selected_total=len(confirmed_packets),
        batch_limits=BatchLimits(max_packets=max_packets),
        stop_reason="controlled_recheck_confirmed",
    )


# START_FUNCTION_CONTRACT
# name: run_nightly_controlled_batch
# purpose: Run the first controlled nightly batch with dry-run default and live fail-closed gates.
# inputs:
#   project_config: Project config path.
#   selection_path: Optional saved batch selection JSON for recheck.
#   max_packets: Maximum packets, default 3.
#   concurrency: Must be 1.
#   timeout_seconds_per_packet: Bounded per-packet timeout.
#   max_failures: Stop threshold, default 1.
#   stop_on_degradation: Forwarded stop condition.
#   allow_git_commit: Allow delegated packet branch commit when live-approved.
#   allow_git_push: Allow delegated packet branch push when live-approved.
#   dry_run: Safe default, no execution.
#   execute: Explicitly request live execution.
#   acknowledge_live_batch: Required live acknowledgement.
#   opt_in_token: Explicit approval token or None to read GRACE_NIGHTLY_BATCH_EXECUTION_APPROVED.
#   recheck_runner: Optional injected recheck runner.
#   execution_runner: Optional injected guarded execution runner.
#   lock_factory: Optional injected runtime lock factory.
# returns: NightlyControlledBatchRunResult.
# side_effects: Runtime lock, optional guarded live execution.
# emitted_logs: None.
# error_behavior: Returns structured blockers instead of raising for known gate failures.
# END_FUNCTION_CONTRACT
def run_nightly_controlled_batch(
    *,
    project_config: Path | str | None = None,
    selection_path: Path | str | None = None,
    max_packets: int = DEFAULT_MAX_PACKETS,
    concurrency: int = DEFAULT_CONCURRENCY,
    timeout_seconds_per_packet: int = DEFAULT_TIMEOUT_SECONDS_PER_PACKET,
    max_failures: int = DEFAULT_MAX_FAILURES,
    stop_on_degradation: bool = True,
    allow_git_commit: bool = False,
    allow_git_push: bool = False,
    dry_run: bool = True,
    execute: bool = False,
    acknowledge_live_batch: bool = False,
    opt_in_token: str | None = None,
    recheck_runner: Callable[..., NightlyBatchRecheckResult] | None = None,
    execution_runner: Callable[..., BatchExecutionResult] | None = None,
    lock_factory: Callable[..., RuntimeLock] | None = None,
) -> NightlyControlledBatchRunResult:
    execution_start = _utc_now()
    try:
        project = load_project_adapter(project_config)
    except Exception as exc:
        return NightlyControlledBatchRunResult(
            ok=False,
            project_key="",
            dry_run=dry_run,
            controls=_controls(
                max_packets=max_packets,
                concurrency=concurrency,
                timeout_seconds_per_packet=timeout_seconds_per_packet,
                max_failures=max_failures,
                stop_on_degradation=stop_on_degradation,
                allow_git_commit=allow_git_commit,
                allow_git_push=allow_git_push,
            ),
            execution_start=execution_start.isoformat(),
            execution_end=_utc_now().isoformat(),
            errors=[_error("PROJECT_LOAD_FAILED", str(exc))],
            stop_reason="project_load_failed",
        )

    live_mode = bool(execute and not dry_run)
    result = NightlyControlledBatchRunResult(
        ok=False,
        project_key=project.project_key,
        dry_run=not live_mode,
        controls=_controls(
            max_packets=max_packets,
            concurrency=concurrency,
            timeout_seconds_per_packet=timeout_seconds_per_packet,
            max_failures=max_failures,
            stop_on_degradation=stop_on_degradation,
            allow_git_commit=allow_git_commit,
            allow_git_push=allow_git_push,
        ),
        execution_start=execution_start.isoformat(),
    )

    lock_builder = lock_factory or RuntimeLock
    lock = lock_builder(
        Path(project.repo_root) / project.runtime_state_root,
        name="nightly-controlled-batch-run",
        max_age_seconds=MAX_TIMEOUT_SECONDS_PER_PACKET,
        allow_ephemeral=True,
    )
    lock_result = lock.acquire()
    result.lock_acquired = lock_result.acquired
    if not lock_result.acquired:
        result.blockers.append(_error("LOCK_UNAVAILABLE", "Runtime lock unavailable", blocker_class="lock"))
        result.errors.extend(lock_result.errors)
        result.stop_reason = "lock_unavailable"
        released = lock.release(lock_result)
        result.lock_released = released.released or not lock_result.acquired
        result.execution_end = _utc_now().isoformat()
        result.execution_time_seconds = (_utc_now() - execution_start).total_seconds()
        return result

    try:
        result.blockers.extend(_validate_controls(
            max_packets=max_packets,
            concurrency=concurrency,
            timeout_seconds_per_packet=timeout_seconds_per_packet,
            max_failures=max_failures,
        ))
        if result.blockers:
            result.stop_reason = "control_blocked"
            return result

        if live_mode:
            token = opt_in_token if opt_in_token is not None else os.environ.get("GRACE_NIGHTLY_BATCH_EXECUTION_APPROVED")
            if not acknowledge_live_batch:
                result.blockers.append(_error(
                    "LIVE_BATCH_ACK_REQUIRED",
                    "--i-understand-live-batch is required for live controlled batch execution",
                    blocker_class="approval",
                ))
            if token != "1":
                result.blockers.append(_error(
                    "LIVE_BATCH_TOKEN_REQUIRED",
                    "GRACE_NIGHTLY_BATCH_EXECUTION_APPROVED=1 is required for live controlled batch execution",
                    blocker_class="approval",
                ))
            if result.blockers:
                result.stop_reason = "live_opt_in_blocked"
                return result
            result.live_opt_in_confirmed = True
        else:
            result.live_opt_in_confirmed = True

        recheck = recheck_runner or recheck_nightly_batch
        recheck_result = recheck(
            project_config=project_config,
            selection_path=selection_path,
            max_packets=max_packets,
            max_cost="live_required",
        )
        result.recheck = _recheck_summary(recheck_result)
        result.selected_total = recheck_result.selected_total
        result.confirmed_total = recheck_result.confirmed_total
        result.blocked_total = recheck_result.blocked_total
        result.packet_summaries = _planned_summaries(recheck_result)
        result.packet_summaries_total = recheck_result.packet_samples_total
        result.warnings.extend(recheck_result.warnings[:MAX_ITEMS])
        result.errors.extend(recheck_result.errors[:MAX_ITEMS])

        if not recheck_result.ok:
            result.blockers.extend(recheck_result.blockers[:MAX_ITEMS])
            result.stop_reason = "recheck_blocked"
            return result

        if recheck_result.confirmed_total == 0:
            result.ok = True
            result.stop_reason = "no_packets_selected"
            return result

        if not live_mode:
            result.ok = True
            result.stop_reason = "dry_run_complete"
            return result

        execute_guard = execution_runner or execute_batch_with_guard
        execution_result = execute_guard(
            project_config=project_config,
            batch_selection=_selection_from_recheck(
                project_key=project.project_key,
                recheck_result=recheck_result,
                max_packets=max_packets,
            ),
            max_packets=max_packets,
            concurrency=DEFAULT_CONCURRENCY,
            timeout_seconds_per_packet=timeout_seconds_per_packet,
            max_failures=max_failures,
            stop_on_degradation=stop_on_degradation,
            allow_git_commit=allow_git_commit,
            allow_git_push=allow_git_push,
            allow_git_merge=False,
            dry_run=False,
            execute=True,
            acknowledge_live_batch=True,
            opt_in_token=opt_in_token,
        )
        result.ok = execution_result.ok
        result.executed_total = execution_result.executed_total
        result.skipped_total = execution_result.skipped_total
        result.passed_total = execution_result.passed_total
        result.blocked_total = execution_result.blocked_total
        result.failed_total = execution_result.failed_total
        result.live_agents_started = execution_result.live_agents_started
        result.prefect_runs_created = execution_result.prefect_runs_created
        result.git_mutations_count = execution_result.git_mutations_count
        result.stop_reason = execution_result.stop_reason
        result.packet_summaries = _execution_summaries(execution_result)
        result.packet_summaries_total = execution_result.packet_summaries_total
        result.warnings.extend(execution_result.warnings[:MAX_ITEMS])
        result.errors.extend(execution_result.errors[:MAX_ITEMS])
        result.blockers.extend(execution_result.blockers[:MAX_ITEMS])
    finally:
        lock.release(lock_result)
        result.lock_released = lock_result.released
        execution_end = _utc_now()
        result.execution_end = execution_end.isoformat()
        result.execution_time_seconds = (execution_end - execution_start).total_seconds()

    return result
