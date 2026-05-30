# ############################################################################
# AI_HEADER: registry_bootstrap_apply
# ROLE: Guarded operator wrapper for runtime registry bootstrap apply.
# ############################################################################

# START_MODULE_CONTRACT
# purpose: Build a bounded, guarded source-to-runtime registry bootstrap apply path.
# inputs: Explicit project configuration path, dry-run/apply mode.
# returns: RegistryBootstrapApplyResult with preflight, backup, apply, idempotence, and submit dry-run summaries.
# side_effects: Reads source packets/artifacts; writes only runtime registry state and bounded backup in apply mode.
# emitted_logs: None.
# error_behavior: Fails closed with structured errors before mutating runtime state.
# END_MODULE_CONTRACT

# START_MODULE_MAP
# mapping:
#   - class: RegistryBootstrapApplyResult
#   - function: run_registry_bootstrap_apply
# END_MODULE_MAP

from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from prefect_grace.platform.backlog_controller import BacklogController
from prefect_grace.platform.controller_backlog_bootstrap import (
    BacklogBootstrapPlan,
    PACKET_FILTER_INVALID_PREFIX,
    PACKET_FILTER_NOT_FOUND_PREFIX,
    build_backlog_bootstrap_plan,
    dataclass_to_dict,
    normalize_packet_ids,
)
from prefect_grace.platform.prefect_native_submission import submit_ready_packets_to_prefect
from prefect_grace.platform.project_adapter import load_project_adapter
from prefect_grace.platform.state_store import PacketRegistryStore, RunStore
from prefect_grace.platform.status_model import RegistryStatus


TERMINAL_STATUSES = {RegistryStatus.ACCEPTED.value, RegistryStatus.BLOCKED.value}


@dataclass
class RegistryBootstrapApplyResult:
    ok: bool
    project_key: str = ""
    dry_run: bool = True
    apply: bool = False
    packet_ids: list[str] = field(default_factory=list)
    packet_filter: dict[str, Any] = field(default_factory=dict)
    project_config: str = ""
    runtime_state_root: str = ""
    write_root: str = ""
    live_execution_disabled: bool = True
    preflight: dict[str, Any] = field(default_factory=dict)
    before_snapshot: dict[str, Any] = field(default_factory=dict)
    backup_path: str = ""
    apply_summary: dict[str, Any] = field(default_factory=dict)
    after_snapshot: dict[str, Any] = field(default_factory=dict)
    idempotence: dict[str, Any] = field(default_factory=dict)
    sync_dry_run: dict[str, Any] = field(default_factory=dict)
    submit_dry_run: dict[str, Any] = field(default_factory=dict)
    source_files_checked: int = 0
    source_mutations: list[str] = field(default_factory=list)
    writes_outside_runtime_state_root: list[str] = field(default_factory=list)
    warnings: list[dict[str, Any]] = field(default_factory=list)
    errors: list[dict[str, Any]] = field(default_factory=list)

    # START_FUNCTION_CONTRACT
    # name: to_dict
    # purpose: Convert guarded bootstrap apply result to a JSON-safe dictionary.
    # inputs: None.
    # returns: dict containing result fields.
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


def _bootstrap_plan_error(error: str) -> dict[str, Any]:
    if error.startswith(PACKET_FILTER_NOT_FOUND_PREFIX):
        message = error.removeprefix(PACKET_FILTER_NOT_FOUND_PREFIX).strip()
        return _error("PACKET_FILTER_NOT_FOUND", message)
    if error.startswith(PACKET_FILTER_INVALID_PREFIX):
        message = error.removeprefix(PACKET_FILTER_INVALID_PREFIX).strip()
        return _error("PACKET_FILTER_INVALID", message)
    return _error("BOOTSTRAP_PREFLIGHT_ERROR", error)


def _is_relative_to(path: Path, root: Path) -> bool:
    try:
        path.resolve().relative_to(root.resolve())
        return True
    except ValueError:
        return False


def _file_hash(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _source_fingerprints(project: Any, plan: BacklogBootstrapPlan) -> dict[str, str]:
    repo_root = Path(project.repo_root)
    paths: set[Path] = set()
    for candidate in plan.candidates:
        paths.add(repo_root / candidate.source_path)
        for evidence_path in candidate.evidence_paths:
            paths.add(repo_root / evidence_path)
    return {
        str(path.resolve()): _file_hash(path)
        for path in sorted(paths)
        if path.is_file()
    }


def _changed_fingerprints(before: dict[str, str], after: dict[str, str]) -> list[str]:
    changed = []
    for path, digest in before.items():
        if after.get(path) != digest:
            changed.append(path)
    for path in after:
        if path not in before:
            changed.append(path)
    return sorted(changed)


def _registry_snapshot(project: Any) -> dict[str, Any]:
    state_root = Path(project.runtime_state_root) / "state"
    packets = PacketRegistryStore(state_root).list_packets(project.project_key)
    status_counts: dict[str, int] = {}
    for packet in packets:
        status = str(packet.get("registry_status") or "unknown")
        status_counts[status] = status_counts.get(status, 0) + 1
    return {
        "packet_count": len(packets),
        "status_counts": dict(sorted(status_counts.items())),
        "packet_ids": sorted(str(packet.get("packet_id") or "") for packet in packets if packet.get("packet_id")),
    }


def _planned_upserts(plan: BacklogBootstrapPlan) -> list[dict[str, Any]]:
    planned = []
    for candidate in plan.candidates:
        if candidate.planned_action not in {"create", "update"}:
            continue
        planned.append(
            {
                "packet_id": candidate.packet_id,
                "target_status": candidate.inferred_status,
                "planned_action": candidate.planned_action,
                "current_registry_status": candidate.current_registry_status,
                "source_hash": candidate.source_hash,
                "inference_reason": candidate.inference_reason,
                "evidence_state": _evidence_state(candidate),
            }
        )
    return planned


def _evidence_state(candidate: Any) -> str:
    warning_text = "\n".join(candidate.warnings)
    if "Conflicting terminal bootstrap evidence" in warning_text:
        return "conflicting"
    if candidate.inferred_status in TERMINAL_STATUSES:
        return "terminal"
    if candidate.evidence_paths:
        return "non_terminal"
    if candidate.inference_reason == "existing_terminal_registry_source_hash_unchanged":
        return "terminal_registry_unchanged"
    return "missing"


def _preflight_summary(project: Any, plan: BacklogBootstrapPlan) -> dict[str, Any]:
    status_counts: dict[str, int] = {}
    action_counts: dict[str, int] = {}
    source_hash_matches: dict[str, bool] = {}
    registry = PacketRegistryStore(Path(project.runtime_state_root) / "state")
    for candidate in plan.candidates:
        status = str(candidate.inferred_status or "none")
        status_counts[status] = status_counts.get(status, 0) + 1
        action_counts[candidate.planned_action] = action_counts.get(candidate.planned_action, 0) + 1
        current = registry.load_packet(candidate.packet_id)
        source_hash_matches[candidate.packet_id] = bool(
            current and current.get("source_hash") == candidate.source_hash
        )
    return {
        "source_packet_candidate_count": len(plan.candidates),
        "candidate_status_counts": dict(sorted(status_counts.items())),
        "planned_action_counts": dict(sorted(action_counts.items())),
        "errors_count": len(plan.errors),
        "warnings_count": len(plan.warnings),
        "planned_upserts": _planned_upserts(plan),
        "write_root": str((Path(project.runtime_state_root) / "state").resolve()),
        "source_hash_matches_current_runtime": source_hash_matches,
        "live_submission_execution_disabled": True,
    }


def _unsafe_plan_errors(project: Any, plan: BacklogBootstrapPlan, project_config: Path) -> list[dict[str, Any]]:
    errors = []
    if not project_config.is_file():
        errors.append(_error("PROJECT_CONFIG_REQUIRED", "Apply requires an explicit project config file."))
    runtime_root = Path(project.runtime_state_root).resolve()
    write_root = (runtime_root / "state").resolve()
    repo_root = Path(project.repo_root).resolve()
    forbidden_roots = [
        repo_root / ".worktrees",
        repo_root / "prefect_grace" / "state",
        repo_root / project.packets_dir,
    ]
    if not _is_relative_to(write_root, runtime_root):
        errors.append(_error("WRITE_ROOT_ESCAPE", "Planned registry write root escapes runtime_state_root."))
    if runtime_root == repo_root or any(_is_relative_to(runtime_root, root) for root in forbidden_roots):
        errors.append(_error("UNSAFE_RUNTIME_STATE_ROOT", "runtime_state_root overlaps a forbidden source/worktree path."))
    for candidate in plan.candidates:
        warning_text = "\n".join(candidate.warnings)
        if "Conflicting terminal bootstrap evidence" in warning_text:
            errors.append(_error("CONFLICTING_TERMINAL_EVIDENCE", "Conflicting terminal evidence.", packet_id=candidate.packet_id))
        if candidate.inferred_status == RegistryStatus.ACCEPTED.value:
            weak_reason = candidate.inference_reason in {
                "strict_source_ready_no_terminal_artifact_evidence",
                "no_terminal_artifact_evidence",
            }
            if weak_reason:
                errors.append(_error("WEAK_ACCEPTANCE_EVIDENCE", "Accepted status cannot be inferred from weak source evidence.", packet_id=candidate.packet_id))
    return errors


def _write_backup(project: Any, snapshot: dict[str, Any]) -> str:
    backup_dir = Path(project.runtime_state_root) / "state" / "backups"
    backup_dir.mkdir(parents=True, exist_ok=True)
    backup_path = backup_dir / "packet_registry.bootstrap-backup.json"
    backup_path.write_text(json.dumps(snapshot, indent=2, ensure_ascii=False), encoding="utf-8")
    return str(backup_path)


def _sync_summary(project: Any) -> dict[str, Any]:
    result = BacklogController.sync(project=project, dry_run=True)
    return {
        "packets_total": result.packets_total,
        "registry_updates": result.registry_updates,
        "ready": result.ready,
        "accepted": result.accepted,
        "blocked": result.blocked,
        "changed_after_acceptance": result.changed_after_acceptance,
        "ready_for_retry": result.ready_for_retry,
        "cascading_blocked": result.cascading_blocked,
        "cycles": result.cycles,
        "warnings_count": len(result.warnings),
        "errors": result.errors,
    }


def _submit_dry_run_summary(project: Any) -> dict[str, Any]:
    before_runs = RunStore(Path(project.runtime_state_root) / "state").list_runs()
    plan = BacklogController.plan_submission(project)
    submission = submit_ready_packets_to_prefect(
        project=project,
        dry_run=True,
        submitter=None,
        execute_agent=False,
    )
    after_runs = RunStore(Path(project.runtime_state_root) / "state").list_runs()
    return {
        "packets_to_submit": plan.packets_to_submit,
        "submission_order": plan.submission_order,
        "blocked_packets": plan.blocked_packets,
        "packets_planned": submission.packets_planned,
        "packets_submitted": submission.packets_submitted,
        "prefect_runs_created": max(0, len(after_runs) - len(before_runs)),
        "warnings_count": len(plan.warnings) + len(submission.warnings),
        "errors": [*plan.errors, *submission.errors],
    }


def _writes_outside_runtime_root(project: Any, paths: list[str]) -> list[str]:
    runtime_root = Path(project.runtime_state_root).resolve()
    return [
        path
        for path in paths
        if not _is_relative_to(Path(path), runtime_root)
    ]


# START_FUNCTION_CONTRACT
# name: run_registry_bootstrap_apply
# purpose: Run guarded dry-run or explicit apply for source-to-runtime registry bootstrap.
# inputs:
#   project_config: Explicit project.yaml path.
#   apply: Whether to mutate runtime registry after preflight passes.
# returns: RegistryBootstrapApplyResult with bounded operator evidence.
# side_effects: Reads source packets and runtime state; in apply mode writes registry state and a bounded backup under runtime_state_root.
# emitted_logs: None.
# error_behavior: Returns ok=False with structured errors for unsafe preflight or apply failures.
# END_FUNCTION_CONTRACT
def run_registry_bootstrap_apply(
    *,
    project_config: Path | str,
    apply: bool = False,
    packet_ids: list[str] | tuple[str, ...] | None = None,
) -> RegistryBootstrapApplyResult:
    project_config_path = Path(project_config)
    normalized_packet_ids, packet_filter_errors = normalize_packet_ids(packet_ids)
    try:
        project = load_project_adapter(project_config_path)
    except Exception as exc:
        return RegistryBootstrapApplyResult(
            ok=False,
            dry_run=not apply,
            apply=apply,
            packet_ids=normalized_packet_ids,
            packet_filter={
                "enabled": bool(normalized_packet_ids),
                "packet_ids": normalized_packet_ids,
            },
            project_config=str(project_config_path),
            errors=[_error("PROJECT_LOAD_FAILED", str(exc))],
        )

    result = RegistryBootstrapApplyResult(
        ok=False,
        project_key=project.project_key,
        dry_run=not apply,
        apply=apply,
        packet_ids=normalized_packet_ids,
        packet_filter={
            "enabled": bool(normalized_packet_ids),
            "packet_ids": normalized_packet_ids,
        },
        project_config=str(project_config_path),
        runtime_state_root=str(Path(project.runtime_state_root).resolve()),
        write_root=str((Path(project.runtime_state_root) / "state").resolve()),
    )
    result.errors.extend(
        _error(
            "PACKET_FILTER_INVALID",
            error.removeprefix(PACKET_FILTER_INVALID_PREFIX).strip(),
        )
        for error in packet_filter_errors
    )
    if result.errors:
        return result

    preflight_plan = build_backlog_bootstrap_plan(
        project,
        dry_run=True,
        packet_ids=normalized_packet_ids,
    )
    result.preflight = _preflight_summary(project, preflight_plan)
    result.before_snapshot = _registry_snapshot(project)
    result.source_files_checked = len(_source_fingerprints(project, preflight_plan))
    result.warnings.extend(_error("BOOTSTRAP_WARNING", warning) for warning in preflight_plan.warnings)
    result.errors.extend(_bootstrap_plan_error(error) for error in preflight_plan.errors)
    result.errors.extend(_unsafe_plan_errors(project, preflight_plan, project_config_path))
    result.sync_dry_run = _sync_summary(project)
    result.submit_dry_run = _submit_dry_run_summary(project)
    if result.submit_dry_run.get("prefect_runs_created"):
        result.errors.append(_error("DRY_RUN_CREATED_PREFECT_RUNS", "submit-packets dry-run created runtime runs."))

    if result.errors:
        return result
    if not apply:
        result.ok = True
        return result

    source_before = _source_fingerprints(project, preflight_plan)
    result.backup_path = _write_backup(project, result.before_snapshot)
    apply_plan = build_backlog_bootstrap_plan(
        project,
        dry_run=False,
        packet_ids=normalized_packet_ids,
    )
    result.apply_summary = {
        "apply_count": apply_plan.apply_count,
        "errors": apply_plan.errors,
        "warnings_count": len(apply_plan.warnings),
        "planned_action_counts": _preflight_summary(project, apply_plan)["planned_action_counts"],
    }
    result.after_snapshot = _registry_snapshot(project)
    source_after = _source_fingerprints(project, preflight_plan)
    result.source_mutations = _changed_fingerprints(source_before, source_after)
    result.writes_outside_runtime_state_root = _writes_outside_runtime_root(project, [result.backup_path])
    idempotence_plan = build_backlog_bootstrap_plan(
        project,
        dry_run=True,
        packet_ids=normalized_packet_ids,
    )
    result.idempotence = {
        "planned_upserts_after_apply": _planned_upserts(idempotence_plan),
        "planned_action_counts": _preflight_summary(project, idempotence_plan)["planned_action_counts"],
        "errors": idempotence_plan.errors,
    }
    result.sync_dry_run = _sync_summary(project)
    result.submit_dry_run = _submit_dry_run_summary(project)
    result.errors.extend(_error("BOOTSTRAP_APPLY_ERROR", error) for error in apply_plan.errors)
    if result.source_mutations:
        result.errors.append(_error("SOURCE_MUTATION_DETECTED", "Source packet or evidence file changed during apply."))
    if result.writes_outside_runtime_state_root:
        result.errors.append(_error("WRITE_OUTSIDE_RUNTIME_ROOT", "Apply wrote outside runtime_state_root."))
    if result.submit_dry_run.get("prefect_runs_created"):
        result.errors.append(_error("DRY_RUN_CREATED_PREFECT_RUNS", "submit-packets dry-run created runtime runs."))
    result.ok = not result.errors
    return result
