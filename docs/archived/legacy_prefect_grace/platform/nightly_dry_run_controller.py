# ############################################################################
# AI_HEADER: nightly_dry_run_controller
# ROLE: Deterministic dry-run planner for GRACE nightly controller runs.
# ############################################################################

# START_MODULE_CONTRACT
# purpose: Build a bounded nightly dry-run plan without executing packets or mutating registry state.
# inputs: Project config, until-blocked flag, and lock max age.
# returns: NightlyDryRunResult with lock, source, runtime, plan, and side-effect summaries.
# side_effects: Creates and removes a project-scoped lock file only.
# emitted_logs: None.
# error_behavior: Returns structured blocked/failure summaries without live execution.
# END_MODULE_CONTRACT

# START_MODULE_MAP
# mapping:
#   - class: NightlyDryRunResult
#   - function: run_nightly_dry_run
# END_MODULE_MAP

from __future__ import annotations

from dataclasses import asdict, dataclass, field
import hashlib
import json
from pathlib import Path
from typing import Any

from prefect_grace.platform.backlog_controller import BacklogController
from prefect_grace.platform.controller_backlog_bootstrap import (
    BacklogBootstrapPlan,
    build_backlog_bootstrap_plan,
)
from prefect_grace.platform.prefect_native_submission import submit_ready_packets_to_prefect
from prefect_grace.platform.project_adapter import load_project_adapter
from prefect_grace.platform.runtime_lock import RuntimeLock
from prefect_grace.platform.state_store import PacketRegistryStore, RunStore
from prefect_grace.platform.status_model import RegistryStatus


MAX_PACKET_IDS = 25


@dataclass
class NightlyDryRunResult:
    ok: bool
    mode: str = "nightly_dry_run"
    project_key: str = ""
    until_blocked: bool = False
    preflight_status: str = "blocked"
    plan_id: str = ""
    plan_hash: str = ""
    state_root: str = ""
    lock: dict[str, Any] = field(default_factory=dict)
    source: dict[str, Any] = field(default_factory=dict)
    runtime: dict[str, Any] = field(default_factory=dict)
    plan: dict[str, Any] = field(default_factory=dict)
    side_effects: dict[str, Any] = field(default_factory=dict)
    warnings: list[dict[str, Any]] = field(default_factory=list)
    errors: list[dict[str, Any]] = field(default_factory=list)

    # START_FUNCTION_CONTRACT
    # name: to_dict
    # purpose: Convert nightly dry-run result to JSON-safe dictionary.
    # inputs: None.
    # returns: dict containing bounded nightly plan fields.
    # side_effects: None.
    # emitted_logs: None.
    # error_behavior: Propagates dataclass serialization errors.
    # END_FUNCTION_CONTRACT
    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _error(code: str, message: str, **extra: Any) -> dict[str, Any]:
    payload = {"code": code, "message": message}
    payload.update(extra)
    return payload


def _bounded_ids(packet_ids: list[str]) -> dict[str, Any]:
    return {
        "count": len(packet_ids),
        "items": packet_ids[:MAX_PACKET_IDS],
        "truncated": len(packet_ids) > MAX_PACKET_IDS,
    }


def _warning_class(warning: str) -> str:
    if "legacy_missing_strict_sections" in warning:
        return "legacy_missing_strict_sections"
    if "missing_controller_ids" in warning:
        return "missing_controller_ids"
    if "missing dependencies" in warning:
        return "missing_dependencies"
    return "other"


def _source_summary(plan: BacklogBootstrapPlan) -> dict[str, Any]:
    status_counts: dict[str, int] = {}
    action_counts: dict[str, int] = {}
    for candidate in plan.candidates:
        status = str(candidate.inferred_status or "none")
        status_counts[status] = status_counts.get(status, 0) + 1
        action_counts[candidate.planned_action] = action_counts.get(candidate.planned_action, 0) + 1
    warning_classes = {_warning_class(warning) for warning in plan.warnings}
    return {
        "candidates_total": len(plan.candidates),
        "status_counts": dict(sorted(status_counts.items())),
        "planned_action_counts": dict(sorted(action_counts.items())),
        "errors": len(plan.errors),
        "warnings": len(plan.warnings),
        "warning_classes": len(warning_classes),
    }


def _registry_status_counts(project: Any) -> dict[str, int]:
    registry = PacketRegistryStore(Path(project.runtime_state_root) / "state")
    counts: dict[str, int] = {}
    for packet in registry.list_packets(project.project_key):
        status = str(packet.get("registry_status") or "unknown")
        counts[status] = counts.get(status, 0) + 1
    return counts


def _terminal_mismatches(plan: BacklogBootstrapPlan) -> list[dict[str, Any]]:
    mismatches: list[dict[str, Any]] = []
    for candidate in plan.candidates:
        if candidate.planned_action not in {"create", "update"}:
            continue
        mismatches.append(
            {
                "packet_id": candidate.packet_id,
                "current_registry_status": candidate.current_registry_status,
                "target_status": candidate.inferred_status,
                "planned_action": candidate.planned_action,
                "inference_reason": candidate.inference_reason,
            }
        )
    return mismatches[:MAX_PACKET_IDS]


def _accepted_source_runtime_mismatches(plan: BacklogBootstrapPlan) -> list[str]:
    packet_ids = []
    for candidate in plan.candidates:
        if candidate.inferred_status != RegistryStatus.ACCEPTED.value:
            continue
        if candidate.current_registry_status != RegistryStatus.ACCEPTED.value:
            packet_ids.append(candidate.packet_id)
    return packet_ids


def _runtime_summary(project: Any, bootstrap_plan: BacklogBootstrapPlan, sync_result: Any) -> dict[str, Any]:
    status_counts = _registry_status_counts(project)
    stale = _terminal_mismatches(bootstrap_plan)
    accepted_mismatches = _accepted_source_runtime_mismatches(bootstrap_plan)
    return {
        "registry_packets_total": sum(status_counts.values()),
        "accepted": status_counts.get(RegistryStatus.ACCEPTED.value, 0),
        "ready": status_counts.get(RegistryStatus.READY.value, 0),
        "blocked": status_counts.get(RegistryStatus.BLOCKED.value, 0),
        "waiting": status_counts.get(RegistryStatus.WAITING_FOR_DEPENDENCIES.value, 0),
        "cascading_blocked": status_counts.get(RegistryStatus.CASCADING_BLOCKED.value, 0),
        "status_counts": dict(sorted(status_counts.items())),
        "sync": {
            "packets_total": sync_result.packets_total,
            "registry_updates": sync_result.registry_updates,
            "ready": len(sync_result.ready),
            "accepted": len(sync_result.accepted),
            "blocked": len(sync_result.blocked),
            "waiting": status_counts.get(RegistryStatus.WAITING_FOR_DEPENDENCIES.value, 0),
            "changed_after_acceptance": len(sync_result.changed_after_acceptance),
            "ready_for_retry": len(sync_result.ready_for_retry),
            "errors": len(sync_result.errors),
            "warnings": len(sync_result.warnings),
        },
        "stale_source_runtime_mismatches": stale,
        "stale_source_runtime_mismatches_total": sum(
            1
            for candidate in bootstrap_plan.candidates
            if candidate.planned_action in {"create", "update"}
        ),
        "accepted_source_still_ready_or_blocked": accepted_mismatches[:MAX_PACKET_IDS],
        "accepted_source_still_ready_or_blocked_total": len(accepted_mismatches),
    }


def _plan_summary(submission_plan: Any, submission_result: Any, *, until_blocked: bool, preflight_blocked: bool) -> dict[str, Any]:
    would_submit = list(submission_result.packets_planned)
    blocked_packets = list(submission_plan.blocked_packets)
    stop_reason = None
    if preflight_blocked:
        stop_reason = "source_runtime_mismatch"
    elif not would_submit and blocked_packets:
        stop_reason = "blocked_dependencies"
    elif not would_submit:
        stop_reason = "nothing_runnable"
    elif until_blocked and blocked_packets:
        stop_reason = "would_stop_on_blocker"
    return {
        "would_submit": would_submit[:MAX_PACKET_IDS],
        "would_submit_total": len(would_submit),
        "submission_order": list(submission_plan.submission_order)[:MAX_PACKET_IDS],
        "submission_order_total": len(submission_plan.submission_order),
        "blocked_packets": blocked_packets[:MAX_PACKET_IDS],
        "blocked_packets_total": len(blocked_packets),
        "stop_reason": stop_reason,
    }


def _side_effects(project: Any, sync_result: Any, before_run_count: int, after_run_count: int) -> dict[str, int]:
    del project
    return {
        "registry_updates": int(sync_result.registry_updates),
        "prefect_runs_created": max(0, after_run_count - before_run_count),
        "live_agents_started": 0,
        "source_files_changed": 0,
    }


def _hash_result(result: NightlyDryRunResult) -> tuple[str, str]:
    payload = result.to_dict()
    payload["lock"] = {
        key: value
        for key, value in dict(payload.get("lock") or {}).items()
        if key not in {"owner", "existing_owner"}
    }
    payload.pop("plan_id", None)
    payload.pop("plan_hash", None)
    encoded = json.dumps(payload, sort_keys=True, ensure_ascii=False).encode("utf-8")
    digest = "sha256:" + hashlib.sha256(encoded).hexdigest()
    return digest, digest


# START_FUNCTION_CONTRACT
# name: run_nightly_dry_run
# purpose: Build a locked nightly dry-run plan without live execution or registry mutation.
# inputs:
#   project_config: Explicit or default project config path.
#   until_blocked: Whether future execution would stop at first blocker.
#   lock_max_age_seconds: Stale lock replacement threshold.
# returns: NightlyDryRunResult with bounded plan summary.
# side_effects: Creates and releases the controller lock under runtime_state_root.
# emitted_logs: None.
# error_behavior: Returns ok=False on active lock, load failure, or unsafe planning evidence.
# END_FUNCTION_CONTRACT
def run_nightly_dry_run(
    *,
    project_config: Path | str | None = None,
    until_blocked: bool = False,
    lock_max_age_seconds: int = 3600,
) -> NightlyDryRunResult:
    try:
        project = load_project_adapter(project_config)
    except Exception as exc:
        return NightlyDryRunResult(
            ok=False,
            until_blocked=until_blocked,
            errors=[_error("PROJECT_LOAD_FAILED", str(exc))],
        )

    lock = RuntimeLock(
        project.runtime_state_root,
        name="backlog-controller",
        owner=f"nightly-dry-run:{project.project_key}",
        max_age_seconds=lock_max_age_seconds,
        allow_ephemeral=True,
    )
    lock_result = lock.acquire()
    result = NightlyDryRunResult(
        ok=False,
        project_key=project.project_key,
        until_blocked=until_blocked,
        state_root=str(Path(project.runtime_state_root).resolve()),
        lock=lock_result.to_dict(),
    )
    if not lock_result.acquired:
        result.errors.extend(lock_result.errors)
        return result
    if lock_result.ephemeral:
        result.warnings.append(_error("LOCK_NOT_PERSISTED", lock_result.message or "Controller lock was not persisted."))

    try:
        before_run_count = len(RunStore(Path(project.runtime_state_root) / "state").list_runs())
        bootstrap_plan = build_backlog_bootstrap_plan(project, dry_run=True)
        sync_result = BacklogController.sync(project=project, dry_run=True)
        submission_plan = BacklogController.plan_submission(project)
        submission_result = submit_ready_packets_to_prefect(
            project=project,
            dry_run=True,
            submitter=None,
            execute_agent=False,
        )
        after_run_count = len(RunStore(Path(project.runtime_state_root) / "state").list_runs())
        result.source = _source_summary(bootstrap_plan)
        result.runtime = _runtime_summary(project, bootstrap_plan, sync_result)
        preflight_blocked = bool(
            bootstrap_plan.errors
            or sync_result.errors
            or result.runtime["stale_source_runtime_mismatches_total"]
            or result.runtime["accepted_source_still_ready_or_blocked_total"]
        )
        result.preflight_status = "blocked" if preflight_blocked else "ready"
        result.plan = _plan_summary(
            submission_plan,
            submission_result,
            until_blocked=until_blocked,
            preflight_blocked=preflight_blocked,
        )
        result.side_effects = _side_effects(project, sync_result, before_run_count, after_run_count)
        result.warnings.extend(_error("BOOTSTRAP_WARNING", warning) for warning in bootstrap_plan.warnings)
        result.warnings.extend(_error("SYNC_WARNING", warning) for warning in sync_result.warnings)
        result.warnings.extend(_error("SUBMISSION_WARNING", warning) for warning in submission_plan.warnings)
        result.errors.extend(_error("BOOTSTRAP_ERROR", error) for error in bootstrap_plan.errors)
        result.errors.extend(_error("SYNC_ERROR", error) for error in sync_result.errors)
        result.errors.extend(_error("SUBMISSION_ERROR", error) for error in submission_plan.errors)
        if result.side_effects["prefect_runs_created"]:
            result.errors.append(_error("DRY_RUN_CREATED_PREFECT_RUNS", "Nightly dry-run created Prefect runs."))
        if preflight_blocked:
            result.warnings.append(_error("SOURCE_RUNTIME_PREFLIGHT_BLOCKED", "Runtime registry requires bootstrap reconciliation before nightly execution."))
        result.ok = not result.errors
    except Exception as exc:
        result.errors.append(_error("NIGHTLY_DRY_RUN_FAILED", str(exc)))
    finally:
        released = lock.release(lock_result)
        result.lock = released.to_dict()
        if released.errors:
            result.errors.extend(released.errors)
            result.ok = False

    result.plan_id, result.plan_hash = _hash_result(result)
    return result
