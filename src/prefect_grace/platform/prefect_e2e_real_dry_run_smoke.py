# ############################################################################
# AI_HEADER: prefect_e2e_real_dry_run_smoke
# ROLE: Controlled real Prefect E2E dry-run smoke harness.
# ############################################################################

# START_MODULE_CONTRACT
# purpose: Submit exactly one scratch-only E2E packet to real Prefect with agent dry-run execution.
# inputs: Project config path, isolated smoke roots, timeout/poll controls, optional test hooks.
# returns: PrefectE2ERealDryRunSmokeResult with JSON-safe run and status metadata.
# side_effects: Writes a generated smoke packet and registry entry; may create one Prefect flow run.
# emitted_logs: None.
# error_behavior: Returns structured guard/submission/wait errors; does not raise for expected operator blocks.
# END_MODULE_CONTRACT

# START_MODULE_MAP
# mapping:
#   - class: PrefectE2ERealDryRunSmokeResult
#   - class: _SmokeProject
#   - function: run_prefect_e2e_real_dry_run_smoke
#   - function: _build_smoke_packet_content
#   - function: _read_prefect_flow_run_status
#   - function: _wait_for_flow_run
# END_MODULE_MAP

from __future__ import annotations

from dataclasses import dataclass
import importlib
from pathlib import Path
import time
from typing import Any, Callable

from prefect_grace.platform.backlog_controller import BacklogController
from prefect_grace.platform.packet_parser import parse_packet_markdown
from prefect_grace.platform.prefect_native_submission import submit_ready_packets_to_prefect
from prefect_grace.platform.project_adapter import ProjectAdapterConfig, load_project_adapter
from prefect_grace.platform.state_store import PacketRegistryStore
from prefect_grace.tasks.prefect_submitter import E2E_PACKET_DEPLOYMENT_NAME

SMOKE_FEATURE_ID = "FEAT-GRACE-PREFECT-REAL-E2E-DRY-RUN-SMOKE-MVP"
SMOKE_PACKET_ID = "FEAT-GRACE-PREFECT-REAL-E2E-DRY-RUN-SMOKE-MVP-W01-REAL-E2E-DRY-RUN-SMOKE"
SMOKE_WAVE_ID = "W01"
SMOKE_MODE = "prefect_real_e2e_agent_dry_run"
SUCCESS_STATE_TYPES = {"completed", "cached"}
FAILURE_STATE_TYPES = {"failed", "crashed", "cancelled"}
SUCCESS_DOMAIN_STATUSES = {"accepted", "check_passed"}


#START_BLOCK_MODELS
@dataclass(frozen=True)
class PrefectE2ERealDryRunSmokeResult:
    ok: bool
    mode: str
    packet_id: str
    runner_kind: str
    deployment_name: str
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
    errors: list[dict[str, Any]]

    # START_FUNCTION_CONTRACT
    # name: to_dict
    # purpose: Serialize smoke result to a JSON-safe dict.
    # inputs:
    #   self: PrefectE2ERealDryRunSmokeResult instance.
    # returns: dict[str, Any] with result fields.
    # side_effects: None.
    # emitted_logs: None.
    # error_behavior: None.
    # END_FUNCTION_CONTRACT
    def to_dict(self) -> dict[str, Any]:
        return {
            "ok": self.ok,
            "mode": self.mode,
            "packet_id": self.packet_id,
            "runner_kind": self.runner_kind,
            "deployment_name": self.deployment_name,
            "work_queue_name": self.work_queue_name,
            "flow_run_id": self.flow_run_id,
            "flow_run_name": self.flow_run_name,
            "flow_run_url": self.flow_run_url,
            "submitted": self.submitted,
            "waited": self.waited,
            "prefect_state_type": self.prefect_state_type,
            "prefect_state_name": self.prefect_state_name,
            "domain_status": self.domain_status,
            "artifact_ids": list(self.artifact_ids),
            "errors": list(self.errors),
        }


@dataclass(frozen=True)
class _SmokeProject:
    project_key: str
    repo_root: str
    runtime_state_root: str
    worktree_root: str
    packets_dir: str


#END_BLOCK_MODELS
#START_BLOCK_HELPERS
# START_FUNCTION_CONTRACT
# name: _result
# purpose: Build a real dry-run smoke result with stable defaults.
# inputs:
#   ok: Success flag.
#   submitted: Whether native submission produced a flow run.
#   waited: Whether Prefect wait/status verification ran.
#   errors: Structured errors.
#   work_queue_name: Optional work queue metadata.
#   flow_run_id: Optional Prefect flow run id.
#   flow_run_name: Optional Prefect flow run name.
#   flow_run_url: Optional Prefect flow run URL.
#   prefect_state_type: Optional Prefect state type.
#   prefect_state_name: Optional Prefect state name.
#   domain_status: Optional E2E domain status.
#   artifact_ids: Optional artifact ids.
# returns: PrefectE2ERealDryRunSmokeResult.
# side_effects: None.
# emitted_logs: None.
# error_behavior: None.
# END_FUNCTION_CONTRACT
def _result(
    *,
    ok: bool,
    submitted: bool = False,
    waited: bool = False,
    errors: list[dict[str, Any]] | None = None,
    work_queue_name: str | None = None,
    flow_run_id: str | None = None,
    flow_run_name: str | None = None,
    flow_run_url: str | None = None,
    prefect_state_type: str | None = None,
    prefect_state_name: str | None = None,
    domain_status: str | None = None,
    artifact_ids: list[str] | None = None,
) -> PrefectE2ERealDryRunSmokeResult:
    return PrefectE2ERealDryRunSmokeResult(
        ok=ok,
        mode=SMOKE_MODE,
        packet_id=SMOKE_PACKET_ID,
        runner_kind="e2e",
        deployment_name=E2E_PACKET_DEPLOYMENT_NAME,
        work_queue_name=work_queue_name,
        flow_run_id=flow_run_id,
        flow_run_name=flow_run_name,
        flow_run_url=flow_run_url,
        submitted=submitted,
        waited=waited,
        prefect_state_type=prefect_state_type,
        prefect_state_name=prefect_state_name,
        domain_status=domain_status,
        artifact_ids=list(artifact_ids or []),
        errors=list(errors or []),
    )


# START_FUNCTION_CONTRACT
# name: _build_smoke_packet_content
# purpose: Render the strict scratch-only real dry-run smoke packet.
# inputs: None.
# returns: Markdown packet content.
# side_effects: None.
# emitted_logs: None.
# error_behavior: None.
# END_FUNCTION_CONTRACT
def _build_smoke_packet_content() -> str:
    return f"""# Execution Packet: {SMOKE_PACKET_ID}

- packet_id: {SMOKE_PACKET_ID}
- feature_id: {SMOKE_FEATURE_ID}
- wave_id: {SMOKE_WAVE_ID}
- status: ready
- phase: PHASE-GRACE-ORCHESTRATOR-PORTABLE-MVP

## Objective
Submit one controlled real Prefect E2E dry-run smoke packet. The packet is a
no-op scratch-only execution used to prove real Prefect runner submission and
worker execution without live agents.

## Allowed Write Scope
- scratch/grace-real-e2e-smoke/**

## Frozen Scope
- backend/**
- frontend/**
- prefect_grace/**
- .env
- docker-compose*.yml
- scripts/**
- tools/**

## Must Preserve
- No product backend or frontend code changes.
- No feature pipeline execution.
- No live agent execution.
- No merge, push, squash, commit, deployment mutation, accept, or worktree cleanup.

## Verification
Confirm that exactly one E2E Prefect flow run is created and reaches a
successful dry-run state, or report a timeout/error explicitly.

## Expected Evidence
- Prefect flow run id
- Prefect flow run URL
- Prefect deployment name
- Prefect state name and type
- Registry submission metadata

## Escalation Triggers
- More than one packet would be submitted
- Live agent execution requested
- Deployment name is not the E2E packet runner
- Write scope outside scratch/grace-real-e2e-smoke/**
"""


# START_FUNCTION_CONTRACT
# name: _smoke_project
# purpose: Build a project-like config using smoke state/worktree roots.
# inputs:
#   project: Loaded ProjectAdapterConfig.
#   state_root: Smoke runtime state root.
#   worktree_root: Smoke worktree root.
# returns: _SmokeProject suitable for native submission planning.
# side_effects: None.
# emitted_logs: None.
# error_behavior: None.
# END_FUNCTION_CONTRACT
def _smoke_project(project: ProjectAdapterConfig, *, state_root: Path, worktree_root: Path) -> _SmokeProject:
    return _SmokeProject(
        project_key=project.project_key,
        repo_root=project.repo_root,
        runtime_state_root=str(state_root),
        worktree_root=str(worktree_root),
        packets_dir=project.packets_dir,
    )


# START_FUNCTION_CONTRACT
# name: _normalize_state_type
# purpose: Normalize Prefect state type values from enums or strings.
# inputs:
#   value: Raw state type value.
# returns: Lowercase state type string, or None.
# side_effects: None.
# emitted_logs: None.
# error_behavior: None.
# END_FUNCTION_CONTRACT
def _normalize_state_type(value: Any) -> str | None:
    if value is None:
        return None
    raw = getattr(value, "value", value)
    text = str(raw).strip()
    if "." in text:
        text = text.rsplit(".", 1)[-1]
    return text.lower() or None


# START_FUNCTION_CONTRACT
# name: _extract_payload
# purpose: Extract JSON-like result payload from a Prefect state object when available.
# inputs:
#   state: Prefect state-like object.
# returns: dict payload or empty dict.
# side_effects: May call a local state.result method if present and non-async.
# emitted_logs: None.
# error_behavior: Best-effort; returns empty dict on extraction errors.
# END_FUNCTION_CONTRACT
def _extract_payload(state: Any) -> dict[str, Any]:
    candidates = [getattr(state, "data", None), getattr(state, "_result", None)]
    result_fn = getattr(state, "result", None)
    if callable(result_fn):
        try:
            candidates.append(result_fn(raise_on_failure=False, fetch=True))
        except TypeError:
            try:
                candidates.append(result_fn())
            except Exception:
                pass
        except Exception:
            pass
    for candidate in candidates:
        if isinstance(candidate, dict):
            return candidate
        value = getattr(candidate, "value", None)
        if isinstance(value, dict):
            return value
    return {}


# START_FUNCTION_CONTRACT
# name: _read_prefect_flow_run_status
# purpose: Read Prefect flow run state and best-effort E2E result metadata.
# inputs:
#   flow_run_id: Prefect flow run id.
# returns: dict with prefect_state_type, prefect_state_name, domain_status, artifact_ids.
# side_effects: Reads Prefect API.
# emitted_logs: None.
# error_behavior: Returns error field if Prefect client read fails.
# END_FUNCTION_CONTRACT
def _read_prefect_flow_run_status(flow_run_id: str) -> dict[str, Any]:
    try:
        get_client = importlib.import_module("prefect.client.orchestration").get_client
    except ImportError as e:
        return {"error": f"Prefect client unavailable: {e}"}

    async def _fetch() -> dict[str, Any]:
        async with get_client() as client:
            flow_run = await client.read_flow_run(flow_run_id)
            state = getattr(flow_run, "state", None)
            payload = _extract_payload(state)
            return {
                "prefect_state_type": _normalize_state_type(getattr(state, "type", None)),
                "prefect_state_name": str(getattr(state, "name", "") or "") or None,
                "domain_status": payload.get("domain_status") if isinstance(payload, dict) else None,
                "artifact_ids": list(payload.get("artifact_ids") or []) if isinstance(payload, dict) else [],
            }

    try:
        import asyncio
        return asyncio.run(_fetch())
    except Exception as e:
        return {"error": str(e)}


# START_FUNCTION_CONTRACT
# name: _wait_for_flow_run
# purpose: Poll Prefect status until success, terminal failure, or timeout.
# inputs:
#   flow_run_id: Prefect flow run id.
#   timeout_seconds: Maximum wait seconds.
#   poll_interval_seconds: Poll interval seconds.
#   status_reader: Status reader callable.
#   sleep_fn: Sleep callable.
# returns: tuple(status dict, errors list).
# side_effects: Sleeps and reads Prefect status.
# emitted_logs: None.
# error_behavior: Returns structured timeout/status errors.
# END_FUNCTION_CONTRACT
def _wait_for_flow_run(
    *,
    flow_run_id: str,
    timeout_seconds: int,
    poll_interval_seconds: int,
    status_reader: Callable[[str], dict[str, Any]],
    sleep_fn: Callable[[float], None],
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    deadline = time.monotonic() + max(timeout_seconds, 0)
    last_status: dict[str, Any] = {}
    while True:
        last_status = status_reader(flow_run_id)
        if last_status.get("error"):
            return last_status, [{
                "code": "PREFECT_STATUS_READ_FAILED",
                "message": str(last_status["error"]),
            }]

        state_type = _normalize_state_type(last_status.get("prefect_state_type"))
        domain_status = str(last_status.get("domain_status") or "").strip()
        if state_type in SUCCESS_STATE_TYPES or domain_status in SUCCESS_DOMAIN_STATUSES:
            return last_status, []
        if state_type in FAILURE_STATE_TYPES:
            return last_status, [{
                "code": "PREFECT_DRY_RUN_FAILED",
                "message": f"Prefect flow run reached {last_status.get('prefect_state_name') or state_type}.",
            }]
        if time.monotonic() >= deadline:
            return last_status, [{
                "code": "PREFECT_DRY_RUN_TIMEOUT",
                "message": f"Timed out waiting for Prefect flow run {flow_run_id}.",
            }]
        sleep_fn(max(min(poll_interval_seconds, max(deadline - time.monotonic(), 0)), 0))


#END_BLOCK_HELPERS
#START_BLOCK_SMOKE
# START_FUNCTION_CONTRACT
# name: run_prefect_e2e_real_dry_run_smoke
# purpose: Submit exactly one scratch-only E2E dry-run packet to real Prefect and optionally wait for status.
# inputs:
#   project_config: Path to project config.
#   state_root: Isolated smoke state root.
#   worktree_root: Isolated smoke worktree root.
#   packet_root: Directory for generated smoke packet.
#   timeout_seconds: Maximum wait seconds.
#   poll_interval_seconds: Wait poll interval seconds.
#   wait: Whether to wait for Prefect terminal/successful state.
#   execute_agent: Must remain False.
#   submitter: Optional test hook; default is real E2EPacketSubmitter.
#   status_reader: Optional test hook; default reads real Prefect client.
#   sleep_fn: Optional test hook for wait sleeps.
# returns: PrefectE2ERealDryRunSmokeResult.
# side_effects: Writes smoke packet/registry state and may submit one Prefect flow run.
# emitted_logs: None.
# error_behavior: Returns structured errors instead of raising for operator blocks.
# END_FUNCTION_CONTRACT
def run_prefect_e2e_real_dry_run_smoke(
    *,
    project_config: Path,
    state_root: Path,
    worktree_root: Path,
    packet_root: Path,
    timeout_seconds: int = 900,
    poll_interval_seconds: int = 5,
    wait: bool = True,
    execute_agent: bool = False,
    submitter: Callable[..., dict[str, Any]] | None = None,
    status_reader: Callable[[str], dict[str, Any]] | None = None,
    sleep_fn: Callable[[float], None] | None = None,
) -> PrefectE2ERealDryRunSmokeResult:
    if execute_agent:
        return _result(
            ok=False,
            errors=[{
                "code": "REAL_DRY_RUN_EXECUTE_AGENT_REJECTED",
                "message": "Real E2E dry-run smoke forbids live agent execution.",
            }],
        )

    project = load_project_adapter(project_config)
    smoke_project = _smoke_project(project, state_root=state_root, worktree_root=worktree_root)

    packet_dir = Path(packet_root) / SMOKE_FEATURE_ID
    packet_dir.mkdir(parents=True, exist_ok=True)
    packet_path = packet_dir / "EXECUTION_PACKET.md"
    packet_path.write_text(_build_smoke_packet_content(), encoding="utf-8")
    parsed = parse_packet_markdown(packet_path, mode="strict")

    registry = PacketRegistryStore(Path(state_root) / "state")
    registry.upsert_packet({
        "packet_id": parsed.packet_id,
        "project_key": project.project_key,
        "feature_id": parsed.feature_id,
        "wave_id": parsed.wave_id,
        "title": parsed.title,
        "path": str(packet_path),
        "source_hash": parsed.source_hash,
        "registry_status": "ready",
        "registry_reason": "prefect_e2e_real_dry_run_smoke",
        "depends_on": [],
    })

    plan = BacklogController.plan_submission(smoke_project)
    if plan.errors:
        return _result(
            ok=False,
            errors=[{"code": "SUBMISSION_PLAN_ERROR", "message": message} for message in plan.errors],
        )
    if plan.packets_to_submit != [SMOKE_PACKET_ID] or plan.submission_order != [SMOKE_PACKET_ID]:
        return _result(
            ok=False,
            errors=[{
                "code": "REAL_DRY_RUN_PACKET_COUNT_INVALID",
                "message": f"Expected only {SMOKE_PACKET_ID} to be submitted; got {plan.packets_to_submit}.",
            }],
        )

    if submitter is None:
        from prefect_grace.platform.runtime_adapter import E2EPacketSubmitter
        submitter = E2EPacketSubmitter()

    submission_result = submit_ready_packets_to_prefect(
        project=smoke_project,
        dry_run=False,
        limit=1,
        execute_agent=False,
        timeout_seconds=timeout_seconds,
        base_ref="HEAD",
        worktree_root=worktree_root,
        scheduled_for=None,
        continue_on_error=False,
        submitter=submitter,
        runner_kind="e2e",
    )
    if submission_result.errors or len(submission_result.records) != 1:
        errors = list(submission_result.errors)
        if len(submission_result.records) != 1:
            errors.append({
                "code": "REAL_DRY_RUN_SUBMISSION_COUNT_INVALID",
                "message": f"Expected one submission record; got {len(submission_result.records)}.",
            })
        return _result(ok=False, errors=errors)

    record = submission_result.records[0]
    if record.deployment_name != E2E_PACKET_DEPLOYMENT_NAME:
        return _result(
            ok=False,
            submitted=record.status == "submitted",
            work_queue_name=record.work_queue_name,
            flow_run_id=record.flow_run_id,
            flow_run_name=record.flow_run_name,
            flow_run_url=record.url,
            errors=[{
                "code": "UNEXPECTED_E2E_DEPLOYMENT",
                "message": f"Expected {E2E_PACKET_DEPLOYMENT_NAME}; got {record.deployment_name}.",
            }],
        )
    if not record.flow_run_id:
        return _result(
            ok=False,
            submitted=False,
            work_queue_name=record.work_queue_name,
            flow_run_name=record.flow_run_name,
            flow_run_url=record.url,
            errors=[{"code": "MISSING_PREFECT_FLOW_RUN_ID", "message": "Native submission did not return a flow run id."}],
        )

    if not wait:
        return _result(
            ok=record.status == "submitted",
            submitted=record.status == "submitted",
            waited=False,
            work_queue_name=record.work_queue_name,
            flow_run_id=record.flow_run_id,
            flow_run_name=record.flow_run_name,
            flow_run_url=record.url,
            errors=[] if record.status == "submitted" else [{
                "code": "SUBMISSION_NOT_SUBMITTED",
                "message": record.error or record.status,
            }],
        )

    reader = status_reader or _read_prefect_flow_run_status
    sleeper = sleep_fn or time.sleep
    status, wait_errors = _wait_for_flow_run(
        flow_run_id=record.flow_run_id,
        timeout_seconds=timeout_seconds,
        poll_interval_seconds=poll_interval_seconds,
        status_reader=reader,
        sleep_fn=sleeper,
    )
    state_type = _normalize_state_type(status.get("prefect_state_type"))
    domain_status = status.get("domain_status")
    artifact_ids = list(status.get("artifact_ids") or [])
    ok = not wait_errors and (
        state_type in SUCCESS_STATE_TYPES or str(domain_status or "") in SUCCESS_DOMAIN_STATUSES
    )
    return _result(
        ok=ok,
        submitted=True,
        waited=True,
        work_queue_name=record.work_queue_name,
        flow_run_id=record.flow_run_id,
        flow_run_name=record.flow_run_name,
        flow_run_url=record.url,
        prefect_state_type=state_type,
        prefect_state_name=status.get("prefect_state_name"),
        domain_status=domain_status or "unknown",
        artifact_ids=artifact_ids,
        errors=wait_errors,
    )


#END_BLOCK_SMOKE
