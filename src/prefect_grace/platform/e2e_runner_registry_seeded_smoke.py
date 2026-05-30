# ############################################################################
# AI_HEADER: e2e_runner_registry_seeded_smoke
# ROLE: Offline registry-seeded smoke for the GRACE E2E packet runner.
# ############################################################################

# START_MODULE_CONTRACT
# purpose: Run a deterministic registry-seeded dry-run smoke for the E2E packet runner.
# inputs: Project config path plus explicit temporary state, worktree, and packet roots.
# returns: E2ERegistrySeededSmokeResult with JSON-safe planning, runner, and registry evidence.
# side_effects: Writes synthetic packets, git metadata, worktrees, and registry state only below temp roots.
# emitted_logs: None.
# error_behavior: Returns structured errors in the smoke result.
# END_MODULE_CONTRACT

# START_MODULE_MAP
# mapping:
#   - class: E2ERegistrySeededSmokeCase
#   - class: E2ERegistrySeededSmokeResult
#   - function: run_e2e_runner_registry_seeded_smoke
# END_MODULE_MAP

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from pathlib import Path
import shutil
import subprocess
import tempfile
from typing import Any

import yaml

from prefect_grace.platform.backlog_controller import BacklogController
from prefect_grace.platform.controller_backlog_bootstrap import build_backlog_bootstrap_plan
from prefect_grace.platform.e2e_packet_runner import run_e2e_packet
from prefect_grace.platform.prefect_native_submission import submit_ready_packets_to_prefect
from prefect_grace.platform.project_adapter import load_project_adapter
from prefect_grace.platform.state_store import PacketRegistryStore

#START_BLOCK_MODELS
@dataclass(frozen=True)
class E2ERegistrySeededSmokeCase:
    name: str
    packet_id: str
    expected_status: str
    actual_status: str | None
    selected_for_e2e: bool
    ok: bool
    warnings: list[str] = field(default_factory=list)
    errors: list[dict[str, Any]] = field(default_factory=list)

    # START_FUNCTION_CONTRACT
    # name: to_dict
    # purpose: Serialize an E2E registry-seeded smoke case to a JSON-safe dictionary.
    # inputs:
    #   self: E2ERegistrySeededSmokeCase instance.
    # returns: dict with case fields.
    # side_effects: None.
    # emitted_logs: None.
    # error_behavior: None.
    # END_FUNCTION_CONTRACT
    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class E2ERegistrySeededSmokeResult:
    ok: bool
    project_key: str
    state_root: str
    worktree_root: str
    packet_root: str
    selected_packet_id: str | None
    bootstrap_apply_count: int
    sync_plan: dict[str, Any]
    submit_plan: dict[str, Any]
    e2e_result: dict[str, Any] | None
    registry_before: dict[str, Any]
    registry_after: dict[str, Any]
    cases: list[E2ERegistrySeededSmokeCase]
    prefect_runs_created: int
    live_agents_started: int
    writes_outside_temp_roots: list[str]
    warnings: list[str] = field(default_factory=list)
    errors: list[dict[str, Any]] = field(default_factory=list)

    # START_FUNCTION_CONTRACT
    # name: to_dict
    # purpose: Serialize the E2E registry-seeded smoke result to a JSON-safe dictionary.
    # inputs:
    #   self: E2ERegistrySeededSmokeResult instance.
    # returns: dict with result fields and serialized case verdicts.
    # side_effects: None.
    # emitted_logs: None.
    # error_behavior: None.
    # END_FUNCTION_CONTRACT
    def to_dict(self) -> dict[str, Any]:
        return {
            "ok": self.ok,
            "project_key": self.project_key,
            "state_root": self.state_root,
            "worktree_root": self.worktree_root,
            "packet_root": self.packet_root,
            "selected_packet_id": self.selected_packet_id,
            "bootstrap_apply_count": self.bootstrap_apply_count,
            "sync_plan": dict(self.sync_plan),
            "submit_plan": dict(self.submit_plan),
            "e2e_result": dict(self.e2e_result) if self.e2e_result is not None else None,
            "registry_before": dict(self.registry_before),
            "registry_after": dict(self.registry_after),
            "cases": [case.to_dict() for case in self.cases],
            "prefect_runs_created": self.prefect_runs_created,
            "live_agents_started": self.live_agents_started,
            "writes_outside_temp_roots": list(self.writes_outside_temp_roots),
            "warnings": list(self.warnings),
            "errors": list(self.errors),
        }


#END_BLOCK_MODELS
#START_BLOCK_FIXTURES
PACKET_PARENT_ACCEPTED = "SMOKE-PARENT-ACCEPTED-W01-PACKET"
PACKET_CHILD_RUNNABLE = "SMOKE-CHILD-RUNNABLE-W01-PACKET"
PACKET_CHILD_MISSING_DEP = "SMOKE-CHILD-MISSING-DEP-W01-PACKET"
PACKET_PARENT_BLOCKED = "SMOKE-PARENT-BLOCKED-W01-PACKET"
PACKET_CHILD_BLOCKED_DEP = "SMOKE-CHILD-BLOCKED-DEP-W01-PACKET"
PACKET_SOURCE_STATUS_ONLY = "SMOKE-PARENT-SOURCE-STATUS-ONLY-W01-PACKET"
MISSING_DEPENDENCY_ID = "SMOKE-NOT-PRESENT-W01-PACKET"


def _packet_markdown(
    packet_id: str,
    *,
    status: str = "ready",
    depends_on: list[str] | None = None,
) -> str:
    dependency_line = ""
    if depends_on:
        dependency_line = f"- depends_on: `{', '.join(depends_on)}`\n"
    feature_id = packet_id.rsplit("-W01-", 1)[0]
    return f"""# Execution Packet: {packet_id}

## Objective
Synthetic registry-seeded E2E smoke packet for {packet_id}.

## Slice
- packet_id: `{packet_id}`
- feature_id: `{feature_id}`
- wave_id: `W01`
- status: `{status}`
{dependency_line}
## Allowed Write Scope
- /tmp/**

## Frozen Scope
- backend/**

## Must Preserve
- Synthetic smoke fixtures remain isolated to explicit temporary roots.

## Verification
Run deterministic dry-run E2E smoke.

## Expected Evidence
- Smoke JSON output.

## Escalation Triggers
- Live agents or live Prefect runs are required.
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
    packet_path.write_text(
        _packet_markdown(packet_id, status=status, depends_on=depends_on),
        encoding="utf-8",
    )
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
    }

    parent_review = packet_paths[PACKET_PARENT_ACCEPTED].parent / "REVIEWS" / "review-0001.md"
    parent_review.parent.mkdir(parents=True, exist_ok=True)
    parent_review.write_text("verdict: ACCEPTED\n", encoding="utf-8")

    blocked_summary = packet_paths[PACKET_PARENT_BLOCKED].parent / "SUMMARY.md"
    blocked_summary.write_text("current_status: blocked\n", encoding="utf-8")

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


def _unsafe_runtime_path(path: Path, repo_root: Path) -> bool:
    return (
        _is_relative_to(path, Path("/var/lib/grace-orchestrator"))
        or _is_relative_to(path, repo_root / "prefect_grace" / "state")
    )


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


def _validate_roots(
    *,
    state_root: Path,
    worktree_root: Path,
    packet_root: Path,
    repo_root: Path,
) -> list[dict[str, Any]]:
    errors: list[dict[str, Any]] = []
    root_specs = [
        ("state_root", state_root, "UNSAFE_STATE_ROOT"),
        ("worktree_root", worktree_root, "UNSAFE_WORKTREE_ROOT"),
        ("packet_root", packet_root, "UNSAFE_PACKET_ROOT"),
    ]
    for label, root, code in root_specs:
        if _unsafe_runtime_path(root, repo_root) or _is_relative_to(root, repo_root):
            errors.append(_error(code, f"{label} must not be real GRACE state or inside the repository"))
            continue
        if not _is_dedicated_temp_root(root):
            errors.append(_error(code, f"{label} must be a dedicated child directory under the system temp root"))

    root_pairs = [
        ("state_root", state_root, "worktree_root", worktree_root),
        ("state_root", state_root, "packet_root", packet_root),
        ("worktree_root", worktree_root, "packet_root", packet_root),
    ]
    for left_label, left, right_label, right in root_pairs:
        if _roots_overlap(left, right):
            errors.append(
                _error(
                    "OVERLAPPING_TEMP_ROOTS",
                    f"{left_label} and {right_label} must be separate temp directories",
                )
            )
    return errors


def _reset_temp_runtime_roots(state_root: Path, worktree_root: Path) -> None:
    shutil.rmtree(state_root, ignore_errors=True)
    shutil.rmtree(worktree_root, ignore_errors=True)
    state_root.mkdir(parents=True, exist_ok=True)
    worktree_root.mkdir(parents=True, exist_ok=True)


def _run_git(args: list[str], cwd: Path) -> None:
    subprocess.run(["git", *args], cwd=cwd, capture_output=True, text=True, check=True)


def _has_head(repo_root: Path) -> bool:
    result = subprocess.run(
        ["git", "rev-parse", "--verify", "HEAD"],
        cwd=repo_root,
        capture_output=True,
        text=True,
    )
    return result.returncode == 0


def _ensure_synthetic_git_repo(packet_root: Path) -> None:
    packet_root.mkdir(parents=True, exist_ok=True)
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


def _load_registry_map(state_root: Path) -> dict[str, Any]:
    registry_path = state_root / "state" / "packet_registry.yaml"
    if not registry_path.exists():
        return {}
    data = yaml.safe_load(registry_path.read_text(encoding="utf-8")) or {}
    if not isinstance(data, dict):
        return {}
    return {packet_id: data[packet_id] for packet_id in sorted(data)}


def _status(registry_map: dict[str, Any], packet_id: str) -> str | None:
    record = registry_map.get(packet_id)
    if not isinstance(record, dict):
        return None
    return record.get("registry_status")


def _case(
    *,
    name: str,
    packet_id: str,
    expected_status: str,
    actual_status: str | None,
    selected_for_e2e: bool,
    ok: bool | None = None,
    warnings: list[str] | None = None,
) -> E2ERegistrySeededSmokeCase:
    case_ok = (expected_status == (actual_status or "")) if ok is None else ok
    errors = [] if case_ok else [
        _error(
            "CASE_FAILED",
            f"{name} expected {expected_status}, got {actual_status}",
            packet_id=packet_id,
        )
    ]
    return E2ERegistrySeededSmokeCase(
        name=name,
        packet_id=packet_id,
        expected_status=expected_status,
        actual_status=actual_status,
        selected_for_e2e=selected_for_e2e,
        ok=case_ok,
        warnings=warnings or [],
        errors=errors,
    )


def _paths_outside_roots(paths: list[Path], roots: list[Path]) -> list[str]:
    outside = []
    for path in paths:
        if not any(_is_relative_to(path, root) for root in roots):
            outside.append(str(path))
    return outside


#END_BLOCK_HELPERS
#START_BLOCK_SMOKE
# START_FUNCTION_CONTRACT
# name: run_e2e_runner_registry_seeded_smoke
# purpose: Run an isolated registry-seeded dry-run smoke through the E2E packet runner.
# inputs:
#   project_config: Path to project config.
#   state_root: Explicit temporary state root.
#   worktree_root: Explicit temporary worktree root.
#   packet_root: Explicit synthetic packet root.
#   json_safe: Retained for API compatibility; result is always JSON-safe.
# returns: E2ERegistrySeededSmokeResult with planning, runner, registry, and case evidence.
# side_effects: Writes synthetic packets, temp registry state, and temp worktrees only under explicit roots.
# emitted_logs: None.
# error_behavior: Returns structured errors instead of raising for validation and smoke failures.
# END_FUNCTION_CONTRACT
def run_e2e_runner_registry_seeded_smoke(
    *,
    project_config: Path,
    state_root: Path,
    worktree_root: Path,
    packet_root: Path,
    json_safe: bool = True,
) -> E2ERegistrySeededSmokeResult:
    base_adapter = load_project_adapter(project_config)
    repo_root = Path(base_adapter.repo_root)
    errors = _validate_roots(
        state_root=state_root,
        worktree_root=worktree_root,
        packet_root=packet_root,
        repo_root=repo_root,
    )
    warnings: list[str] = []

    if errors:
        return E2ERegistrySeededSmokeResult(
            ok=False,
            project_key=base_adapter.project_key,
            state_root=str(state_root),
            worktree_root=str(worktree_root),
            packet_root=str(packet_root),
            selected_packet_id=None,
            bootstrap_apply_count=0,
            sync_plan={},
            submit_plan={},
            e2e_result=None,
            registry_before={},
            registry_after={},
            cases=[],
            prefect_runs_created=0,
            live_agents_started=0,
            writes_outside_temp_roots=[],
            warnings=warnings,
            errors=errors,
        )

    _reset_temp_runtime_roots(state_root, worktree_root)
    _ensure_synthetic_git_repo(packet_root)
    packet_paths = _write_smoke_fixtures(packet_root)

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

    registry = PacketRegistryStore(state_root / "state")
    bootstrap_plan = build_backlog_bootstrap_plan(adapter, dry_run=False)
    warnings.extend(bootstrap_plan.warnings)
    errors.extend(_error("BOOTSTRAP_APPLY_FAILED", str(err)) for err in bootstrap_plan.errors)

    sync_result = BacklogController.sync(adapter, dry_run=True)
    submit_result = submit_ready_packets_to_prefect(project=adapter, dry_run=True, submitter=None)
    prefect_runs_created = len(submit_result.packets_submitted)

    selected_packet_id = submit_result.packets_planned[0] if len(submit_result.packets_planned) == 1 else None
    if submit_result.packets_planned != [PACKET_CHILD_RUNNABLE]:
        errors.append(
            _error(
                "UNEXPECTED_SUBMIT_PLAN",
                "Submit dry-run must select exactly the runnable child packet",
                packets_planned=list(submit_result.packets_planned),
            )
        )

    registry_before = _load_registry_map(state_root)
    e2e_result: dict[str, Any] | None = None
    e2e_invocations = 0

    if selected_packet_id:
        e2e_invocations = 1
        e2e_run = run_e2e_packet(
            project_root=packet_root,
            packet_path=packet_paths[selected_packet_id],
            state_root=state_root,
            worktree_root=worktree_root,
            project_key=adapter.project_key,
            attempt=1,
            base_ref="HEAD",
            dry_run=True,
            execute_agent=False,
            fake_verifier_output=None,
            fake_reviewer_output=None,
            timeout_seconds=60,
            keep_worktree=True,
        )
        e2e_result = e2e_run.to_dict()
        if e2e_run.ok and e2e_run.domain_status == "accepted":
            current = registry.load_packet(selected_packet_id) or {"packet_id": selected_packet_id}
            registry.upsert_packet({
                **current,
                "registry_status": e2e_run.registry_status,
                "registry_reason": e2e_run.registry_reason,
                "registry_transition": e2e_run.registry_transition,
                "domain_status": e2e_run.domain_status,
                "selected_for_e2e": True,
                "e2e_attempt": e2e_run.attempt,
            })
        else:
            errors.append(
                _error(
                    "E2E_RUNNER_NOT_ACCEPTED",
                    "Dry-run E2E runner did not return accepted",
                    packet_id=selected_packet_id,
                    domain_status=e2e_run.domain_status,
                )
            )

    registry_after = _load_registry_map(state_root)
    submit_plan = submit_result.to_dict()
    submit_plan["packets_to_submit"] = list(submit_result.packets_planned)

    case_inputs = {
        PACKET_PARENT_ACCEPTED: _status(registry_before, PACKET_PARENT_ACCEPTED),
        PACKET_CHILD_RUNNABLE: _status(registry_before, PACKET_CHILD_RUNNABLE),
        PACKET_CHILD_MISSING_DEP: _status(registry_before, PACKET_CHILD_MISSING_DEP),
        PACKET_CHILD_BLOCKED_DEP: _status(registry_before, PACKET_CHILD_BLOCKED_DEP),
        PACKET_SOURCE_STATUS_ONLY: _status(registry_before, PACKET_SOURCE_STATUS_ONLY),
    }
    planned = set(submit_result.packets_planned)
    cases = [
        _case(
            name="accepted_parent_seeded",
            packet_id=PACKET_PARENT_ACCEPTED,
            expected_status="accepted",
            actual_status=case_inputs[PACKET_PARENT_ACCEPTED],
            selected_for_e2e=PACKET_PARENT_ACCEPTED in planned,
            ok=case_inputs[PACKET_PARENT_ACCEPTED] == "accepted" and PACKET_PARENT_ACCEPTED not in planned,
        ),
        _case(
            name="child_runnable_selected",
            packet_id=PACKET_CHILD_RUNNABLE,
            expected_status="ready",
            actual_status=case_inputs[PACKET_CHILD_RUNNABLE],
            selected_for_e2e=PACKET_CHILD_RUNNABLE in planned,
            ok=case_inputs[PACKET_CHILD_RUNNABLE] == "ready" and PACKET_CHILD_RUNNABLE in planned,
        ),
        _case(
            name="missing_dependency_waits_unselected",
            packet_id=PACKET_CHILD_MISSING_DEP,
            expected_status="waiting_for_dependencies",
            actual_status=case_inputs[PACKET_CHILD_MISSING_DEP],
            selected_for_e2e=PACKET_CHILD_MISSING_DEP in planned,
            ok=case_inputs[PACKET_CHILD_MISSING_DEP] == "waiting_for_dependencies"
            and PACKET_CHILD_MISSING_DEP not in planned,
        ),
        _case(
            name="blocked_dependency_waits_unselected",
            packet_id=PACKET_CHILD_BLOCKED_DEP,
            expected_status="waiting_for_dependencies",
            actual_status=case_inputs[PACKET_CHILD_BLOCKED_DEP],
            selected_for_e2e=PACKET_CHILD_BLOCKED_DEP in planned,
            ok=case_inputs[PACKET_CHILD_BLOCKED_DEP] in {"waiting_for_dependencies", "cascading_blocked"}
            and PACKET_CHILD_BLOCKED_DEP not in planned,
        ),
        _case(
            name="source_status_only_not_accepted",
            packet_id=PACKET_SOURCE_STATUS_ONLY,
            expected_status="waiting_for_dependencies",
            actual_status=case_inputs[PACKET_SOURCE_STATUS_ONLY],
            selected_for_e2e=PACKET_SOURCE_STATUS_ONLY in planned,
            ok=case_inputs[PACKET_SOURCE_STATUS_ONLY] != "accepted" and PACKET_SOURCE_STATUS_ONLY not in planned,
        ),
        _case(
            name="exactly_one_e2e_invocation",
            packet_id="run-e2e-packet",
            expected_status="1",
            actual_status=str(e2e_invocations),
            selected_for_e2e=e2e_invocations == 1,
        ),
        _case(
            name="e2e_runner_accepts_selected_child",
            packet_id=selected_packet_id or "",
            expected_status="accepted",
            actual_status=e2e_result.get("domain_status") if e2e_result else None,
            selected_for_e2e=selected_packet_id == PACKET_CHILD_RUNNABLE,
            ok=bool(
                e2e_result
                and e2e_result.get("domain_status") == "accepted"
                and e2e_result.get("registry_status") == "accepted"
                and e2e_result.get("registry_reason") == "execution_accepted"
            ),
        ),
        _case(
            name="selected_child_registry_transition_written",
            packet_id=PACKET_CHILD_RUNNABLE,
            expected_status="accepted",
            actual_status=_status(registry_after, PACKET_CHILD_RUNNABLE),
            selected_for_e2e=selected_packet_id == PACKET_CHILD_RUNNABLE,
            ok=_status(registry_after, PACKET_CHILD_RUNNABLE) == "accepted"
            and _status(registry_after, PACKET_PARENT_ACCEPTED) == "accepted"
            and _status(registry_after, PACKET_CHILD_MISSING_DEP) == "waiting_for_dependencies"
            and _status(registry_after, PACKET_SOURCE_STATUS_ONLY) != "accepted",
        ),
        _case(
            name="no_live_prefect_or_agents",
            packet_id="runtime",
            expected_status="offline",
            actual_status="offline" if prefect_runs_created == 0 else "prefect_runs_created",
            selected_for_e2e=False,
            ok=prefect_runs_created == 0,
        ),
    ]

    for case in cases:
        errors.extend(case.errors)
    errors.extend(_error("SYNC_DRY_RUN_ERROR", str(err)) for err in sync_result.errors)
    errors.extend(_error("SUBMIT_DRY_RUN_ERROR", str(err)) for err in submit_result.errors)

    touched_roots = [state_root, worktree_root, packet_root]
    touched_paths = [
        state_root / "state" / "packet_registry.yaml",
        packet_root / "packets",
    ]
    if e2e_result:
        worktree_path = e2e_result.get("worktree_path")
        if worktree_path:
            touched_paths.append(Path(str(worktree_path)))
        for artifact_path in e2e_result.get("artifact_paths") or []:
            touched_paths.append(Path(str(artifact_path)))
    writes_outside_temp_roots = _paths_outside_roots(touched_paths, touched_roots)
    if writes_outside_temp_roots:
        errors.append(_error("WRITE_OUTSIDE_TEMP_ROOTS", "Smoke detected writes outside temp roots"))

    return E2ERegistrySeededSmokeResult(
        ok=not errors and bool(e2e_result) and e2e_result.get("domain_status") == "accepted",
        project_key=adapter.project_key,
        state_root=str(state_root),
        worktree_root=str(worktree_root),
        packet_root=str(packet_root),
        selected_packet_id=selected_packet_id,
        bootstrap_apply_count=bootstrap_plan.apply_count,
        sync_plan=_sync_result_to_dict(sync_result),
        submit_plan=submit_plan,
        e2e_result=e2e_result,
        registry_before=registry_before,
        registry_after=registry_after,
        cases=cases,
        prefect_runs_created=prefect_runs_created,
        live_agents_started=0,
        writes_outside_temp_roots=writes_outside_temp_roots,
        warnings=warnings,
        errors=errors,
    )


#END_BLOCK_SMOKE
