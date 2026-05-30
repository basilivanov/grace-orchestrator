# ############################################################################
# AI_HEADER: live_opt_in_single_scratch_packet
# ROLE: Explicit opt-in smoke for one synthetic live-agent scratch packet.
# ############################################################################

# START_MODULE_CONTRACT
# purpose: Build and optionally run one registry-selected scratch packet behind explicit live-agent opt-in gates.
# inputs: Project config path, explicit temp roots, live-agent gate flags, opt-in token, and optional test hooks.
# returns: LiveOptInSingleScratchResult with registry, submission, scope, and safety evidence.
# side_effects: Writes synthetic packet/state under explicit temp roots and may submit or run one live E2E packet.
# emitted_logs: None.
# error_behavior: Returns structured errors for expected gate, root, planning, submission, and scope failures.
# END_MODULE_CONTRACT

# START_MODULE_MAP
# mapping:
#   - class: LiveOptInSingleScratchResult
#   - function: run_live_opt_in_single_scratch_packet
# END_MODULE_MAP

from __future__ import annotations

from dataclasses import asdict, dataclass, field
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
from typing import Any, Callable

import yaml

from prefect_grace.platform.backlog_controller import BacklogController
from prefect_grace.platform.controller_backlog_bootstrap import build_backlog_bootstrap_plan
from prefect_grace.platform.prefect_native_submission import submit_ready_packets_to_prefect
from prefect_grace.platform.project_adapter import load_project_adapter
from prefect_grace.platform.scope_guard import validate_scope
from prefect_grace.tasks.prefect_submitter import E2E_PACKET_DEPLOYMENT_NAME

MODE = "live_opt_in_single_scratch_packet"
FEATURE_ID = "FEAT-GRACE-LIVE-OPT-IN-SINGLE-SCRATCH-PACKET"
WAVE_ID = "W01"
PACKET_ID = "LIVE-OPT-IN-SINGLE-SCRATCH-W01-SCRATCH"
EXTRA_PACKET_ID = "LIVE-OPT-IN-SINGLE-SCRATCH-W01-EXTRA"
OPT_IN_TOKEN = "single-scratch"
SCRATCH_ALLOWED_SCOPE = "scratch/grace-live-opt-in-single-scratch/**"
FROZEN_SCOPE = [
    "backend/**",
    "frontend/**",
    "prefect_grace/**",
    "scripts/**",
    "tools/**",
    "docker-compose*.yml",
    ".env",
]


#START_BLOCK_MODELS
@dataclass(frozen=True)
class LiveOptInSingleScratchResult:
    ok: bool
    project_key: str
    mode: str
    opt_in_confirmed: bool
    state_root: str
    worktree_root: str
    packet_root: str
    selected_packet_id: str | None
    registry_before: dict[str, Any]
    registry_after: dict[str, Any]
    submit_plan: dict[str, Any]
    deployment_name: str | None
    work_queue_name: str | None
    flow_run_id: str | None
    flow_run_name: str | None
    flow_run_url: str | None
    agent_launch_count: int
    domain_status: str | None
    scope_verdict: str | None
    changed_files: list[str]
    writes_outside_temp_roots: list[str]
    warnings: list[str]
    errors: list[dict[str, Any]]
    bootstrap_apply_count: int = 0
    sync_plan: dict[str, Any] = field(default_factory=dict)

    # START_FUNCTION_CONTRACT
    # name: to_dict
    # purpose: Serialize live opt-in smoke result to a JSON-safe dictionary without secret token values.
    # inputs:
    #   self: LiveOptInSingleScratchResult instance.
    # returns: dict[str, Any] with all smoke result fields.
    # side_effects: None.
    # emitted_logs: None.
    # error_behavior: None.
    # END_FUNCTION_CONTRACT
    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


#END_BLOCK_MODELS
#START_BLOCK_HELPERS
def _error(code: str, message: str, **extra: Any) -> dict[str, Any]:
    return {"code": code, "message": message, **extra}


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
        _run_git(["commit", "--allow-empty", "-m", "Initial synthetic live opt-in scratch commit"], packet_root)
    _run_git(["worktree", "prune"], packet_root)


def _packet_markdown(packet_id: str) -> str:
    return f"""# Execution Packet: {packet_id}

## Objective
Write one tiny deterministic scratch evidence file only.

## Slice
- packet_id: `{packet_id}`
- feature_id: `{FEATURE_ID}`
- wave_id: `{WAVE_ID}`
- status: `ready`

## Allowed Write Scope
- {SCRATCH_ALLOWED_SCOPE}

## Frozen Scope
{chr(10).join(f"- {scope}" for scope in FROZEN_SCOPE)}

## Must Preserve
- Live execution must remain bounded to this single synthetic scratch packet.
- No backend, frontend, platform, script, tool, compose, or environment files may be edited.

## Verification
Run the E2E packet runner with dry_run=false only after explicit live-agent opt-in gates.

## Expected Evidence
- A deterministic file under `scratch/grace-live-opt-in-single-scratch/`.
- Registry plan selecting exactly this packet.
- Scope verdict confirming only scratch writes.

## Escalation Triggers
- More than one packet is selected.
- Any opt-in gate is missing.
- Any write lands outside explicit temporary roots or outside the scratch allowed scope.
"""


def _write_scratch_packet(packet_root: Path, *, extra_ready_packet: bool = False) -> Path:
    packets_dir = packet_root / "packets"
    if packets_dir.exists():
        shutil.rmtree(packets_dir)
    packets_dir.mkdir(parents=True, exist_ok=True)

    packet_dir = packets_dir / PACKET_ID
    packet_dir.mkdir(parents=True, exist_ok=True)
    packet_path = packet_dir / "EXECUTION_PACKET.md"
    packet_path.write_text(_packet_markdown(PACKET_ID), encoding="utf-8")

    if extra_ready_packet:
        extra_dir = packets_dir / EXTRA_PACKET_ID
        extra_dir.mkdir(parents=True, exist_ok=True)
        (extra_dir / "EXECUTION_PACKET.md").write_text(_packet_markdown(EXTRA_PACKET_ID), encoding="utf-8")

    return packet_path


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
    return data if isinstance(data, dict) else {}


def _paths_outside_roots(paths: list[Path], roots: list[Path]) -> list[str]:
    outside = []
    for path in paths:
        if not any(_is_relative_to(path, root) for root in roots):
            outside.append(str(path))
    return outside


def _result_dict(value: Any) -> dict[str, Any]:
    if hasattr(value, "to_dict"):
        converted = value.to_dict()
        return converted if isinstance(converted, dict) else {}
    if isinstance(value, dict):
        return dict(value)
    return {}


def _empty_result(
    *,
    ok: bool,
    project_key: str,
    opt_in_confirmed: bool,
    state_root: Path,
    worktree_root: Path,
    packet_root: Path,
    errors: list[dict[str, Any]],
    warnings: list[str] | None = None,
) -> LiveOptInSingleScratchResult:
    return LiveOptInSingleScratchResult(
        ok=ok,
        project_key=project_key,
        mode=MODE,
        opt_in_confirmed=opt_in_confirmed,
        state_root=str(state_root),
        worktree_root=str(worktree_root),
        packet_root=str(packet_root),
        selected_packet_id=None,
        registry_before={},
        registry_after={},
        submit_plan={},
        deployment_name=None,
        work_queue_name=None,
        flow_run_id=None,
        flow_run_name=None,
        flow_run_url=None,
        agent_launch_count=0,
        domain_status=None,
        scope_verdict=None,
        changed_files=[],
        writes_outside_temp_roots=[],
        warnings=warnings or [],
        errors=errors,
    )


def _opt_in_errors(*, execute_agent: bool, acknowledge_live_agent: bool, opt_in_token: str | None) -> list[dict[str, Any]]:
    errors: list[dict[str, Any]] = []
    if not execute_agent:
        errors.append(_error("LIVE_OPT_IN_EXECUTE_AGENT_REQUIRED", "--execute-agent is required for live smoke execution."))
    if not acknowledge_live_agent:
        errors.append(_error("LIVE_OPT_IN_ACK_REQUIRED", "--i-understand-live-agent is required for live smoke execution."))
    if opt_in_token != OPT_IN_TOKEN:
        errors.append(_error("LIVE_OPT_IN_TOKEN_REQUIRED", "Required live-agent opt-in token is missing or invalid."))
    return errors


#END_BLOCK_HELPERS
#START_BLOCK_SMOKE
# START_FUNCTION_CONTRACT
# name: run_live_opt_in_single_scratch_packet
# purpose: Execute a fail-closed live-agent smoke for exactly one synthetic scratch packet.
# inputs:
#   project_config: Path to project config.
#   state_root: Explicit temporary state root.
#   worktree_root: Explicit temporary worktree root.
#   packet_root: Explicit synthetic packet root.
#   execute_agent: Required live-agent execution flag.
#   acknowledge_live_agent: Required operator acknowledgement flag.
#   opt_in_token: Required token value or None to read GRACE_LIVE_AGENT_OPT_IN.
#   timeout_seconds: Live runner or Prefect submission timeout seconds.
#   json_safe: Retained for API compatibility; result is JSON-safe.
#   runner: Optional test hook that simulates the E2E runner without live agents.
#   submitter: Optional test hook for Prefect submission.
#   extra_ready_packet: Optional test hook that proves multi-packet plans fail closed.
# returns: LiveOptInSingleScratchResult.
# side_effects: Writes temp fixtures/state and may submit or run one live E2E packet after all gates.
# emitted_logs: None.
# error_behavior: Returns structured errors instead of raising for expected smoke failures.
# END_FUNCTION_CONTRACT
def run_live_opt_in_single_scratch_packet(
    *,
    project_config: Path,
    state_root: Path,
    worktree_root: Path,
    packet_root: Path,
    execute_agent: bool = False,
    acknowledge_live_agent: bool = False,
    opt_in_token: str | None = None,
    timeout_seconds: int = 1800,
    json_safe: bool = True,
    runner: Callable[..., Any] | None = None,
    submitter: Callable[..., dict[str, Any]] | None = None,
    extra_ready_packet: bool = False,
) -> LiveOptInSingleScratchResult:
    base_adapter = load_project_adapter(project_config)
    token = opt_in_token if opt_in_token is not None else os.environ.get("GRACE_LIVE_AGENT_OPT_IN")
    gate_errors = _opt_in_errors(
        execute_agent=execute_agent,
        acknowledge_live_agent=acknowledge_live_agent,
        opt_in_token=token,
    )
    if gate_errors:
        return _empty_result(
            ok=False,
            project_key=base_adapter.project_key,
            opt_in_confirmed=False,
            state_root=state_root,
            worktree_root=worktree_root,
            packet_root=packet_root,
            errors=gate_errors,
        )

    root_errors = _validate_roots(
        state_root=state_root,
        worktree_root=worktree_root,
        packet_root=packet_root,
        repo_root=Path(base_adapter.repo_root),
    )
    if root_errors:
        return _empty_result(
            ok=False,
            project_key=base_adapter.project_key,
            opt_in_confirmed=True,
            state_root=state_root,
            worktree_root=worktree_root,
            packet_root=packet_root,
            errors=root_errors,
        )

    warnings: list[str] = []
    errors: list[dict[str, Any]] = []
    _reset_temp_roots(state_root, worktree_root, packet_root)
    _ensure_synthetic_git_repo(packet_root)
    packet_path = _write_scratch_packet(packet_root, extra_ready_packet=extra_ready_packet)

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
    registry_before = _load_registry_map(state_root)

    sync_result = BacklogController.sync(adapter, dry_run=True)
    warnings.extend(sync_result.warnings)
    errors.extend(_error("SYNC_DRY_RUN_FAILED", str(err)) for err in sync_result.errors)

    dry_submit = submit_ready_packets_to_prefect(
        project=adapter,
        dry_run=True,
        limit=None,
        execute_agent=True,
        timeout_seconds=timeout_seconds,
        worktree_root=worktree_root,
        submitter=None,
        runner_kind="e2e",
    )
    submit_plan = dry_submit.to_dict()
    submit_plan["packets_to_submit"] = list(dry_submit.packets_planned)
    warnings.extend(dry_submit.warnings)
    errors.extend(dry_submit.errors)

    selected_packet_id = dry_submit.packets_planned[0] if dry_submit.packets_planned == [PACKET_ID] else None
    if dry_submit.packets_planned != [PACKET_ID]:
        errors.append(
            _error(
                "LIVE_OPT_IN_PACKET_COUNT_INVALID",
                "Registry-aware submit dry-run must select exactly the synthetic scratch packet.",
                packets_planned=list(dry_submit.packets_planned),
            )
        )

    deployment_name = None
    work_queue_name = None
    flow_run_id = None
    flow_run_name = None
    flow_run_url = None
    agent_launch_count = 0
    domain_status = None
    scope_verdict = None
    changed_files: list[str] = []

    if selected_packet_id and not errors:
        if runner is not None:
            runner_result = _result_dict(
                runner(
                    project_root=packet_root,
                    packet_path=packet_path,
                    state_root=state_root,
                    worktree_root=worktree_root,
                    project_key=adapter.project_key,
                    attempt=1,
                    base_ref="HEAD",
                    dry_run=False,
                    execute_agent=True,
                    timeout_seconds=timeout_seconds,
                    keep_worktree=True,
                )
            )
            agent_launch_count = 1
            deployment_name = runner_result.get("deployment_name") or E2E_PACKET_DEPLOYMENT_NAME
            work_queue_name = runner_result.get("work_queue_name") or adapter.prefect.live_queue
            flow_run_id = runner_result.get("flow_run_id")
            flow_run_name = runner_result.get("flow_run_name")
            flow_run_url = runner_result.get("flow_run_url") or runner_result.get("url")
            domain_status = runner_result.get("domain_status")
            scope_verdict = runner_result.get("scope_verdict")
            changed_files = list(runner_result.get("changed_files") or [])
            if not runner_result.get("ok", False):
                errors.append(_error("LIVE_OPT_IN_RUNNER_FAILED", "Injected live runner did not return ok=true."))
        else:
            if submitter is None:
                from prefect_grace.platform.runtime_adapter import E2EPacketSubmitter
                submitter = E2EPacketSubmitter()
            submission = submit_ready_packets_to_prefect(
                project=adapter,
                dry_run=False,
                limit=1,
                execute_agent=True,
                timeout_seconds=timeout_seconds,
                worktree_root=worktree_root,
                submitter=submitter,
                runner_kind="e2e",
            )
            errors.extend(submission.errors)
            if len(submission.records) != 1:
                errors.append(_error("LIVE_OPT_IN_SUBMISSION_COUNT_INVALID", f"Expected one submission record; got {len(submission.records)}."))
            elif not submission.errors:
                record = submission.records[0]
                deployment_name = record.deployment_name
                work_queue_name = record.work_queue_name
                flow_run_id = record.flow_run_id
                flow_run_name = record.flow_run_name
                flow_run_url = record.url
                if record.packet_id != PACKET_ID:
                    errors.append(_error("LIVE_OPT_IN_WRONG_PACKET_SUBMITTED", f"Expected {PACKET_ID}; got {record.packet_id}."))
                if record.deployment_name != E2E_PACKET_DEPLOYMENT_NAME:
                    errors.append(_error("LIVE_OPT_IN_UNEXPECTED_DEPLOYMENT", f"Expected {E2E_PACKET_DEPLOYMENT_NAME}; got {record.deployment_name}."))
                if record.status != "submitted":
                    errors.append(_error("LIVE_OPT_IN_NOT_SUBMITTED", record.error or record.status))
                if record.status == "submitted":
                    scope_verdict = "pending_prefect_flow"
                    errors.append(
                        _error(
                            "LIVE_OPT_IN_FINAL_EVIDENCE_PENDING",
                            "Prefect flow was submitted, but final live-agent domain and scope evidence is not available in this process.",
                        )
                    )

    registry_after = _load_registry_map(state_root)
    touched_paths = [
        state_root / "state" / "packet_registry.yaml",
        packet_root / "packets",
        worktree_root,
    ]
    writes_outside_temp_roots = _paths_outside_roots(touched_paths, [state_root, worktree_root, packet_root])
    if writes_outside_temp_roots:
        errors.append(_error("WRITE_OUTSIDE_TEMP_ROOTS", "Smoke detected writes outside temp roots"))

    if runner is not None and selected_packet_id and scope_verdict != "passed":
        errors.append(_error("LIVE_OPT_IN_SCOPE_NOT_PASSED", f"Expected scope_verdict=passed; got {scope_verdict}."))
    if runner is not None and selected_packet_id:
        scope_result = validate_scope(
            changed_files,
            [SCRATCH_ALLOWED_SCOPE],
            FROZEN_SCOPE,
            repo_root=packet_root,
        )
        if not scope_result.ok:
            errors.append(
                _error(
                    "LIVE_OPT_IN_CHANGED_FILES_OUTSIDE_SCRATCH",
                    "Runner changed files outside the synthetic scratch allowed scope.",
                    scope_result=scope_result.to_dict(),
                )
            )

    ok = (
        not errors
        and selected_packet_id == PACKET_ID
        and agent_launch_count == 1
        and domain_status in {"accepted", "passed"}
        and not writes_outside_temp_roots
        and scope_verdict == "passed"
    )

    return LiveOptInSingleScratchResult(
        ok=ok,
        project_key=adapter.project_key,
        mode=MODE,
        opt_in_confirmed=True,
        state_root=str(state_root),
        worktree_root=str(worktree_root),
        packet_root=str(packet_root),
        selected_packet_id=selected_packet_id,
        registry_before=registry_before,
        registry_after=registry_after,
        submit_plan=submit_plan,
        deployment_name=deployment_name,
        work_queue_name=work_queue_name,
        flow_run_id=flow_run_id,
        flow_run_name=flow_run_name,
        flow_run_url=flow_run_url,
        agent_launch_count=agent_launch_count,
        domain_status=domain_status,
        scope_verdict=scope_verdict,
        changed_files=changed_files,
        writes_outside_temp_roots=writes_outside_temp_roots,
        warnings=warnings,
        errors=errors,
        bootstrap_apply_count=bootstrap_plan.apply_count,
        sync_plan=_sync_result_to_dict(sync_result),
    )


#END_BLOCK_SMOKE
