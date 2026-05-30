# ############################################################################
# AI_HEADER: single_astro_packet_pilot
# ROLE: Guarded one-packet Astro pilot for real product packets.
# ############################################################################

# START_MODULE_CONTRACT
# purpose: Plan or run one low-risk real Astro packet through the managed Prefect packet runner.
# inputs: Project config path, explicit temp roots, live-agent gates, and optional test hooks.
# returns: SingleAstroPacketPilotResult with bounded submission and scope evidence.
# side_effects: May submit one Prefect flow run after all gates; no Git mutation.
# emitted_logs: structured execution_trace.jsonl for selected packet attempts.
# error_behavior: Returns structured errors for gate, planning, submission, status, and scope failures.
# END_MODULE_CONTRACT

# START_MODULE_MAP
# mapping:
#   - class: SingleAstroPacketPilotResult
#   - function: run_single_astro_packet_pilot
#   - function: _is_low_risk_candidate
# END_MODULE_MAP

from __future__ import annotations

from dataclasses import asdict, dataclass, field
import os
from pathlib import Path
from typing import Any, Callable

from prefect_grace.platform.live_opt_in_single_scratch_packet import (
    _load_registry_map,
    _paths_outside_roots,
    _validate_roots,
)
from prefect_grace.platform.prefect_native_submission import submit_ready_packets_to_prefect
from prefect_grace.platform.packet_parser import parse_packet_markdown
from prefect_grace.platform.project_adapter import load_project_adapter
from prefect_grace.platform.scope_guard import validate_scope
from prefect_grace.platform.single_live_prefect_packet_pilot import create_bounded_prefect_status_reader
from prefect_grace.platform.state_store import PacketRegistryStore
from prefect_grace.platform.structured_logger import log_event
from prefect_grace.platform.trace_context import create_trace_context
from prefect_grace.tasks.prefect_submitter import MANAGED_PACKET_DEPLOYMENT_NAME

MODE = "single_astro_packet_pilot"
FEATURE_ID = "FEAT-GRACE-SINGLE-ASTRO-PACKET-PILOT"
WAVE_ID = "W01"
OPT_IN_TOKEN = "single-astro-packet"


@dataclass
class SingleAstroPacketPilotResult:
    """Result from single Astro packet pilot."""

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
    warnings: list[dict[str, str]] = field(default_factory=list)
    errors: list[dict[str, str]] = field(default_factory=list)
    bootstrap_apply_count: int = 0
    sync_plan: dict[str, Any] = field(default_factory=dict)

    # START_FUNCTION_CONTRACT
    # name: to_dict
    # purpose: Serialize pilot result to a JSON-safe dictionary.
    # inputs:
    #   self: SingleAstroPacketPilotResult instance.
    # returns: dict[str, Any] with bounded result fields.
    # side_effects: None.
    # emitted_logs: None.
    # error_behavior: None.
    # END_FUNCTION_CONTRACT
    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["registry_before"] = _ensure_registry_summary(self.registry_before, self.selected_packet_id)
        data["registry_after"] = _ensure_registry_summary(self.registry_after, self.selected_packet_id)
        data["submit_plan"] = _bounded_submit_plan(self.submit_plan)
        data["plan_count"] = _plan_count(self.submit_plan)
        return data


def _error(code: str, message: str, **extra: Any) -> dict[str, Any]:
    return {"code": code, "message": message, **extra}


def _packet_status(packet: dict[str, Any]) -> str:
    return str(packet.get("registry_status") or packet.get("status") or "unknown")


def _selected_packet_summary(
    registry: dict[str, Any],
    selected_packet_id: str | None,
) -> dict[str, Any] | None:
    if not selected_packet_id:
        return None

    packet = registry.get(selected_packet_id)
    if not isinstance(packet, dict):
        return {"packet_id": selected_packet_id, "found": False}

    allowed_scope = packet.get("allowed_write_scope") or []
    return {
        "packet_id": selected_packet_id,
        "found": True,
        "status": _packet_status(packet),
        "source_hash": packet.get("source_hash"),
        "path": packet.get("path"),
        "allowed_scope_count": len(allowed_scope) if isinstance(allowed_scope, list) else 0,
    }


def _registry_summary(
    registry: dict[str, Any],
    selected_packet_id: str | None,
) -> dict[str, Any]:
    status_counts: dict[str, int] = {}
    for packet in registry.values():
        if not isinstance(packet, dict):
            status = "unknown"
        else:
            status = _packet_status(packet)
        status_counts[status] = status_counts.get(status, 0) + 1

    return {
        "total_packets": len(registry),
        "status_counts": dict(sorted(status_counts.items())),
        "selected_packet": _selected_packet_summary(registry, selected_packet_id),
        "records_included": False,
    }


def _is_registry_summary(value: dict[str, Any]) -> bool:
    return (
        "total_packets" in value
        and "status_counts" in value
        and "selected_packet" in value
        and value.get("records_included") is False
    )


def _ensure_registry_summary(
    registry: dict[str, Any],
    selected_packet_id: str | None,
) -> dict[str, Any]:
    if _is_registry_summary(registry):
        return dict(registry)
    return _registry_summary(registry, selected_packet_id)


def _plan_count(submit_plan: dict[str, Any]) -> int:
    planned = submit_plan.get("packets_planned") or submit_plan.get("packets_to_submit") or []
    return len(planned) if isinstance(planned, list) else 0


def _bounded_submit_plan(submit_plan: dict[str, Any]) -> dict[str, Any]:
    bounded = dict(submit_plan)
    records = bounded.get("records")
    if isinstance(records, list):
        bounded["records_count"] = len(records)
        bounded["records"] = records[:1]
    bounded["plan_count"] = _plan_count(submit_plan)
    return bounded


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
    warnings: list[dict[str, str]] | None = None,
    selected_packet_id: str | None = None,
    registry_before: dict[str, Any] | None = None,
) -> SingleAstroPacketPilotResult:
    return SingleAstroPacketPilotResult(
        ok=ok,
        project_key=project_key,
        mode=MODE,
        dry_run=dry_run,
        opt_in_confirmed=opt_in_confirmed,
        state_root=str(state_root),
        worktree_root=str(worktree_root),
        packet_root=str(packet_root),
        selected_packet_id=selected_packet_id,
        registry_before=_registry_summary(registry_before or {}, selected_packet_id),
        registry_after=_registry_summary(registry_before or {}, selected_packet_id),
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


def _result_dict(value: Any) -> dict[str, Any]:
    if hasattr(value, "to_dict"):
        converted = value.to_dict()
        return converted if isinstance(converted, dict) else {}
    if hasattr(value, "__dataclass_fields__"):
        return asdict(value)
    if isinstance(value, dict):
        return dict(value)
    return {}


def _submission_record_fields(record: Any) -> dict[str, Any]:
    if hasattr(record, "to_dict"):
        converted = record.to_dict()
        return converted if isinstance(converted, dict) else {}
    if hasattr(record, "__dataclass_fields__"):
        return asdict(record)
    if isinstance(record, dict):
        return dict(record)
    return dict(record)


def _packet_contract_fields(adapter: Any, record: dict[str, Any]) -> dict[str, Any]:
    path_value = record.get("path")
    if not path_value:
        return {"strict_packet_contract_ok": False}

    packet_path = Path(path_value)
    if not packet_path.is_absolute():
        packet_path = Path(adapter.repo_root) / packet_path

    try:
        parsed = parse_packet_markdown(packet_path, mode="strict")
    except Exception as exc:
        return {
            "strict_packet_contract_ok": False,
            "strict_packet_contract_error": str(exc),
        }

    return {
        "packet_id": parsed.packet_id,
        "feature_id": parsed.feature_id,
        "wave_id": parsed.wave_id,
        "status": parsed.status,
        "allowed_write_scope": parsed.allowed_write_scope,
        "frozen_scope": parsed.frozen_scope,
        "source_hash": parsed.source_hash,
        "strict_packet_contract_ok": True,
    }


def _load_project_registry_map(adapter: Any, state_root: Path) -> dict[str, Any]:
    registry_map = _load_registry_map(state_root)
    if not registry_map:
        registry_map = _load_registry_map(Path(adapter.runtime_state_root))

    enriched: dict[str, Any] = {}
    for packet_id, record in registry_map.items():
        packet = dict(record or {})
        packet.setdefault("packet_id", packet_id)
        contract_fields = _packet_contract_fields(adapter, packet)
        for key, value in contract_fields.items():
            if value or key not in packet:
                packet[key] = value
        enriched[packet_id] = packet
    return enriched


def _candidate_gate(packet: dict[str, Any]) -> tuple[bool, str | None]:
    if not packet.get("source_hash"):
        return False, f"Packet {packet.get('packet_id', '')} is missing source_hash"
    if packet.get("strict_packet_contract_ok") is False:
        return False, f"Packet {packet.get('packet_id', '')} is missing strict packet contract"
    review_status = str(packet.get("latest_review_status") or packet.get("review_status") or "").lower()
    if review_status in {"blocked", "rework_required"}:
        return False, f"Packet {packet.get('packet_id', '')} has existing blocked review: {review_status}"
    return _is_low_risk_candidate(packet)


def _write_selected_registry(
    *,
    state_root: Path,
    selected_packet_id: str,
    selected_packet: dict[str, Any],
) -> Path:
    submission_root = state_root / "single_astro_submission"
    registry = PacketRegistryStore(submission_root / "state")
    registry.upsert_packet(
        {
            **selected_packet,
            "packet_id": selected_packet_id,
            "registry_status": "ready",
        }
    )
    return submission_root


# START_FUNCTION_CONTRACT
# name: _is_low_risk_candidate
# purpose: Check if packet is a low-risk candidate for first Astro pilot.
# inputs: packet (dict[str, Any]) - Packet record with status and allowed_write_scope.
# returns: tuple[bool, str | None] - (is_low_risk, rejection_reason).
# side_effects: None.
# emitted_logs: None.
# error_behavior: Returns (False, reason_string) for any rejection condition.
# END_FUNCTION_CONTRACT
def _is_low_risk_candidate(packet: dict[str, Any]) -> tuple[bool, str | None]:
    """Check if packet is a low-risk candidate for first Astro pilot.

    Returns (is_low_risk, rejection_reason).
    """
    packet_id = packet.get("packet_id", "")
    status = packet.get("registry_status") or packet.get("status", "")
    allowed_scope = packet.get("allowed_write_scope", [])

    # Must be ready
    if status not in {"ready", "ready_for_retry"}:
        return False, f"Packet {packet_id} status is {status}, not ready"

    # Must have allowed scope
    if not allowed_scope:
        return False, f"Packet {packet_id} has no allowed_write_scope"

    # Reject if scope is too broad (heuristic: more than 20 paths or includes backend/frontend root)
    if len(allowed_scope) > 20:
        return False, f"Packet {packet_id} has broad scope ({len(allowed_scope)} paths)"

    # Check for risky patterns
    for scope_path in allowed_scope:
        scope_lower = scope_path.lower()
        if scope_lower.startswith("/opt/astro-project/backend") and "**" in scope_path:
            return False, f"Packet {packet_id} has broad backend scope: {scope_path}"
        if scope_lower.startswith("/opt/astro-project/frontend") and "**" in scope_path:
            return False, f"Packet {packet_id} has broad frontend scope: {scope_path}"
        if "/scripts/pipeline.py" in scope_lower:
            return False, f"Packet {packet_id} modifies pipeline.py"
        if "docker-compose" in scope_lower:
            return False, f"Packet {packet_id} modifies Docker compose"

    return True, None


# START_FUNCTION_CONTRACT
# name: run_single_astro_packet_pilot
# purpose: Plan or run one low-risk real Astro packet through managed Prefect runner.
# inputs: project_path (Path), state/worktree/packet roots (Path), dry_run (bool), execute_agent (bool), acknowledge_live_agent (bool), opt_in_token (str|None), timeout_seconds (int), packet_id (str|None), submitter (Callable|None), status_reader (Callable|None), trace_context (optional).
# returns: SingleAstroPacketPilotResult with bounded submission and scope evidence.
# side_effects: May submit one Prefect flow run after all gates; no Git mutation.
# emitted_logs: structured execution_trace.jsonl for selected packet attempts.
# error_behavior: Returns structured errors for gate, planning, submission, status, and scope failures.
# END_FUNCTION_CONTRACT
def run_single_astro_packet_pilot(
    project_path: str | Path,
    state_root: str | Path,
    worktree_root: str | Path,
    packet_root: str | Path,
    dry_run: bool = True,
    execute_agent: bool = False,
    acknowledge_live_agent: bool = False,
    opt_in_token: str | None = None,
    timeout_seconds: int = 300,
    packet_id: str | None = None,
    submitter: Callable | None = None,
    status_reader: Callable | None = None,
    trace_context: Any | None = None,
) -> SingleAstroPacketPilotResult:
    """Run single Astro packet pilot.

    Args:
        project_path: Path to project.yaml
        state_root: Root for state files
        worktree_root: Root for worktrees
        packet_root: Root for packet files
        dry_run: If True, plan only without submission
        execute_agent: If True, allow agent execution
        acknowledge_live_agent: If True, acknowledge live agent risk
        opt_in_token: Required token for live execution
        timeout_seconds: Timeout for status polling
        packet_id: Explicit packet ID to run (optional)
        submitter: Test hook for Prefect submission
        status_reader: Test hook for status reading
        trace_context: Optional structured logging context

    Returns:
        SingleAstroPacketPilotResult with bounded evidence
    """
    project_path = Path(project_path)
    state_root = Path(state_root)
    worktree_root = Path(worktree_root)
    packet_root = Path(packet_root)
    errors: list[dict[str, Any]] = []
    warnings: list[dict[str, str]] = []
    active_trace_context = trace_context

    def _log(event: str, result: str = "ok", **extra: Any) -> None:
        log_event(
            active_trace_context,
            module="M-GRACE-SINGLE-ASTRO-PACKET-PILOT",
            fn="run_single_astro_packet_pilot",
            block="SINGLE_ASTRO_PILOT",
            event=event,
            result=result,
            **extra,
        )

    try:
        base_adapter = load_project_adapter(project_path)
        repo_root = Path(base_adapter.repo_root)
        adapter = load_project_adapter(
            project_path,
            overrides={
                "runtime_state_root": str(state_root),
                "artifact_root": str(state_root / "artifacts"),
                "worktree_root": str(worktree_root),
            },
        )
        project_key = adapter.project_key
    except Exception as exc:
        return _empty_result(
            ok=False,
            project_key="",
            dry_run=dry_run,
            opt_in_confirmed=False,
            state_root=state_root,
            worktree_root=worktree_root,
            packet_root=packet_root,
            errors=[_error("PROJECT_LOAD_FAILED", str(exc))],
        )

    root_validation_errors = _validate_roots(
        state_root=state_root,
        worktree_root=worktree_root,
        packet_root=packet_root,
        repo_root=repo_root,
    )
    if root_validation_errors:
        return _empty_result(
            ok=False,
            project_key=project_key,
            dry_run=dry_run,
            opt_in_confirmed=False,
            state_root=state_root,
            worktree_root=worktree_root,
            packet_root=packet_root,
            errors=root_validation_errors,
        )

    token = opt_in_token if opt_in_token is not None else os.environ.get("GRACE_ASTRO_PACKET_OPT_IN")
    opt_in_confirmed = True
    if not dry_run:
        if not execute_agent:
            errors.append(_error("LIVE_AGENT_EXECUTE_REQUIRED", "--execute-agent is required for live Astro packet execution."))
            opt_in_confirmed = False
        if not acknowledge_live_agent:
            errors.append(_error("LIVE_AGENT_NOT_ACKNOWLEDGED", "Live agent execution requires --i-understand-live-agent."))
            opt_in_confirmed = False
        if token != OPT_IN_TOKEN:
            errors.append(_error("OPT_IN_TOKEN_MISMATCH", f"Required Astro packet opt-in token is {OPT_IN_TOKEN}."))
            opt_in_confirmed = False

    if not opt_in_confirmed:
        return _empty_result(
            ok=False,
            project_key=project_key,
            dry_run=dry_run,
            opt_in_confirmed=False,
            state_root=state_root,
            worktree_root=worktree_root,
            packet_root=packet_root,
            errors=errors,
        )

    try:
        registry_map = _load_project_registry_map(base_adapter, state_root)
    except Exception as exc:
        return _empty_result(
            ok=False,
            project_key=project_key,
            dry_run=dry_run,
            opt_in_confirmed=opt_in_confirmed,
            state_root=state_root,
            worktree_root=worktree_root,
            packet_root=packet_root,
            errors=[_error("REGISTRY_LOAD_FAILED", str(exc))],
        )

    registry_before = {packet_key: dict(packet_value) for packet_key, packet_value in registry_map.items()}

    selected_packet_id = None
    selected_packet: dict[str, Any] | None = None
    if packet_id:
        selected_packet = registry_map.get(packet_id)
        if selected_packet is None:
            return _empty_result(
                ok=False,
                project_key=project_key,
                dry_run=dry_run,
                opt_in_confirmed=opt_in_confirmed,
                state_root=state_root,
                worktree_root=worktree_root,
                packet_root=packet_root,
                errors=[_error("PACKET_NOT_FOUND", f"Packet {packet_id} not in registry")],
                selected_packet_id=packet_id,
                registry_before=registry_before,
            )
        ok_candidate, rejection_reason = _candidate_gate(selected_packet)
        if not ok_candidate:
            return _empty_result(
                ok=False,
                project_key=project_key,
                dry_run=dry_run,
                opt_in_confirmed=opt_in_confirmed,
                state_root=state_root,
                worktree_root=worktree_root,
                packet_root=packet_root,
                errors=[_error("PACKET_NOT_LOW_RISK", rejection_reason or "Packet is not a low-risk candidate.")],
                selected_packet_id=packet_id,
                registry_before=registry_before,
            )
        selected_packet_id = packet_id
    else:
        for candidate_id, candidate in registry_map.items():
            ok_candidate, _ = _candidate_gate(candidate)
            if ok_candidate:
                selected_packet_id = candidate_id
                selected_packet = candidate
                break

    if selected_packet_id is None or selected_packet is None:
        return _empty_result(
            ok=False,
            project_key=project_key,
            dry_run=dry_run,
            opt_in_confirmed=opt_in_confirmed,
            state_root=state_root,
            worktree_root=worktree_root,
            packet_root=packet_root,
            errors=[_error("NO_LOW_RISK_CANDIDATE", "No low-risk ready packets found in registry.")],
            registry_before=registry_before,
        )

    if active_trace_context is None:
        active_trace_context = create_trace_context(
            packet_id=selected_packet_id,
            attempt=1,
            scenario_id="SCN-SINGLE-ASTRO-PILOT",
            artifact_root=state_root / "artifacts",
        )
    _log("candidate_selection_started", "ok", explicit_packet=bool(packet_id))
    _log("candidate_selected", "ok", selected_packet_id=selected_packet_id)

    submission_state_root = _write_selected_registry(
        state_root=state_root,
        selected_packet_id=selected_packet_id,
        selected_packet=selected_packet,
    )
    submission_adapter = load_project_adapter(
        project_path,
        overrides={
            "runtime_state_root": str(submission_state_root),
            "artifact_root": str(submission_state_root / "artifacts"),
            "worktree_root": str(worktree_root),
        },
    )

    try:
        dry_submit = submit_ready_packets_to_prefect(
            project=submission_adapter,
            dry_run=True,
            limit=1,
            execute_agent=execute_agent,
            timeout_seconds=timeout_seconds,
            worktree_root=worktree_root,
            submitter=None,
            runner_kind="managed",
            trace_context=active_trace_context,
        )
    except Exception as exc:
        _log("submission_planned", "fail", error=str(exc))
        return _empty_result(
            ok=False,
            project_key=project_key,
            dry_run=dry_run,
            opt_in_confirmed=opt_in_confirmed,
            state_root=state_root,
            worktree_root=worktree_root,
            packet_root=packet_root,
            errors=[_error("SUBMISSION_PLAN_FAILED", str(exc))],
            selected_packet_id=selected_packet_id,
            registry_before=registry_before,
        )

    submit_plan_dict = dry_submit.to_dict()
    submit_plan_dict["packets_to_submit"] = list(dry_submit.packets_planned)
    _log(
        "submission_planned",
        "ok" if dry_submit.ok else "fail",
        packets_planned=list(dry_submit.packets_planned),
        error_count=len(dry_submit.errors),
    )
    errors.extend(dry_submit.errors)
    warnings.extend(_error("SUBMISSION_PLAN_WARNING", warning) for warning in dry_submit.warnings)

    if dry_submit.packets_planned != [selected_packet_id]:
        errors.append(
            _error(
                "ASTRO_PACKET_COUNT_INVALID",
                "Managed Prefect dry-run plan must select exactly the selected Astro packet.",
                packets_planned=list(dry_submit.packets_planned),
            )
        )

    flow_run_id = None
    flow_run_name = None
    flow_run_url = None
    deployment_name = MANAGED_PACKET_DEPLOYMENT_NAME
    work_queue_name = None
    prefect_runs_created = 0

    if dry_submit.records:
        record_data = _submission_record_fields(dry_submit.records[0])
        deployment_name = record_data.get("deployment_name")
        work_queue_name = record_data.get("work_queue_name")
        flow_run_name = record_data.get("flow_run_name")

    submit_result = dry_submit
    if not dry_run and not errors:
        if submitter is None:
            from prefect_grace.platform.runtime_adapter import ManagedPacketSubmitter
            submitter = ManagedPacketSubmitter()
        try:
            _log("prefect_submitted", "ok", dry_run=False, submission_started=True)
            submit_result = submit_ready_packets_to_prefect(
                project=submission_adapter,
                dry_run=False,
                limit=1,
                execute_agent=execute_agent,
                timeout_seconds=timeout_seconds,
                worktree_root=worktree_root,
                submitter=submitter,
                runner_kind="managed",
                trace_context=active_trace_context,
            )
        except Exception as exc:
            _log("prefect_submitted", "fail", error=str(exc))
            errors.append(_error("SUBMISSION_FAILED", str(exc)))
        else:
            errors.extend(submit_result.errors)
            submit_plan_dict = submit_result.to_dict()
            submit_plan_dict["packets_to_submit"] = list(submit_result.packets_planned)
            if len(submit_result.records) != 1:
                errors.append(_error("ASTRO_SUBMISSION_COUNT_INVALID", f"Expected one submission record; got {len(submit_result.records)}."))
            elif not submit_result.errors:
                record_data = _submission_record_fields(submit_result.records[0])
                deployment_name = record_data.get("deployment_name")
                work_queue_name = record_data.get("work_queue_name")
                flow_run_id = record_data.get("flow_run_id")
                flow_run_name = record_data.get("flow_run_name")
                flow_run_url = record_data.get("url")
                if record_data.get("packet_id") != selected_packet_id:
                    errors.append(_error("ASTRO_WRONG_PACKET_SUBMITTED", f"Expected {selected_packet_id}; got {record_data.get('packet_id')}."))
                if record_data.get("deployment_name") != MANAGED_PACKET_DEPLOYMENT_NAME:
                    errors.append(_error("ASTRO_UNEXPECTED_DEPLOYMENT", f"Expected {MANAGED_PACKET_DEPLOYMENT_NAME}; got {record_data.get('deployment_name')}."))
                if record_data.get("status") != "submitted":
                    errors.append(_error("ASTRO_NOT_SUBMITTED", record_data.get("error") or record_data.get("status") or "not submitted"))
                if flow_run_id and record_data.get("status") == "submitted":
                    prefect_runs_created = 1
                _log(
                    "prefect_submitted",
                    "ok" if prefect_runs_created == 1 else "fail",
                    flow_run_id=flow_run_id,
                    flow_run_name=flow_run_name,
                    status=record_data.get("status"),
                )

    domain_status = None
    scope_verdict = None
    changed_files: list[str] = []
    poll_events: list[dict[str, Any]] = []
    live_agents_started = 0

    if not dry_run and execute_agent and flow_run_id:
        try:
            reader = status_reader or create_bounded_prefect_status_reader(None)
            _log("status_poll_started", "ok", flow_run_id=flow_run_id)
            status_result = _result_dict(
                reader(
                    flow_run_id=flow_run_id,
                    packet_id=selected_packet_id,
                    timeout_seconds=timeout_seconds,
                )
            )
            domain_status = status_result.get("domain_status")
            scope_verdict = status_result.get("scope_verdict")
            changed_files = list(status_result.get("changed_files") or [])
            poll_events = list(status_result.get("poll_events") or [])
            live_agents_started = int(status_result.get("live_agents_started") or status_result.get("agent_launch_count") or 0)
            errors.extend(list(status_result.get("errors") or []))
            if not status_result.get("ok", False):
                errors.append(_error("ASTRO_STATUS_NOT_OK", "Managed Prefect status reader did not return ok=true."))
            _log(
                "status_received",
                "ok" if status_result.get("ok", False) else "fail",
                domain_status=domain_status,
                scope_verdict=scope_verdict,
                poll_event_count=len(poll_events),
            )
        except Exception as exc:
            errors.append(_error("STATUS_READ_FAILED", str(exc)))
            scope_verdict = "status_read_failed"
            _log("status_received", "fail", error=str(exc))

    if changed_files:
        scope_result = validate_scope(
            changed_files,
            list(selected_packet.get("allowed_write_scope") or []),
            list(selected_packet.get("frozen_scope") or []),
            repo_root=repo_root,
            trace_context=active_trace_context,
        )
        _log(
            "scope_validated",
            "ok" if scope_result.ok else "fail",
            changed_file_count=len(changed_files),
            outside_allowed_count=len(scope_result.outside_allowed),
            frozen_violation_count=len(scope_result.frozen_violations),
        )
        if not scope_result.ok:
            if domain_status is None:
                domain_status = "scope_blocked"
            if scope_verdict is None or scope_verdict == "passed":
                scope_verdict = "blocked"
            errors.append(
                _error(
                    "ASTRO_CHANGED_FILES_OUTSIDE_ALLOWED_SCOPE",
                    "Managed Prefect pilot changed files outside the selected packet scope.",
                    scope_result=scope_result.to_dict(),
                )
            )

    touched_paths = [
        state_root / "single_astro_submission" / "state" / "packet_registry.yaml",
        worktree_root,
        packet_root,
    ]
    writes_outside_temp_roots = _paths_outside_roots(touched_paths, [state_root, worktree_root, packet_root])
    if writes_outside_temp_roots:
        errors.append(_error("WRITE_OUTSIDE_TEMP_ROOTS", "Pilot detected writes outside temp roots."))

    registry_after = _load_project_registry_map(base_adapter, state_root)
    final_ok = (
        not errors
        and submit_result.ok
        and dry_submit.packets_planned == [selected_packet_id]
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
    _log(
        "domain_status_determined",
        "ok" if final_ok else "fail",
        domain_status=domain_status,
        scope_verdict=scope_verdict,
        error_count=len(errors),
    )
    if active_trace_context is not None:
        try:
            active_trace_context.flush()
        except Exception:
            pass

    return SingleAstroPacketPilotResult(
        ok=final_ok,
        project_key=project_key,
        mode=MODE,
        dry_run=dry_run,
        opt_in_confirmed=opt_in_confirmed,
        state_root=str(state_root),
        worktree_root=str(worktree_root),
        packet_root=str(packet_root),
        selected_packet_id=selected_packet_id,
        registry_before=_registry_summary(registry_before, selected_packet_id),
        registry_after=_registry_summary(registry_after, selected_packet_id),
        submit_plan=submit_plan_dict,
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
    )
