# ############################################################################
# AI_HEADER: single_live_prefect_packet_pilot
# ROLE: Guarded one-packet Prefect-managed scratch pilot.
# ############################################################################

# START_MODULE_CONTRACT
# purpose: Plan or run one synthetic scratch packet through the managed Prefect packet runner.
# inputs: Project config path, explicit temp roots, live-agent gates, and optional test hooks.
# returns: SingleLivePrefectPacketPilotResult with bounded submission and scope evidence.
# side_effects: Writes synthetic packet/state under explicit temp roots and may submit one Prefect flow run after all gates.
# emitted_logs: None.
# error_behavior: Returns structured errors for gate, planning, submission, status, and scope failures.
# END_MODULE_CONTRACT

# START_MODULE_MAP
# mapping:
#   - class: SingleLivePrefectPacketPilotResult
#   - function: run_single_live_prefect_packet_pilot
#   - function: create_bounded_prefect_status_reader
# END_MODULE_MAP

from __future__ import annotations

from dataclasses import asdict, dataclass, field
import hashlib
import os
from pathlib import Path
from typing import Any, Callable

from prefect_grace.platform.backlog_controller import BacklogController
from prefect_grace.platform.controller_backlog_bootstrap import build_backlog_bootstrap_plan
from prefect_grace.platform.live_opt_in_single_scratch_packet import (
    _ensure_synthetic_git_repo,
    _load_registry_map,
    _paths_outside_roots,
    _reset_temp_roots,
    _sync_result_to_dict,
    _validate_roots,
)
from prefect_grace.platform.prefect_native_submission import submit_ready_packets_to_prefect
from prefect_grace.platform.project_adapter import load_project_adapter
from prefect_grace.platform.scope_guard import validate_scope
from prefect_grace.tasks.prefect_submitter import MANAGED_PACKET_DEPLOYMENT_NAME

MODE = "single_live_prefect_packet_pilot"
FEATURE_ID = "FEAT-GRACE-SINGLE-LIVE-PREFECT-PACKET-PILOT"
WAVE_ID = "W01"
PACKET_ID = "SINGLE-LIVE-PREFECT-PACKET-PILOT-W01-SCRATCH"
EXTRA_PACKET_ID = "SINGLE-LIVE-PREFECT-PACKET-PILOT-W01-EXTRA"
OPT_IN_TOKEN = "single-live-prefect"
SCRATCH_ALLOWED_SCOPE = "scratch/grace-single-live-prefect/**"
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
class SingleLivePrefectPacketPilotResult:
    """Bounded result for the managed Prefect scratch packet pilot."""

    ok: bool
    project_key: str
    mode: str
    dry_run: bool
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
    prefect_runs_created: int
    live_agents_started: int
    domain_status: str | None
    scope_verdict: str | None
    changed_files: list[str]
    writes_outside_temp_roots: list[str]
    poll_events: list[dict[str, Any]]
    warnings: list[str]
    errors: list[dict[str, Any]]
    bootstrap_apply_count: int = 0
    sync_plan: dict[str, Any] = field(default_factory=dict)

    # START_FUNCTION_CONTRACT
    # name: to_dict
    # purpose: Serialize pilot result to a JSON-safe dictionary without secret tokens.
    # inputs:
    #   self: SingleLivePrefectPacketPilotResult instance.
    # returns: dict[str, Any] with all bounded result fields.
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


def _result_dict(value: Any) -> dict[str, Any]:
    if hasattr(value, "to_dict"):
        converted = value.to_dict()
        return converted if isinstance(converted, dict) else {}
    if isinstance(value, dict):
        return dict(value)
    return {}


def _packet_markdown(packet_id: str) -> str:
    return f"""# Execution Packet: {packet_id}

## Objective
Write one deterministic scratch file through the managed Prefect packet runner.

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
- No backend, frontend, platform, script, tool, compose, environment, source packet, or registry files may be edited outside temp roots.
- Git commit, push, and merge are disabled for this pilot.

## Verification
Run the managed Prefect packet runner with dry_run=false only after explicit live-agent opt-in gates.

## Expected Evidence
- Exactly one managed Prefect flow run is created.
- A deterministic file is written under `scratch/grace-single-live-prefect/`.
- Scope verdict confirms only scratch writes.

## Escalation Triggers
- More than one packet is selected.
- Any opt-in gate is missing for live mode.
- Any write lands outside explicit temporary roots or outside the scratch allowed scope.
"""


def _write_scratch_packet(packet_root: Path, *, extra_ready_packet: bool = False) -> Path:
    packets_dir = packet_root / "packets"
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


def _opt_in_errors(*, execute_agent: bool, acknowledge_live_agent: bool, opt_in_token: str | None) -> list[dict[str, Any]]:
    errors: list[dict[str, Any]] = []
    if not execute_agent:
        errors.append(_error("LIVE_PREFECT_EXECUTE_AGENT_REQUIRED", "--execute-agent is required for live Prefect pilot execution."))
    if not acknowledge_live_agent:
        errors.append(_error("LIVE_PREFECT_ACK_REQUIRED", "--i-understand-live-agent is required for live Prefect pilot execution."))
    if opt_in_token != OPT_IN_TOKEN:
        errors.append(_error("LIVE_PREFECT_TOKEN_REQUIRED", "Required live Prefect opt-in token is missing or invalid."))
    return errors


def _empty_result(
    *,
    ok: bool,
    project_key: str,
    dry_run: bool,
    opt_in_confirmed: bool,
    state_root: Path,
    worktree_root: Path,
    packet_root: Path,
    errors: list[dict[str, Any]],
    warnings: list[str] | None = None,
) -> SingleLivePrefectPacketPilotResult:
    return SingleLivePrefectPacketPilotResult(
        ok=ok,
        project_key=project_key,
        mode=MODE,
        dry_run=dry_run,
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
        prefect_runs_created=0,
        live_agents_started=0,
        domain_status=None,
        scope_verdict=None,
        changed_files=[],
        writes_outside_temp_roots=[],
        poll_events=[],
        warnings=warnings or [],
        errors=errors,
    )


def _submission_record_fields(record: Any) -> dict[str, Any]:
    if hasattr(record, "to_dict"):
        return record.to_dict()
    return dict(record)


def _pilot_idempotency_namespace(*, state_root: Path, worktree_root: Path, packet_root: Path) -> str:
    seed = "|".join(
        str(path.resolve(strict=False))
        for path in (state_root, worktree_root, packet_root)
    )
    digest = hashlib.sha256(seed.encode("utf-8")).hexdigest()[:16]
    return f"{MODE}-{digest}"


def _prefect_state_type_name(value: Any) -> str | None:
    if value is None:
        return None
    enum_value = getattr(value, "value", None)
    if enum_value:
        return str(enum_value)
    enum_name = getattr(value, "name", None)
    if enum_name:
        return str(enum_name)
    return str(value)


def _flow_run_parameters(flow_run: Any) -> dict[str, Any]:
    parameters = getattr(flow_run, "parameters", None)
    if isinstance(parameters, dict):
        return dict(parameters)
    return {}


def _coerce_status_payload(state_data: Any) -> dict[str, Any]:
    if isinstance(state_data, dict):
        return dict(state_data)
    if hasattr(state_data, "__dict__"):
        return dict(vars(state_data))
    return {
        "domain_status": getattr(state_data, "domain_status", None),
        "scope_verdict": getattr(state_data, "scope_verdict", None),
        "live_agents_started": getattr(state_data, "live_agents_started", 0),
        "changed_files": getattr(state_data, "changed_files", []),
    }


def _status_from_payload(payload: dict[str, Any], poll_events: list[dict[str, Any]]) -> dict[str, Any]:
    from prefect_grace.tasks.managed_packet_artifacts import (
        managed_result_live_agents_started,
        managed_result_scope_verdict,
    )

    domain_status = payload.get("domain_status")
    scope_verdict = managed_result_scope_verdict(payload)
    live_agents_started = managed_result_live_agents_started(payload)
    changed_files = payload.get("changed_files") or []
    payload_errors = payload.get("errors", [])

    if not isinstance(changed_files, list):
        changed_files = []
    if payload_errors and not isinstance(payload_errors, list):
        payload_errors = [payload_errors]

    if domain_status is None or scope_verdict is None:
        return {
            "ok": False,
            "domain_status": domain_status,
            "scope_verdict": scope_verdict or "evidence_incomplete",
            "live_agents_started": live_agents_started,
            "changed_files": changed_files,
            "poll_events": poll_events,
            "errors": [{"code": "FLOW_RUN_EVIDENCE_INCOMPLETE", "message": "Flow run completed but domain/scope evidence is incomplete"}],
        }

    ok = (domain_status in ("accepted", "passed") and scope_verdict == "passed")
    result = {
        "ok": ok,
        "domain_status": domain_status,
        "scope_verdict": scope_verdict,
        "live_agents_started": live_agents_started,
        "changed_files": changed_files,
        "poll_events": poll_events,
    }
    if payload_errors:
        result["errors"] = payload_errors
    return result


def _status_from_managed_payload_file(flow_run: Any, poll_events: list[dict[str, Any]]) -> dict[str, Any]:
    from prefect_grace.tasks.managed_packet_artifacts import read_managed_result_payload

    parameters = _flow_run_parameters(flow_run)
    payload_path = parameters.get("managed_result_payload_path") or parameters.get("result_payload_path")
    payload_root = parameters.get("managed_result_payload_root")

    if not payload_path:
        return {
            "ok": False,
            "domain_status": None,
            "scope_verdict": "payload_missing",
            "live_agents_started": 0,
            "changed_files": [],
            "poll_events": poll_events,
            "errors": [{"code": "MANAGED_RESULT_PAYLOAD_PATH_MISSING", "message": "Flow run completed without API payload and no managed result payload path parameter is available"}],
        }

    try:
        payload = read_managed_result_payload(payload_path=str(payload_path), payload_root=str(payload_root or ""))
    except FileNotFoundError as e:
        return {
            "ok": False,
            "domain_status": None,
            "scope_verdict": "payload_missing",
            "live_agents_started": 0,
            "changed_files": [],
            "poll_events": poll_events,
            "errors": [{"code": "MANAGED_RESULT_PAYLOAD_FILE_MISSING", "message": str(e)}],
        }
    except Exception as e:
        return {
            "ok": False,
            "domain_status": None,
            "scope_verdict": "payload_read_failed",
            "live_agents_started": 0,
            "changed_files": [],
            "poll_events": poll_events,
            "errors": [{"code": "MANAGED_RESULT_PAYLOAD_READ_FAILED", "message": str(e)}],
        }

    return _status_from_payload(payload, poll_events)


# START_FUNCTION_CONTRACT
# Function: create_bounded_prefect_status_reader
# Purpose: Create bounded status reader that polls Prefect flow run until completion or timeout
# Args:
#   - prefect_client: Prefect client for API calls (optional, will create if None)
# Returns: Callable status reader that accepts flow_run_id, packet_id, timeout_seconds
# Inputs: Optional Prefect client
# Side_effects: Polls Prefect API, sleeps between polls
# Emitted_logs: None
# Error_behavior: Returns error dict on timeout or API failure
# END_FUNCTION_CONTRACT
def create_bounded_prefect_status_reader(prefect_client: Any | None = None) -> Callable[..., dict[str, Any]]:
    """Create bounded status reader for Prefect flow run polling.

    Returns a callable that polls Prefect flow run status with:
    - Bounded timeout
    - Bounded poll events (max 100)
    - No unbounded log streaming
    - Final domain/scope status from flow run result
    """
    import time

    def _status_reader_impl(*, flow_run_id: str, packet_id: str, timeout_seconds: int) -> dict[str, Any]:
        # Create client if not provided
        client = prefect_client
        if client is None:
            try:
                from prefect_grace.platform.runtime_adapter import create_prefect_sync_client
                client = create_prefect_sync_client()
                if client is None:
                    return {
                        "ok": False,
                        "domain_status": None,
                        "scope_verdict": "prefect_unavailable",
                        "live_agents_started": 0,
                        "changed_files": [],
                        "poll_events": [],
                        "errors": [{"code": "PREFECT_CLIENT_UNAVAILABLE", "message": "Prefect client not available"}],
                    }
            except Exception as e:
                return {
                    "ok": False,
                    "domain_status": None,
                    "scope_verdict": "prefect_unavailable",
                    "live_agents_started": 0,
                    "changed_files": [],
                    "poll_events": [],
                    "errors": [{"code": "PREFECT_CLIENT_CREATION_FAILED", "message": str(e)}],
                }

        poll_events = []
        start_time = time.time()
        poll_interval = 2  # seconds
        max_events = 100

        try:
            while True:
                elapsed = time.time() - start_time
                if elapsed > timeout_seconds:
                    return {
                        "ok": False,
                        "domain_status": "timeout",
                        "scope_verdict": "pending_timeout",
                        "live_agents_started": 0,
                        "changed_files": [],
                        "poll_events": poll_events,
                        "errors": [{"code": "WORKER_TIMEOUT", "message": f"Flow run did not complete within {timeout_seconds}s"}],
                    }

                # Read flow run state
                try:
                    flow_run = client.read_flow_run(flow_run_id)
                except Exception as e:
                    return {
                        "ok": False,
                        "domain_status": None,
                        "scope_verdict": "flow_run_read_failed",
                        "live_agents_started": 0,
                        "changed_files": [],
                        "poll_events": poll_events,
                        "errors": [{"code": "FLOW_RUN_READ_FAILED", "message": str(e)}],
                    }

                state_type = _prefect_state_type_name(getattr(flow_run, "state_type", None))
                state_name = getattr(flow_run, "state_name", None)

                # Record poll event (bounded)
                if len(poll_events) < max_events:
                    poll_events.append({
                        "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                        "state_type": state_type,
                        "state_name": state_name,
                        "elapsed_seconds": int(elapsed),
                    })

                # Check if terminal state
                if state_type in ("COMPLETED", "FAILED", "CANCELLED", "CRASHED", "CANCELLING"):
                    # Extract result from flow run state
                    if state_type == "COMPLETED":
                        # Read payload from flow run state
                        state = getattr(flow_run, "state", None)
                        state_data = getattr(state, "data", None) if state else None

                        if state_data is None:
                            return _status_from_managed_payload_file(flow_run, poll_events)

                        # Extract domain/scope evidence from payload
                        try:
                            payload = _coerce_status_payload(state_data)
                            return _status_from_payload(payload, poll_events)

                        except Exception as e:
                            return {
                                "ok": False,
                                "domain_status": None,
                                "scope_verdict": "payload_read_failed",
                                "live_agents_started": 0,
                                "changed_files": [],
                                "poll_events": poll_events,
                                "errors": [{"code": "FLOW_RUN_PAYLOAD_READ_FAILED", "message": f"Failed to read flow run payload: {e}"}],
                            }
                    else:
                        # Non-completed terminal states
                        return {
                            "ok": False,
                            "domain_status": "failed",
                            "scope_verdict": "flow_failed",
                            "live_agents_started": 0,
                            "changed_files": [],
                            "poll_events": poll_events,
                            "errors": [{"code": "FLOW_RUN_FAILED", "message": f"Flow run ended in {state_type} state"}],
                        }

                # Sleep before next poll
                time.sleep(poll_interval)

        except Exception as e:
            return {
                "ok": False,
                "domain_status": None,
                "scope_verdict": "status_reader_error",
                "live_agents_started": 0,
                "changed_files": [],
                "poll_events": poll_events,
                "errors": [{"code": "STATUS_READER_ERROR", "message": str(e)}],
            }

    return _status_reader_impl


def _status_reader_result(
    *,
    status_reader: Callable[..., Any] | None,
    flow_run_id: str | None,
    packet_id: str,
    timeout_seconds: int,
) -> dict[str, Any]:
    if status_reader is None:
        return {
            "ok": False,
            "domain_status": None,
            "scope_verdict": "pending_prefect_flow",
            "live_agents_started": 0,
            "changed_files": [],
            "poll_events": [],
            "errors": [
                _error(
                    "LIVE_PREFECT_FINAL_EVIDENCE_PENDING",
                    "Prefect flow was submitted, but final managed-runner domain and scope evidence is not available in this process.",
                )
            ],
        }
    return _result_dict(
        status_reader(
            flow_run_id=flow_run_id,
            packet_id=packet_id,
            timeout_seconds=timeout_seconds,
        )
    )


#END_BLOCK_HELPERS
#START_BLOCK_PILOT
# START_FUNCTION_CONTRACT
# name: run_single_live_prefect_packet_pilot
# purpose: Plan or run one synthetic scratch packet through managed Prefect submission.
# inputs:
#   project_config: Path to project config.
#   state_root: Explicit temporary state root.
#   worktree_root: Explicit temporary worktree root.
#   packet_root: Explicit temporary packet source root.
#   dry_run: Safe default, plans only and creates zero Prefect flow runs.
#   execute_agent: Required live-agent execution flag for non-dry-run mode.
#   acknowledge_live_agent: Required operator acknowledgement for non-dry-run mode.
#   opt_in_token: Required opt-in token for non-dry-run mode, or None to read environment.
#   timeout_seconds: Submission/status timeout seconds.
#   submitter: Optional Prefect submitter hook for tests.
#   status_reader: Optional bounded status reader hook for tests.
#   extra_ready_packet: Test hook proving multi-packet plans fail closed.
# returns: SingleLivePrefectPacketPilotResult.
# side_effects: Writes temp packet/state and may submit one Prefect managed packet flow run after all gates.
# emitted_logs: None.
# error_behavior: Returns structured errors instead of raising for expected pilot failures.
# END_FUNCTION_CONTRACT
def run_single_live_prefect_packet_pilot(
    *,
    project_config: Path,
    state_root: Path,
    worktree_root: Path,
    packet_root: Path,
    dry_run: bool = True,
    execute_agent: bool = False,
    acknowledge_live_agent: bool = False,
    opt_in_token: str | None = None,
    timeout_seconds: int = 1800,
    submitter: Callable[..., dict[str, Any]] | None = None,
    status_reader: Callable[..., Any] | None = None,
    extra_ready_packet: bool = False,
) -> SingleLivePrefectPacketPilotResult:
    base_adapter = load_project_adapter(project_config)
    token = opt_in_token if opt_in_token is not None else os.environ.get("GRACE_LIVE_PREFECT_PACKET_OPT_IN")

    if not dry_run:
        gate_errors = _opt_in_errors(
            execute_agent=execute_agent,
            acknowledge_live_agent=acknowledge_live_agent,
            opt_in_token=token,
        )
        if gate_errors:
            return _empty_result(
                ok=False,
                project_key=base_adapter.project_key,
                dry_run=dry_run,
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
            dry_run=dry_run,
            opt_in_confirmed=not dry_run,
            state_root=state_root,
            worktree_root=worktree_root,
            packet_root=packet_root,
            errors=root_errors,
        )

    warnings: list[str] = []
    errors: list[dict[str, Any]] = []
    idempotency_namespace = _pilot_idempotency_namespace(
        state_root=state_root,
        worktree_root=worktree_root,
        packet_root=packet_root,
    )
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
        runner_kind="managed",
        idempotency_namespace=idempotency_namespace,
    )
    submit_plan = dry_submit.to_dict()
    submit_plan["packets_to_submit"] = list(dry_submit.packets_planned)
    warnings.extend(dry_submit.warnings)
    errors.extend(dry_submit.errors)

    selected_packet_id = dry_submit.packets_planned[0] if dry_submit.packets_planned == [PACKET_ID] else None
    if dry_submit.packets_planned != [PACKET_ID]:
        errors.append(
            _error(
                "LIVE_PREFECT_PACKET_COUNT_INVALID",
                "Managed Prefect dry-run plan must select exactly the synthetic scratch packet.",
                packets_planned=list(dry_submit.packets_planned),
            )
        )

    deployment_name = None
    work_queue_name = None
    flow_run_id = None
    flow_run_name = None
    flow_run_url = None
    prefect_runs_created = 0
    live_agents_started = 0
    domain_status = None
    scope_verdict = None
    changed_files: list[str] = []
    poll_events: list[dict[str, Any]] = []

    if dry_submit.records:
        record_data = _submission_record_fields(dry_submit.records[0])
        deployment_name = record_data.get("deployment_name")
        work_queue_name = record_data.get("work_queue_name")
        flow_run_name = record_data.get("flow_run_name")

    if not dry_run and selected_packet_id and not errors:
        if submitter is None:
            from prefect_grace.platform.runtime_adapter import ManagedPacketSubmitter
            submitter = ManagedPacketSubmitter()

        submission = submit_ready_packets_to_prefect(
            project=adapter,
            dry_run=False,
            limit=1,
            execute_agent=True,
            timeout_seconds=timeout_seconds,
            worktree_root=worktree_root,
            submitter=submitter,
            runner_kind="managed",
            idempotency_namespace=idempotency_namespace,
        )
        errors.extend(submission.errors)
        if len(submission.records) != 1:
            errors.append(_error("LIVE_PREFECT_SUBMISSION_COUNT_INVALID", f"Expected one submission record; got {len(submission.records)}."))
        elif not submission.errors:
            record = submission.records[0]
            deployment_name = record.deployment_name
            work_queue_name = record.work_queue_name
            flow_run_id = record.flow_run_id
            flow_run_name = record.flow_run_name
            flow_run_url = record.url
            if record.packet_id != PACKET_ID:
                errors.append(_error("LIVE_PREFECT_WRONG_PACKET_SUBMITTED", f"Expected {PACKET_ID}; got {record.packet_id}."))
            if record.deployment_name != MANAGED_PACKET_DEPLOYMENT_NAME:
                errors.append(_error("LIVE_PREFECT_UNEXPECTED_DEPLOYMENT", f"Expected {MANAGED_PACKET_DEPLOYMENT_NAME}; got {record.deployment_name}."))
            if record.status != "submitted":
                errors.append(_error("LIVE_PREFECT_NOT_SUBMITTED", record.error or record.status))
            if record.status == "submitted":
                prefect_runs_created = 1
                status_result = _status_reader_result(
                    status_reader=status_reader,
                    flow_run_id=flow_run_id,
                    packet_id=PACKET_ID,
                    timeout_seconds=timeout_seconds,
                )
                errors.extend(list(status_result.get("errors") or []))
                live_agents_started = int(status_result.get("live_agents_started") or status_result.get("agent_launch_count") or 0)
                domain_status = status_result.get("domain_status")
                scope_verdict = status_result.get("scope_verdict")
                changed_files = list(status_result.get("changed_files") or [])
                poll_events = list(status_result.get("poll_events") or [])
                if not status_result.get("ok", False):
                    errors.append(_error("LIVE_PREFECT_STATUS_NOT_OK", "Managed Prefect status reader did not return ok=true."))

    if status_reader is not None and changed_files:
        scope_result = validate_scope(
            changed_files,
            [SCRATCH_ALLOWED_SCOPE],
            FROZEN_SCOPE,
            repo_root=packet_root,
        )
        if not scope_result.ok:
            errors.append(
                _error(
                    "LIVE_PREFECT_CHANGED_FILES_OUTSIDE_SCRATCH",
                    "Managed Prefect pilot changed files outside the synthetic scratch allowed scope.",
                    scope_result=scope_result.to_dict(),
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
        errors.append(_error("WRITE_OUTSIDE_TEMP_ROOTS", "Pilot detected writes outside temp roots."))

    ok = (
        not errors
        and selected_packet_id == PACKET_ID
        and not writes_outside_temp_roots
        and (
            dry_run
            or (
                prefect_runs_created == 1
                and live_agents_started == 1
                and domain_status in {"accepted", "passed"}
                and scope_verdict == "passed"
            )
        )
    )

    return SingleLivePrefectPacketPilotResult(
        ok=ok,
        project_key=adapter.project_key,
        mode=MODE,
        dry_run=dry_run,
        opt_in_confirmed=dry_run or not _opt_in_errors(
            execute_agent=execute_agent,
            acknowledge_live_agent=acknowledge_live_agent,
            opt_in_token=token,
        ),
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
        prefect_runs_created=prefect_runs_created,
        live_agents_started=live_agents_started,
        domain_status=domain_status,
        scope_verdict=scope_verdict,
        changed_files=changed_files,
        writes_outside_temp_roots=writes_outside_temp_roots,
        poll_events=poll_events,
        warnings=warnings,
        errors=errors,
        bootstrap_apply_count=bootstrap_plan.apply_count,
        sync_plan=_sync_result_to_dict(sync_result),
    )


#END_BLOCK_PILOT
