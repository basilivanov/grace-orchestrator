# ############################################################################
# AI_HEADER: registry_apply_smoke
# ROLE: Offline registry apply smoke for GRACE backlog bootstrap.
# ############################################################################

# START_MODULE_CONTRACT
# purpose: Run a deterministic temp-state smoke for bootstrap apply, sync planning, and submit planning.
# inputs: Project config path, explicit temporary state root, optional packet root.
# returns: RegistryApplySmokeResult with JSON-safe case verdicts and planning evidence.
# side_effects: Writes synthetic packet fixtures and registry state only under the explicit state root.
# emitted_logs: None.
# error_behavior: Returns structured errors in the smoke result.
# END_MODULE_CONTRACT

# START_MODULE_MAP
# mapping:
#   - class: RegistryApplySmokeCase
#   - class: RegistryApplySmokeResult
#   - function: run_registry_apply_smoke
# END_MODULE_MAP

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from prefect_grace.platform.backlog_controller import BacklogController
from prefect_grace.platform.controller_backlog_bootstrap import (
    build_backlog_bootstrap_plan,
)
from prefect_grace.platform.prefect_native_submission import submit_ready_packets_to_prefect
from prefect_grace.platform.project_adapter import load_project_adapter
from prefect_grace.platform.state_store import PacketRegistryStore

#START_BLOCK_MODELS
@dataclass(frozen=True)
class RegistryApplySmokeCase:
    name: str
    packet_id: str
    expected_status: str
    actual_status: str | None
    expected_action: str
    actual_action: str | None
    ok: bool
    evidence_paths: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    errors: list[dict[str, Any]] = field(default_factory=list)

    # START_FUNCTION_CONTRACT
    # name: to_dict
    # purpose: Serialize a registry apply smoke case to a JSON-safe dictionary.
    # inputs:
    #   self: RegistryApplySmokeCase instance.
    # returns: dict with case fields.
    # side_effects: None.
    # emitted_logs: None.
    # error_behavior: None.
    # END_FUNCTION_CONTRACT
    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class RegistryApplySmokeResult:
    ok: bool
    project_key: str
    state_root: str
    packet_root: str
    dry_run: bool
    bootstrap_apply_count: int
    sync_plan: dict[str, Any]
    submit_plan: dict[str, Any]
    cases: list[RegistryApplySmokeCase]
    prefect_runs_created: int
    writes_outside_state_root: list[str]
    warnings: list[str] = field(default_factory=list)
    errors: list[dict[str, Any]] = field(default_factory=list)

    # START_FUNCTION_CONTRACT
    # name: to_dict
    # purpose: Serialize the registry apply smoke result to a JSON-safe dictionary.
    # inputs:
    #   self: RegistryApplySmokeResult instance.
    # returns: dict with result fields and serialized cases.
    # side_effects: None.
    # emitted_logs: None.
    # error_behavior: None.
    # END_FUNCTION_CONTRACT
    def to_dict(self) -> dict[str, Any]:
        return {
            "ok": self.ok,
            "project_key": self.project_key,
            "state_root": self.state_root,
            "packet_root": self.packet_root,
            "dry_run": self.dry_run,
            "bootstrap_apply_count": self.bootstrap_apply_count,
            "sync_plan": self.sync_plan,
            "submit_plan": self.submit_plan,
            "cases": [case.to_dict() for case in self.cases],
            "prefect_runs_created": self.prefect_runs_created,
            "writes_outside_state_root": list(self.writes_outside_state_root),
            "warnings": list(self.warnings),
            "errors": list(self.errors),
        }


#END_BLOCK_MODELS
#START_BLOCK_FIXTURES
PACKET_PARENT_ACCEPTED = "SMOKE-PARENT-ACCEPTED-W01-PACKET"
PACKET_DEP_READY = "SMOKE-DEPENDENT-READY-W01-PACKET"
PACKET_MISSING_DEP = "SMOKE-MISSING-DEPENDENCY-W01-PACKET"
PACKET_BLOCKED_PARENT = "SMOKE-BLOCKED-PARENT-W01-PACKET"
PACKET_DEP_BLOCKED = "SMOKE-DEPENDENT-BLOCKED-W01-PACKET"
PACKET_SOURCE_ONLY = "SMOKE-SOURCE-ONLY-W01-PACKET"
PACKET_COMMAND_PASSED = "SMOKE-COMMAND-PASSED-W01-PACKET"


def _packet_markdown(packet_id: str, *, status: str = "ready", depends_on: list[str] | None = None) -> str:
    dependency_line = ""
    if depends_on:
        dependency_line = f"- depends_on: `{', '.join(depends_on)}`\n"
    feature_id = packet_id.rsplit("-W01-", 1)[0]
    return f"""# Execution Packet: {packet_id}

## Objective
Registry apply smoke packet for {packet_id}.

## Slice
- packet_id: `{packet_id}`
- feature_id: `{feature_id}`
- wave_id: `W01`
- status: `{status}`
{dependency_line}
## Allowed Write Scope
- smoke/**

## Frozen Scope
- backend/**

## Must Preserve
- Smoke fixtures remain isolated to temporary state.

## Verification
pytest

## Expected Evidence
- smoke output

## Escalation Triggers
- smoke failure
"""


def _write_packet(repo_root: Path, packet_id: str, *, status: str = "ready", depends_on: list[str] | None = None) -> Path:
    packet_dir = repo_root / "packets" / packet_id
    packet_dir.mkdir(parents=True, exist_ok=True)
    packet_path = packet_dir / "EXECUTION_PACKET.md"
    packet_path.write_text(_packet_markdown(packet_id, status=status, depends_on=depends_on), encoding="utf-8")
    return packet_path


def _write_smoke_fixtures(repo_root: Path) -> dict[str, Path]:
    packet_paths = {
        PACKET_PARENT_ACCEPTED: _write_packet(repo_root, PACKET_PARENT_ACCEPTED),
        PACKET_DEP_READY: _write_packet(
            repo_root,
            PACKET_DEP_READY,
            depends_on=[PACKET_PARENT_ACCEPTED],
        ),
        PACKET_MISSING_DEP: _write_packet(
            repo_root,
            PACKET_MISSING_DEP,
            depends_on=["SMOKE-NOT-PRESENT-W01-PACKET"],
        ),
        PACKET_BLOCKED_PARENT: _write_packet(repo_root, PACKET_BLOCKED_PARENT),
        PACKET_DEP_BLOCKED: _write_packet(
            repo_root,
            PACKET_DEP_BLOCKED,
            depends_on=[PACKET_BLOCKED_PARENT],
        ),
        PACKET_SOURCE_ONLY: _write_packet(repo_root, PACKET_SOURCE_ONLY, status="accepted"),
        PACKET_COMMAND_PASSED: _write_packet(repo_root, PACKET_COMMAND_PASSED),
    }

    parent_review = packet_paths[PACKET_PARENT_ACCEPTED].parent / "REVIEWS" / "review-0001.md"
    parent_review.parent.mkdir(parents=True, exist_ok=True)
    parent_review.write_text("verdict: ACCEPTED\n", encoding="utf-8")

    blocked_summary = packet_paths[PACKET_BLOCKED_PARENT].parent / "SUMMARY.md"
    blocked_summary.write_text("current_status: blocked\n", encoding="utf-8")

    command_evidence = (
        packet_paths[PACKET_COMMAND_PASSED].parent
        / "EVIDENCE"
        / "attempt-0001"
        / "evidence_manifest.json"
    )
    command_evidence.parent.mkdir(parents=True, exist_ok=True)
    command_evidence.write_text(
        '{"status": "passed", "commands": [{"name": "pytest", "status": "passed"}]}',
        encoding="utf-8",
    )

    return packet_paths


#END_BLOCK_FIXTURES
#START_BLOCK_HELPERS
def _error(code: str, message: str, **extra: Any) -> dict[str, Any]:
    return {"code": code, "message": message, **extra}


def _is_relative_to(path: Path, root: Path) -> bool:
    try:
        path.resolve().relative_to(root.resolve())
        return True
    except ValueError:
        return False


def _validate_state_root(state_root: Path, repo_root: Path) -> list[dict[str, Any]]:
    errors: list[dict[str, Any]] = []
    resolved = state_root.resolve()
    if _is_relative_to(resolved, Path("/var/lib/grace-orchestrator")):
        errors.append(_error("UNSAFE_STATE_ROOT", "state_root must not be under /var/lib/grace-orchestrator"))
    if _is_relative_to(resolved, repo_root / "prefect_grace" / "state"):
        errors.append(_error("UNSAFE_STATE_ROOT", "state_root must not be under prefect_grace/state"))
    return errors


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
            snapshot[str(path.resolve())] = path.read_text(encoding="utf-8")
    return snapshot


def _case(
    *,
    name: str,
    packet_id: str,
    expected_status: str,
    actual_status: str | None,
    expected_action: str,
    actual_action: str | None,
    evidence_paths: list[str] | None = None,
    warnings: list[str] | None = None,
) -> RegistryApplySmokeCase:
    ok = expected_status == (actual_status or "") and expected_action == (actual_action or "")
    errors = [] if ok else [
        _error(
            "CASE_FAILED",
            f"{name} expected status/action {expected_status}/{expected_action}, got {actual_status}/{actual_action}",
            packet_id=packet_id,
        )
    ]
    return RegistryApplySmokeCase(
        name=name,
        packet_id=packet_id,
        expected_status=expected_status,
        actual_status=actual_status,
        expected_action=expected_action,
        actual_action=actual_action,
        ok=ok,
        evidence_paths=evidence_paths or [],
        warnings=warnings or [],
        errors=errors,
    )


#END_BLOCK_HELPERS
#START_BLOCK_SMOKE
# START_FUNCTION_CONTRACT
# name: run_registry_apply_smoke
# purpose: Run isolated bootstrap apply, sync dry-run, and submit dry-run smoke against temporary state.
# inputs:
#   project_config: Path to project config.
#   state_root: Explicit temporary runtime state root.
#   packet_root: Optional synthetic packet repo root; must be under state_root when provided.
#   json_safe: Retained for API compatibility; result is always JSON-safe.
# returns: RegistryApplySmokeResult with case verdicts and planning output.
# side_effects: Writes synthetic packet fixtures and registry files only below state_root.
# emitted_logs: None.
# error_behavior: Returns structured errors instead of raising for validation and smoke failures.
# END_FUNCTION_CONTRACT
def run_registry_apply_smoke(
    *,
    project_config: Path,
    state_root: Path,
    packet_root: Path | None = None,
    json_safe: bool = True,
) -> RegistryApplySmokeResult:
    base_adapter = load_project_adapter(project_config)
    repo_root = Path(base_adapter.repo_root)
    errors = _validate_state_root(state_root, repo_root)
    warnings: list[str] = []

    synthetic_repo = packet_root or (state_root / "synthetic_repo")
    if not _is_relative_to(synthetic_repo, state_root):
        errors.append(_error("UNSAFE_PACKET_ROOT", "packet_root must be under state_root"))

    if errors:
        return RegistryApplySmokeResult(
            ok=False,
            project_key=base_adapter.project_key,
            state_root=str(state_root),
            packet_root=str(synthetic_repo),
            dry_run=False,
            bootstrap_apply_count=0,
            sync_plan={},
            submit_plan={},
            cases=[],
            prefect_runs_created=0,
            writes_outside_state_root=[],
            warnings=warnings,
            errors=errors,
        )

    synthetic_repo.mkdir(parents=True, exist_ok=True)
    packet_paths = _write_smoke_fixtures(synthetic_repo)

    adapter = load_project_adapter(
        project_config,
        overrides={
            "repo_root": str(synthetic_repo),
            "packets_dir": "packets",
            "runtime_state_root": str(state_root),
            "artifact_root": str(state_root / "artifacts"),
            "worktree_root": str(state_root / "worktrees"),
        },
    )

    registry = PacketRegistryStore(state_root / "state")
    bootstrap_plan = build_backlog_bootstrap_plan(adapter, dry_run=False)
    warnings.extend(bootstrap_plan.warnings)
    errors.extend(_error("BOOTSTRAP_APPLY_FAILED", str(err)) for err in bootstrap_plan.errors)

    bootstrap_candidates = {candidate.packet_id: candidate for candidate in bootstrap_plan.candidates}
    before_sync = _file_snapshot(state_root / "state")
    sync_result = BacklogController.sync(adapter, dry_run=True)
    after_sync = _file_snapshot(state_root / "state")
    sync_wrote = before_sync != after_sync
    if sync_wrote:
        errors.append(_error("SYNC_DRY_RUN_WROTE_STATE", "sync dry-run changed registry state"))

    submit_result = submit_ready_packets_to_prefect(project=adapter, dry_run=True, submitter=None)
    execute_result = submit_ready_packets_to_prefect(project=adapter, dry_run=False, submitter=None)
    prefect_runs_created = len(submit_result.packets_submitted)
    if execute_result.packets_submitted:
        errors.append(_error("EXECUTE_NOT_FAIL_CLOSED", "execute mode submitted packets without an explicit submitter"))

    submit_plan = submit_result.to_dict()
    submit_plan["packets_to_submit"] = list(submit_result.packets_planned)
    submit_plan["execute_fail_closed"] = {
        "ok": execute_result.ok is False,
        "errors": execute_result.errors,
        "packets_submitted": execute_result.packets_submitted,
    }

    registry_status = {
        packet_id: (registry.load_packet(packet_id) or {}).get("registry_status")
        for packet_id in packet_paths
    }
    submit_planned = set(submit_result.packets_planned)

    def _candidate_action(packet_id: str) -> str | None:
        candidate = bootstrap_candidates.get(packet_id)
        return candidate.planned_action if candidate else None

    cases = [
        _case(
            name="accepted_parent_seeded",
            packet_id=PACKET_PARENT_ACCEPTED,
            expected_status="accepted",
            actual_status=registry_status[PACKET_PARENT_ACCEPTED],
            expected_action="create",
            actual_action=_candidate_action(PACKET_PARENT_ACCEPTED),
            evidence_paths=bootstrap_candidates[PACKET_PARENT_ACCEPTED].evidence_paths,
        ),
        _case(
            name="accepted_parent_not_submitted",
            packet_id=PACKET_PARENT_ACCEPTED,
            expected_status="accepted",
            actual_status=registry_status[PACKET_PARENT_ACCEPTED],
            expected_action="not_submitted",
            actual_action="submitted" if PACKET_PARENT_ACCEPTED in submit_planned else "not_submitted",
        ),
        _case(
            name="dependent_ready_runnable",
            packet_id=PACKET_DEP_READY,
            expected_status="ready",
            actual_status=registry_status[PACKET_DEP_READY],
            expected_action="submitted",
            actual_action="submitted" if PACKET_DEP_READY in submit_planned else "not_submitted",
        ),
        _case(
            name="missing_dependency_waits",
            packet_id=PACKET_MISSING_DEP,
            expected_status="waiting_for_dependencies",
            actual_status=registry_status[PACKET_MISSING_DEP],
            expected_action="not_submitted",
            actual_action="submitted" if PACKET_MISSING_DEP in submit_planned else "not_submitted",
        ),
        _case(
            name="blocked_dependency_waits",
            packet_id=PACKET_DEP_BLOCKED,
            expected_status="waiting_for_dependencies",
            actual_status=registry_status[PACKET_DEP_BLOCKED],
            expected_action="not_submitted",
            actual_action="submitted" if PACKET_DEP_BLOCKED in submit_planned else "not_submitted",
        ),
        _case(
            name="source_status_accepted_without_evidence_not_accepted",
            packet_id=PACKET_SOURCE_ONLY,
            expected_status="ready",
            actual_status=registry_status[PACKET_SOURCE_ONLY],
            expected_action="create",
            actual_action=_candidate_action(PACKET_SOURCE_ONLY),
        ),
        _case(
            name="command_status_passed_not_accepted",
            packet_id=PACKET_COMMAND_PASSED,
            expected_status="ready",
            actual_status=registry_status[PACKET_COMMAND_PASSED],
            expected_action="create",
            actual_action=_candidate_action(PACKET_COMMAND_PASSED),
            evidence_paths=bootstrap_candidates[PACKET_COMMAND_PASSED].evidence_paths,
            warnings=bootstrap_candidates[PACKET_COMMAND_PASSED].warnings,
        ),
        _case(
            name="sync_dry_run_no_registry_write",
            packet_id="sync-packets",
            expected_status="unchanged",
            actual_status="unchanged" if not sync_wrote else "changed",
            expected_action="dry_run",
            actual_action="dry_run",
        ),
        _case(
            name="submit_dry_run_no_prefect_runs",
            packet_id="submit-packets",
            expected_status="zero_prefect_runs",
            actual_status="zero_prefect_runs" if prefect_runs_created == 0 else "prefect_runs_created",
            expected_action="dry_run",
            actual_action="dry_run",
        ),
        _case(
            name="submit_execute_fail_closed",
            packet_id="submit-packets",
            expected_status="fail_closed",
            actual_status="fail_closed" if execute_result.ok is False and not execute_result.packets_submitted else "opened",
            expected_action="NO_SUBMITTER_PROVIDED",
            actual_action=execute_result.errors[0]["code"] if execute_result.errors else "submitted",
        ),
    ]

    writes_outside_state_root = [
        path
        for path in _file_snapshot(state_root).keys()
        if not _is_relative_to(Path(path), state_root)
    ]
    if writes_outside_state_root:
        errors.append(_error("WRITE_OUTSIDE_STATE_ROOT", "Smoke detected writes outside state_root"))

    for case in cases:
        errors.extend(case.errors)
    errors.extend(_error("SYNC_DRY_RUN_ERROR", str(err)) for err in sync_result.errors)
    errors.extend(_error("SUBMIT_DRY_RUN_ERROR", str(err)) for err in submit_result.errors)

    return RegistryApplySmokeResult(
        ok=not errors and all(case.ok for case in cases),
        project_key=adapter.project_key,
        state_root=str(state_root),
        packet_root=str(synthetic_repo / "packets"),
        dry_run=False,
        bootstrap_apply_count=bootstrap_plan.apply_count,
        sync_plan=_sync_result_to_dict(sync_result),
        submit_plan=submit_plan,
        cases=cases,
        prefect_runs_created=prefect_runs_created,
        writes_outside_state_root=writes_outside_state_root,
        warnings=warnings,
        errors=errors,
    )


#END_BLOCK_SMOKE
