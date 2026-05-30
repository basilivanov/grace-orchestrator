# ############################################################################
# AI_HEADER: prefect_real_dry_run_seeded_smoke
# ROLE: Registry-seeded real Prefect dry-run smoke harness.
# ############################################################################

# START_MODULE_CONTRACT
# purpose: Seed a temp packet registry and submit exactly one runnable child to real Prefect in agent dry-run mode.
# inputs: Project config path plus explicit temporary state, worktree, and synthetic packet roots.
# returns: PrefectRealDryRunSeededSmokeResult with JSON-safe registry, planning, submission, and status evidence.
# side_effects: Writes synthetic packets, temp registry state, and may create one Prefect flow run.
# emitted_logs: None.
# error_behavior: Returns structured validation, submission, and wait errors; expected operator blocks do not raise.
# END_MODULE_CONTRACT

# START_MODULE_MAP
# mapping:
#   - class: PrefectRealDryRunSeededSmokeResult
#   - function: run_prefect_real_dry_run_seeded_smoke
# END_MODULE_MAP

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from pathlib import Path
import shutil
import subprocess
import tempfile
import time
from typing import Any, Callable

import yaml

from prefect_grace.platform.backlog_controller import BacklogController
from prefect_grace.platform.controller_backlog_bootstrap import build_backlog_bootstrap_plan
from prefect_grace.platform.prefect_e2e_real_dry_run_smoke import (
    FAILURE_STATE_TYPES,
    SUCCESS_DOMAIN_STATUSES,
    SUCCESS_STATE_TYPES,
    _normalize_state_type,
    _read_prefect_flow_run_status,
    _wait_for_flow_run,
)
from prefect_grace.platform.prefect_native_submission import submit_ready_packets_to_prefect
from prefect_grace.platform.project_adapter import load_project_adapter
from prefect_grace.tasks.prefect_submitter import E2E_PACKET_DEPLOYMENT_NAME

SMOKE_MODE = "prefect_real_dry_run_seeded_smoke"
SMOKE_FEATURE_ID = "FEAT-GRACE-PREFECT-REAL-DRY-RUN-SEEDED-SMOKE"
SMOKE_WAVE_ID = "W01"
PACKET_PARENT_ACCEPTED = "PARENT-ACCEPTED"
PACKET_CHILD_RUNNABLE = "CHILD-RUNNABLE"
PACKET_CHILD_MISSING_DEP = "CHILD-MISSING-DEP"
PACKET_PARENT_BLOCKED = "PARENT-BLOCKED"
PACKET_CHILD_BLOCKED_DEP = "CHILD-BLOCKED-DEP"
PACKET_SOURCE_STATUS_ONLY = "PARENT-SOURCE-STATUS-ONLY"
PACKET_COMMAND_PASSED = "COMMAND-STATUS-PASSED"
MISSING_DEPENDENCY_ID = "MISSING-DEPENDENCY"


#START_BLOCK_MODELS
@dataclass(frozen=True)
class PrefectRealDryRunSeededSmokeResult:
    ok: bool
    project_key: str
    mode: str
    state_root: str
    worktree_root: str
    packet_root: str
    selected_packet_id: str | None
    bootstrap_apply_count: int
    sync_plan: dict[str, Any]
    submit_plan: dict[str, Any]
    deployment_name: str | None
    work_queue_name: str | None
    flow_run_id: str | None
    flow_run_name: str | None
    flow_run_url: str | None
    submitted: bool
    waited: bool
    prefect_state_type: str | None
    prefect_state_name: str | None
    domain_status: str | None
    artifact_ids: list[str]
    prefect_runs_created: int
    live_agents_started: int
    writes_outside_temp_roots: list[str]
    warnings: list[str]
    errors: list[dict[str, Any]]
    cases: list[dict[str, Any]] = field(default_factory=list)

    # START_FUNCTION_CONTRACT
    # name: to_dict
    # purpose: Serialize seeded smoke result to a JSON-safe dictionary.
    # inputs:
    #   self: PrefectRealDryRunSeededSmokeResult instance.
    # returns: dict[str, Any] with result fields and case evidence.
    # side_effects: None.
    # emitted_logs: None.
    # error_behavior: None.
    # END_FUNCTION_CONTRACT
    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


#END_BLOCK_MODELS
#START_BLOCK_FIXTURE_BUILDING
def _packet_markdown(packet_id: str, *, status: str = "ready", depends_on: list[str] | None = None) -> str:
    dependency_line = ""
    if depends_on:
        dependency_line = f"- depends_on: `{', '.join(depends_on)}`\n"
    return f"""# Execution Packet: {packet_id}

## Objective
Synthetic registry-seeded real Prefect dry-run smoke packet for {packet_id}.

## Slice
- packet_id: `{packet_id}`
- feature_id: `{SMOKE_FEATURE_ID}`
- wave_id: `{SMOKE_WAVE_ID}`
- status: `{status}`
{dependency_line}
## Allowed Write Scope
- scratch/grace-prefect-real-dry-run-seeded-smoke/**

## Frozen Scope
- backend/**
- frontend/**
- prefect_grace/**
- .env
- docker-compose*.yml
- scripts/**
- tools/**

## Must Preserve
- Synthetic smoke fixtures remain isolated to explicit temporary roots.
- Live agent execution remains disabled.

## Verification
Submit through the E2E Prefect packet runner with dry_run=true and execute_agent=false.

## Expected Evidence
- Registry plan evidence.
- Prefect submission metadata.
- Zero live agents.

## Escalation Triggers
- More than one packet would be submitted.
- Live agent execution is requested.
- Writes outside temporary smoke roots are detected.
"""


def _write_packet(
    packets_dir: Path,
    packet_id: str,
    *,
    status: str = "ready",
    depends_on: list[str] | None = None,
) -> Path:
    packet_dir = packets_dir / packet_id
    packet_dir.mkdir(parents=True, exist_ok=True)
    packet_path = packet_dir / "EXECUTION_PACKET.md"
    packet_path.write_text(_packet_markdown(packet_id, status=status, depends_on=depends_on), encoding="utf-8")
    return packet_path


def _write_smoke_fixtures(packet_root: Path) -> dict[str, Path]:
    packets_dir = packet_root / "packets"
    if packets_dir.exists():
        shutil.rmtree(packets_dir)
    packets_dir.mkdir(parents=True, exist_ok=True)

    packet_paths = {
        PACKET_PARENT_ACCEPTED: _write_packet(packets_dir, PACKET_PARENT_ACCEPTED),
        PACKET_CHILD_RUNNABLE: _write_packet(
            packets_dir,
            PACKET_CHILD_RUNNABLE,
            depends_on=[PACKET_PARENT_ACCEPTED],
        ),
        PACKET_CHILD_MISSING_DEP: _write_packet(
            packets_dir,
            PACKET_CHILD_MISSING_DEP,
            depends_on=[MISSING_DEPENDENCY_ID],
        ),
        PACKET_PARENT_BLOCKED: _write_packet(packets_dir, PACKET_PARENT_BLOCKED),
        PACKET_CHILD_BLOCKED_DEP: _write_packet(
            packets_dir,
            PACKET_CHILD_BLOCKED_DEP,
            depends_on=[PACKET_PARENT_BLOCKED],
        ),
        PACKET_SOURCE_STATUS_ONLY: _write_packet(
            packets_dir,
            PACKET_SOURCE_STATUS_ONLY,
            status="accepted",
            depends_on=[MISSING_DEPENDENCY_ID],
        ),
        PACKET_COMMAND_PASSED: _write_packet(
            packets_dir,
            PACKET_COMMAND_PASSED,
            depends_on=[MISSING_DEPENDENCY_ID],
        ),
    }

    parent_review = packet_paths[PACKET_PARENT_ACCEPTED].parent / "REVIEWS" / "review-0001.md"
    parent_review.parent.mkdir(parents=True, exist_ok=True)
    parent_review.write_text("verdict: ACCEPTED\n", encoding="utf-8")

    blocked_summary = packet_paths[PACKET_PARENT_BLOCKED].parent / "SUMMARY.md"
    blocked_summary.write_text("current_status: blocked\n", encoding="utf-8")

    command_evidence = packet_paths[PACKET_COMMAND_PASSED].parent / "EVIDENCE" / "attempt-0001" / "evidence_manifest.json"
    command_evidence.parent.mkdir(parents=True, exist_ok=True)
    command_evidence.write_text(
        '{"status": "passed", "commands": [{"name": "pytest", "status": "passed"}]}',
        encoding="utf-8",
    )
    return packet_paths


#END_BLOCK_FIXTURE_BUILDING
#START_BLOCK_HELPERS
def _error(code: str, message: str, **extra: Any) -> dict[str, Any]:
    return {"code": code, "message": message, **extra}


def _case(name: str, ok: bool, **data: Any) -> dict[str, Any]:
    result = {"name": name, "ok": ok, **data}
    if not ok:
        result["errors"] = [_error("CASE_FAILED", f"{name} failed")]
    return result


def _is_relative_to(path: Path, root: Path) -> bool:
    try:
        path.resolve().relative_to(root.resolve())
        return True
    except ValueError:
        return False


def _is_dedicated_temp_root(path: Path) -> bool:
    temp_root = Path(tempfile.gettempdir()).resolve()
    resolved = path.resolve()
    try:
        relative = resolved.relative_to(temp_root)
    except ValueError:
        return False
    return len(relative.parts) >= 2


def _roots_overlap(left: Path, right: Path) -> bool:
    left_resolved = left.resolve()
    right_resolved = right.resolve()
    return (
        left_resolved == right_resolved
        or _is_relative_to(left_resolved, right_resolved)
        or _is_relative_to(right_resolved, left_resolved)
    )


def _validate_roots(*, state_root: Path, worktree_root: Path, packet_root: Path, repo_root: Path) -> list[dict[str, Any]]:
    errors: list[dict[str, Any]] = []
    root_specs = [
        ("state_root", state_root, "UNSAFE_STATE_ROOT"),
        ("worktree_root", worktree_root, "UNSAFE_WORKTREE_ROOT"),
        ("packet_root", packet_root, "UNSAFE_PACKET_ROOT"),
    ]
    for label, root, code in root_specs:
        if _is_relative_to(root, Path("/var/lib/grace-orchestrator")):
            errors.append(_error(code, f"{label} must not be under /var/lib/grace-orchestrator"))
            continue
        if _is_relative_to(root, repo_root / "prefect_grace" / "state"):
            errors.append(_error(code, f"{label} must not be under prefect_grace/state"))
            continue
        if _is_relative_to(root, repo_root):
            errors.append(_error(code, f"{label} must not be inside the repository"))
            continue
        if not _is_dedicated_temp_root(root):
            errors.append(_error(code, f"{label} must be a dedicated child directory under the system temp root"))

    for left_label, left, right_label, right in [
        ("state_root", state_root, "worktree_root", worktree_root),
        ("state_root", state_root, "packet_root", packet_root),
        ("worktree_root", worktree_root, "packet_root", packet_root),
    ]:
        if _roots_overlap(left, right):
            errors.append(_error("OVERLAPPING_TEMP_ROOTS", f"{left_label} and {right_label} must be separate temp roots"))
    return errors


def _reset_temp_roots(state_root: Path, worktree_root: Path, packet_root: Path) -> None:
    shutil.rmtree(state_root, ignore_errors=True)
    shutil.rmtree(worktree_root, ignore_errors=True)
    shutil.rmtree(packet_root, ignore_errors=True)
    state_root.mkdir(parents=True, exist_ok=True)
    worktree_root.mkdir(parents=True, exist_ok=True)
    packet_root.mkdir(parents=True, exist_ok=True)


def _run_git(args: list[str], cwd: Path) -> None:
    subprocess.run(["git", *args], cwd=cwd, capture_output=True, text=True, check=True)


def _has_head(repo_root: Path) -> bool:
    result = subprocess.run(["git", "rev-parse", "--verify", "HEAD"], cwd=repo_root, capture_output=True, text=True)
    return result.returncode == 0


def _ensure_synthetic_git_repo(packet_root: Path) -> None:
    if not (packet_root / ".git").exists():
        _run_git(["init"], packet_root)
    _run_git(["config", "user.name", "GRACE Smoke"], packet_root)
    _run_git(["config", "user.email", "grace-smoke@example.invalid"], packet_root)
    if not _has_head(packet_root):
        _run_git(["commit", "--allow-empty", "-m", "Initial synthetic smoke commit"], packet_root)
    _run_git(["worktree", "prune"], packet_root)


def _sync_result_to_dict(sync_result: Any) -> dict[str, Any]:
    return {
        "packets_total": sync_result.packets_total,
        "registry_updates": sync_result.registry_updates,
        "ready": sync_result.ready,
        "accepted": sync_result.accepted,
        "blocked": sync_result.blocked,
        "changed_after_acceptance": sync_result.changed_after_acceptance,
        "ready_for_retry": sync_result.ready_for_retry,
        "cascading_blocked": sync_result.cascading_blocked,
        "cycles": sync_result.cycles,
        "warnings": sync_result.warnings,
        "errors": sync_result.errors,
    }


def _file_snapshot(root: Path) -> dict[str, str]:
    snapshot: dict[str, str] = {}
    if not root.exists():
        return snapshot
    for path in sorted(root.rglob("*")):
        if path.is_file():
            snapshot[str(path.resolve())] = path.read_text(encoding="utf-8", errors="replace")
    return snapshot


def _load_registry_map(state_root: Path) -> dict[str, Any]:
    registry_path = state_root / "state" / "packet_registry.yaml"
    if not registry_path.exists():
        return {}
    data = yaml.safe_load(registry_path.read_text(encoding="utf-8")) or {}
    return data if isinstance(data, dict) else {}


def _status(registry_map: dict[str, Any], packet_id: str) -> str | None:
    record = registry_map.get(packet_id)
    return record.get("registry_status") if isinstance(record, dict) else None


def _paths_outside_roots(paths: list[Path], roots: list[Path]) -> list[str]:
    outside = []
    for path in paths:
        if not any(_is_relative_to(path, root) for root in roots):
            outside.append(str(path))
    return outside


def _empty_result(
    *,
    ok: bool,
    project_key: str,
    state_root: Path,
    worktree_root: Path,
    packet_root: Path,
    errors: list[dict[str, Any]],
    warnings: list[str] | None = None,
) -> PrefectRealDryRunSeededSmokeResult:
    return PrefectRealDryRunSeededSmokeResult(
        ok=ok,
        project_key=project_key,
        mode=SMOKE_MODE,
        state_root=str(state_root),
        worktree_root=str(worktree_root),
        packet_root=str(packet_root),
        selected_packet_id=None,
        bootstrap_apply_count=0,
        sync_plan={},
        submit_plan={},
        deployment_name=None,
        work_queue_name=None,
        flow_run_id=None,
        flow_run_name=None,
        flow_run_url=None,
        submitted=False,
        waited=False,
        prefect_state_type=None,
        prefect_state_name=None,
        domain_status=None,
        artifact_ids=[],
        prefect_runs_created=0,
        live_agents_started=0,
        writes_outside_temp_roots=[],
        warnings=warnings or [],
        errors=errors,
        cases=[],
    )


def _seeded_wait_errors(errors: list[dict[str, Any]]) -> list[dict[str, Any]]:
    mapped = []
    for error in errors:
        if error.get("code") == "PREFECT_DRY_RUN_TIMEOUT":
            mapped.append({**error, "code": "PREFECT_SEEDED_DRY_RUN_TIMEOUT"})
        else:
            mapped.append(error)
    return mapped


#END_BLOCK_HELPERS
#START_BLOCK_SMOKE
# START_FUNCTION_CONTRACT
# name: run_prefect_real_dry_run_seeded_smoke
# purpose: Seed a temp registry and submit exactly one runnable child to real Prefect in dry-run agent mode.
# inputs:
#   project_config: Path to project config.
#   state_root: Explicit temporary state root.
#   worktree_root: Explicit temporary worktree root.
#   packet_root: Explicit synthetic packet root.
#   timeout_seconds: Maximum Prefect wait seconds.
#   poll_interval_seconds: Prefect wait poll interval seconds.
#   wait: Whether to wait for Prefect terminal/successful state.
#   json_safe: Retained for API compatibility; result is JSON-safe.
#   execute_agent: Must remain False; true is rejected before submission.
#   submitter: Optional test hook; default uses real Prefect E2EPacketSubmitter.
#   status_reader: Optional test hook; default reads real Prefect status.
#   sleep_fn: Optional test hook for wait sleeps.
# returns: PrefectRealDryRunSeededSmokeResult.
# side_effects: Writes temp fixtures/state and may create one Prefect flow run.
# emitted_logs: None.
# error_behavior: Returns structured errors instead of raising for expected smoke failures.
# END_FUNCTION_CONTRACT
def run_prefect_real_dry_run_seeded_smoke(
    *,
    project_config: Path,
    state_root: Path,
    worktree_root: Path,
    packet_root: Path,
    timeout_seconds: int = 900,
    poll_interval_seconds: int = 5,
    wait: bool = True,
    json_safe: bool = True,
    execute_agent: bool = False,
    submitter: Callable[..., dict[str, Any]] | None = None,
    status_reader: Callable[[str], dict[str, Any]] | None = None,
    sleep_fn: Callable[[float], None] | None = None,
) -> PrefectRealDryRunSeededSmokeResult:
    base_adapter = load_project_adapter(project_config)
    repo_root = Path(base_adapter.repo_root)
    warnings: list[str] = []
    errors: list[dict[str, Any]] = []

    if execute_agent:
        return _empty_result(
            ok=False,
            project_key=base_adapter.project_key,
            state_root=state_root,
            worktree_root=worktree_root,
            packet_root=packet_root,
            errors=[_error("PREFECT_SEEDED_DRY_RUN_EXECUTE_AGENT_REJECTED", "Seeded smoke forbids live agent execution.")],
        )

    root_errors = _validate_roots(
        state_root=state_root,
        worktree_root=worktree_root,
        packet_root=packet_root,
        repo_root=repo_root,
    )
    if root_errors:
        return _empty_result(
            ok=False,
            project_key=base_adapter.project_key,
            state_root=state_root,
            worktree_root=worktree_root,
            packet_root=packet_root,
            errors=root_errors,
        )

    _reset_temp_roots(state_root, worktree_root, packet_root)
    _ensure_synthetic_git_repo(packet_root)
    _write_smoke_fixtures(packet_root)

    adapter = load_project_adapter(
        project_config,
        overrides={
            "repo_root": str(packet_root),
            "packets_dir": "packets",
            "runtime_state_root": str(state_root),
            "artifact_root": str(state_root / "artifacts"),
            "worktree_root": str(worktree_root),
        },
    )

    bootstrap_plan = build_backlog_bootstrap_plan(adapter, dry_run=False)
    warnings.extend(bootstrap_plan.warnings)
    errors.extend(_error("BOOTSTRAP_APPLY_FAILED", str(err)) for err in bootstrap_plan.errors)

    before_sync = _file_snapshot(state_root / "state")
    sync_result = BacklogController.sync(adapter, dry_run=True)
    after_sync = _file_snapshot(state_root / "state")
    sync_wrote = before_sync != after_sync
    if sync_wrote:
        errors.append(_error("SYNC_DRY_RUN_WROTE_STATE", "sync-packets dry-run changed registry state"))

    dry_submit = submit_ready_packets_to_prefect(
        project=adapter,
        dry_run=True,
        limit=None,
        execute_agent=False,
        timeout_seconds=timeout_seconds,
        worktree_root=worktree_root,
        submitter=None,
        runner_kind="e2e",
    )
    submit_plan = dry_submit.to_dict()
    submit_plan["packets_to_submit"] = list(dry_submit.packets_planned)
    selected_packet_id = dry_submit.packets_planned[0] if dry_submit.packets_planned == [PACKET_CHILD_RUNNABLE] else None
    if dry_submit.packets_planned != [PACKET_CHILD_RUNNABLE]:
        errors.append(
            _error(
                "PREFECT_SEEDED_UNEXPECTED_SUBMIT_PLAN",
                "Registry-aware submit dry-run must select exactly CHILD-RUNNABLE.",
                packets_planned=list(dry_submit.packets_planned),
            )
        )

    registry_before_submission = _load_registry_map(state_root)
    planned = set(dry_submit.packets_planned)
    case_specs = [
        _case(
            "bounded_parent_seeded_accepted",
            _status(registry_before_submission, PACKET_PARENT_ACCEPTED) == "accepted" and PACKET_PARENT_ACCEPTED not in planned,
            packet_id=PACKET_PARENT_ACCEPTED,
            registry_status=_status(registry_before_submission, PACKET_PARENT_ACCEPTED),
            selected=PACKET_PARENT_ACCEPTED in planned,
        ),
        _case(
            "only_runnable_child_selected",
            selected_packet_id == PACKET_CHILD_RUNNABLE,
            packet_id=PACKET_CHILD_RUNNABLE,
            registry_status=_status(registry_before_submission, PACKET_CHILD_RUNNABLE),
            selected=PACKET_CHILD_RUNNABLE in planned,
        ),
        _case(
            "missing_dependency_unsubmitted",
            _status(registry_before_submission, PACKET_CHILD_MISSING_DEP) == "waiting_for_dependencies"
            and PACKET_CHILD_MISSING_DEP not in planned,
            packet_id=PACKET_CHILD_MISSING_DEP,
            registry_status=_status(registry_before_submission, PACKET_CHILD_MISSING_DEP),
            selected=PACKET_CHILD_MISSING_DEP in planned,
        ),
        _case(
            "blocked_dependency_unsubmitted",
            _status(registry_before_submission, PACKET_CHILD_BLOCKED_DEP) in {"waiting_for_dependencies", "cascading_blocked"}
            and PACKET_CHILD_BLOCKED_DEP not in planned,
            packet_id=PACKET_CHILD_BLOCKED_DEP,
            registry_status=_status(registry_before_submission, PACKET_CHILD_BLOCKED_DEP),
            selected=PACKET_CHILD_BLOCKED_DEP in planned,
        ),
        _case(
            "source_status_only_not_accepted",
            _status(registry_before_submission, PACKET_SOURCE_STATUS_ONLY) != "accepted"
            and PACKET_SOURCE_STATUS_ONLY not in planned,
            packet_id=PACKET_SOURCE_STATUS_ONLY,
            registry_status=_status(registry_before_submission, PACKET_SOURCE_STATUS_ONLY),
            selected=PACKET_SOURCE_STATUS_ONLY in planned,
        ),
        _case(
            "command_status_passed_not_accepted",
            _status(registry_before_submission, PACKET_COMMAND_PASSED) != "accepted"
            and PACKET_COMMAND_PASSED not in planned,
            packet_id=PACKET_COMMAND_PASSED,
            registry_status=_status(registry_before_submission, PACKET_COMMAND_PASSED),
            selected=PACKET_COMMAND_PASSED in planned,
        ),
        _case(
            "sync_dry_run_no_registry_write",
            not sync_wrote,
            packet_id="sync-packets",
            registry_status="unchanged" if not sync_wrote else "changed",
        ),
        _case(
            "submit_dry_run_no_prefect_runs",
            len(dry_submit.packets_submitted) == 0,
            packet_id="submit-packets",
            prefect_runs_created=len(dry_submit.packets_submitted),
        ),
    ]
    for case in case_specs:
        errors.extend(case.get("errors", []))

    deployment_name = None
    work_queue_name = None
    flow_run_id = None
    flow_run_name = None
    flow_run_url = None
    submitted = False
    waited = False
    prefect_state_type = None
    prefect_state_name = None
    domain_status = None
    artifact_ids: list[str] = []
    prefect_runs_created = 0

    if selected_packet_id and not errors:
        if submitter is None:
            from prefect_grace.platform.runtime_adapter import E2EPacketSubmitter
            submitter = E2EPacketSubmitter()
        submission = submit_ready_packets_to_prefect(
            project=adapter,
            dry_run=False,
            limit=1,
            execute_agent=False,
            timeout_seconds=timeout_seconds,
            worktree_root=worktree_root,
            submitter=submitter,
            runner_kind="e2e",
        )
        prefect_runs_created = len(submission.packets_submitted)
        if submission.errors or len(submission.records) != 1:
            errors.extend(submission.errors)
            if len(submission.records) != 1:
                errors.append(_error("PREFECT_SEEDED_SUBMISSION_COUNT_INVALID", f"Expected one submission record; got {len(submission.records)}."))
        else:
            record = submission.records[0]
            deployment_name = record.deployment_name
            work_queue_name = record.work_queue_name
            flow_run_id = record.flow_run_id
            flow_run_name = record.flow_run_name
            flow_run_url = record.url
            submitted = record.status == "submitted"
            if record.packet_id != PACKET_CHILD_RUNNABLE:
                errors.append(_error("PREFECT_SEEDED_WRONG_PACKET_SUBMITTED", f"Expected {PACKET_CHILD_RUNNABLE}; got {record.packet_id}."))
            if record.deployment_name != E2E_PACKET_DEPLOYMENT_NAME:
                errors.append(_error("PREFECT_SEEDED_UNEXPECTED_DEPLOYMENT", f"Expected {E2E_PACKET_DEPLOYMENT_NAME}; got {record.deployment_name}."))
            if not record.flow_run_id:
                errors.append(_error("PREFECT_SEEDED_MISSING_FLOW_RUN_ID", "Prefect submission did not return a flow run id."))
            if not submitted:
                errors.append(_error("PREFECT_SEEDED_NOT_SUBMITTED", record.error or record.status))

            if wait and record.flow_run_id and not errors:
                waited = True
                reader = status_reader or _read_prefect_flow_run_status
                sleeper = sleep_fn or time.sleep
                status, wait_errors = _wait_for_flow_run(
                    flow_run_id=record.flow_run_id,
                    timeout_seconds=timeout_seconds,
                    poll_interval_seconds=poll_interval_seconds,
                    status_reader=reader,
                    sleep_fn=sleeper,
                )
                wait_errors = _seeded_wait_errors(wait_errors)
                errors.extend(wait_errors)
                prefect_state_type = _normalize_state_type(status.get("prefect_state_type"))
                prefect_state_name = status.get("prefect_state_name")
                domain_status = status.get("domain_status") or "unknown"
                artifact_ids = list(status.get("artifact_ids") or [])
            elif not wait:
                waited = False

    touched_paths = [
        state_root / "state" / "packet_registry.yaml",
        packet_root / "packets",
        worktree_root,
    ]
    writes_outside_temp_roots = _paths_outside_roots(touched_paths, [state_root, worktree_root, packet_root])
    if writes_outside_temp_roots:
        errors.append(_error("WRITE_OUTSIDE_TEMP_ROOTS", "Smoke detected writes outside temp roots"))

    success_status = (
        not wait
        or _normalize_state_type(prefect_state_type) in SUCCESS_STATE_TYPES
        or str(domain_status or "") in SUCCESS_DOMAIN_STATUSES
    )
    failure_status = _normalize_state_type(prefect_state_type) in FAILURE_STATE_TYPES
    if failure_status:
        errors.append(_error("PREFECT_SEEDED_DRY_RUN_FAILED", f"Prefect flow run reached {prefect_state_name or prefect_state_type}."))

    ok = (
        not errors
        and selected_packet_id == PACKET_CHILD_RUNNABLE
        and submitted
        and prefect_runs_created == 1
        and deployment_name == E2E_PACKET_DEPLOYMENT_NAME
        and success_status
        and not writes_outside_temp_roots
    )

    return PrefectRealDryRunSeededSmokeResult(
        ok=ok,
        project_key=adapter.project_key,
        mode=SMOKE_MODE,
        state_root=str(state_root),
        worktree_root=str(worktree_root),
        packet_root=str(packet_root),
        selected_packet_id=selected_packet_id,
        bootstrap_apply_count=bootstrap_plan.apply_count,
        sync_plan=_sync_result_to_dict(sync_result),
        submit_plan=submit_plan,
        deployment_name=deployment_name,
        work_queue_name=work_queue_name,
        flow_run_id=flow_run_id,
        flow_run_name=flow_run_name,
        flow_run_url=flow_run_url,
        submitted=submitted,
        waited=waited,
        prefect_state_type=prefect_state_type,
        prefect_state_name=prefect_state_name,
        domain_status=domain_status,
        artifact_ids=artifact_ids,
        prefect_runs_created=prefect_runs_created,
        live_agents_started=0,
        writes_outside_temp_roots=writes_outside_temp_roots,
        warnings=warnings,
        errors=errors,
        cases=case_specs,
    )


#END_BLOCK_SMOKE
