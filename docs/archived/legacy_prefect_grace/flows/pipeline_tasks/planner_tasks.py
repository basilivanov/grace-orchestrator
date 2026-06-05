# ############################################################################
# AI_HEADER: pipeline_tasks.planner_tasks
# ROLE: Planner contract Prefect tasks and pure planner helpers for feature_pipeline.
# ############################################################################

# START_MODULE_CONTRACT
# purpose: Resolve, materialize, and validate planner packet contracts for feature_pipeline.
# inputs: Planner run payloads, planner overrides, feature metadata, verifier settings, and generated packet graphs.
# returns: Planner contract results, materialized packet graphs, validation results, and pure planner helper values.
# side_effects: Materializes packet records through existing planner_contract APIs; validation is read-only.
# emitted_logs: Prefect task logs.
# error_behavior: Preserves existing fallback behavior and validation issue collection.
# END_MODULE_CONTRACT

# START_MODULE_MAP
# mapping:
#   - function: load_architect_manifest
#   - function: architect_wave_contract
#   - function: should_run_planner
#   - function: architect_plan_next_action
#   - function: architect_packet_candidates_to_contract
#   - function: resolve_planner_contract_task
#   - function: materialize_planner_contract_task
#   - function: validate_planner_contract_task
# END_MODULE_MAP

from __future__ import annotations

import json
from pathlib import Path

from prefect_grace.flows.pipeline_helpers.normalizers import normalize_observability_scope
from prefect_grace.flows.pipeline_helpers.rework_routing import (
    packet_execution_contract,
    string_command_list,
    uses_today_week_observability,
)
from prefect_grace.prefect_compat import get_run_logger, task
from prefect_grace.tasks.agent_output_parser import (
    parse_planner_wave_plan_message,
    read_agent_message,
)
from prefect_grace.tasks.planner_contract import (
    default_wave_plan_contract,
    materialize_planner_contract,
    normalize_wave_plan_contract,
)
from prefect_grace.tasks.state_store import find_record
from prefect_grace.tasks.wave_executor import packet_map


# START_FUNCTION_CONTRACT
# name: load_architect_manifest
# purpose: Load a feature's architect manifest from its recorded path.
# inputs:
#   feature_id: Feature identifier.
# returns: Architect manifest dictionary or empty dictionary.
# side_effects: Reads feature state and optional manifest file.
# emitted_logs: None.
# error_behavior: Missing feature/path/file or invalid JSON returns empty dictionary.
# END_FUNCTION_CONTRACT
def load_architect_manifest(feature_id: str) -> dict:
    try:
        feature = find_record("features", "features", "feature_id", feature_id)
    except KeyError:
        return {}
    manifest_path = str(feature.get("architect_manifest_path") or "").strip()
    if not manifest_path:
        return {}
    path = Path(manifest_path)
    if not path.exists():
        return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return payload if isinstance(payload, dict) else {}


# START_FUNCTION_CONTRACT
# name: architect_wave_contract
# purpose: Resolve the architect manifest wave contract for a wave id.
# inputs:
#   architect_manifest: Architect manifest dictionary.
#   wave_id: Wave identifier.
# returns: Matching wave dictionary or empty dictionary.
# side_effects: None.
# emitted_logs: None.
# error_behavior: Skips malformed optional wave records.
# END_FUNCTION_CONTRACT
def architect_wave_contract(architect_manifest: dict, wave_id: str) -> dict:
    target_wave_id = str(wave_id or "").strip().upper()
    for wave in architect_manifest.get("waves") or []:
        if not isinstance(wave, dict):
            continue
        if str(wave.get("wave_id") or "").strip().upper() == target_wave_id:
            return dict(wave)
    return {}


# START_FUNCTION_CONTRACT
# name: should_run_planner
# purpose: Resolve whether feature_pipeline should run the planner packet.
# inputs:
#   run_planner: Optional explicit planner flag.
#   planner_contract: Optional planner contract override.
# returns: Existing planner execution boolean.
# side_effects: None.
# emitted_logs: None.
# error_behavior: None.
# END_FUNCTION_CONTRACT
def should_run_planner(*, run_planner: bool | None, planner_contract: dict | None) -> bool:
    if run_planner is not None:
        return bool(run_planner)
    return False


# START_FUNCTION_CONTRACT
# name: architect_plan_next_action
# purpose: Normalize architect artifact next_action values.
# inputs:
#   payload: Optional architect artifact payload.
# returns: Existing next_action value or materialize_packets fallback.
# side_effects: None.
# emitted_logs: None.
# error_behavior: None.
# END_FUNCTION_CONTRACT
def architect_plan_next_action(payload: dict | None) -> str:
    action = str((payload or {}).get("next_action") or "materialize_packets").strip().lower().replace("-", "_")
    if action in {"materialize_packets", "requires_planner", "requires_user_decision"}:
        return action
    return "materialize_packets"


# START_FUNCTION_CONTRACT
# name: architect_packet_candidates_to_contract
# purpose: Convert architect packet_candidates payloads to a planner contract shape.
# inputs:
#   payload: Optional architect artifact payload.
# returns: Planner contract dictionary or None.
# side_effects: None.
# emitted_logs: None.
# error_behavior: Malformed optional payloads return None.
# END_FUNCTION_CONTRACT
def architect_packet_candidates_to_contract(payload: dict | None) -> dict | None:
    if not isinstance(payload, dict):
        return None
    raw_packets = payload.get("packet_candidates")
    if not isinstance(raw_packets, list) or not raw_packets:
        return None
    packets = [dict(packet) for packet in raw_packets if isinstance(packet, dict)]
    if not packets:
        return None
    raw_waves = payload.get("waves")
    waves = [dict(wave) for wave in raw_waves if isinstance(wave, dict)] if isinstance(raw_waves, list) else []
    return {"waves": waves, "packets": packets}


# START_FUNCTION_CONTRACT
# name: resolve_planner_contract_task
# purpose: Resolve the planner packet graph contract from agent output, explicit override, or fallback defaults.
# inputs: Planner run payload, packet ids, feature metadata, verifier settings, override contract, and parse preference.
# returns: Dict with contract, source, and parser_error.
# side_effects: Reads planner agent output when requested.
# emitted_logs: Prefect task log line.
# error_behavior: Falls back to explicit/default contract when agent output is unavailable or invalid.
# END_FUNCTION_CONTRACT
@task(task_run_name="packet-graph:resolve")
def resolve_planner_contract_task(
    planner_run: dict,
    *,
    planner_packet_id: str,
    architect_packet_id: str,
    feature_id: str,
    implementation_title: str,
    implementation_summary: str,
    verifier_backend_profile: str | None,
    verifier_frontend_profile: str | None,
    verifier_frontend_commands: list[str] | None,
    verifier_observability_profile: str | None,
    verifier_observability_commands: list[str] | None,
    verifier_artifact_globs: list[str] | None,
    verifier_touches_frontend: bool,
    verifier_requires_frontend_visual: bool,
    verifier_include_day_live_canary: bool,
    planner_contract_override: dict | None,
    prefer_agent_output: bool,
) -> dict:
    logger = get_run_logger()
    parser_error = None
    contract = None
    if prefer_agent_output:
        try:
            payload = parse_planner_wave_plan_message(
                read_agent_message(planner_run.get('last_message_path'), planner_run.get('stdout_path'))
            )
            contract = normalize_wave_plan_contract(
                payload,
                external_dependency_refs={
                    str(planner_packet_id).strip(),
                    str(architect_packet_id).strip(),
                    "planner output",
                    "architect formalization",
                },
            )
        except ValueError as exc:
            parser_error = str(exc)
    if contract is None and planner_contract_override:
        contract = normalize_wave_plan_contract(
            planner_contract_override,
            external_dependency_refs={
                str(planner_packet_id).strip(),
                str(architect_packet_id).strip(),
                "planner output",
                "architect formalization",
            },
        )
        source = 'explicit_input'
    elif contract is None:
        contract = default_wave_plan_contract(
            feature_id=feature_id,
            implementation_title=implementation_title,
            implementation_summary=implementation_summary,
            verifier_backend_profile=verifier_backend_profile,
            verifier_frontend_profile=verifier_frontend_profile,
            verifier_frontend_commands=verifier_frontend_commands,
            verifier_observability_profile=verifier_observability_profile,
            verifier_observability_commands=verifier_observability_commands,
            verifier_artifact_globs=verifier_artifact_globs,
            verifier_touches_frontend=verifier_touches_frontend,
            verifier_requires_frontend_visual=verifier_requires_frontend_visual,
            verifier_include_day_live_canary=verifier_include_day_live_canary,
        )
        source = 'fallback'
    elif contract is not None:
        source = 'agent_output'
    logger.info('Resolved packet graph contract source=%s parser_error=%s', source, parser_error)
    return {'contract': contract, 'source': source, 'parser_error': parser_error}


# START_FUNCTION_CONTRACT
# name: materialize_planner_contract_task
# purpose: Materialize the resolved planner contract into packet records.
# inputs: Feature id, architect/planner packet ids, resolved contract result, agent hints, and verifier defaults.
# returns: Materialized packet graph dictionary.
# side_effects: Writes packet state and files through materialize_planner_contract.
# emitted_logs: Prefect task log line.
# error_behavior: Propagates materialization errors.
# END_FUNCTION_CONTRACT
@task(task_run_name="packet-graph:materialize:{feature_id}")
def materialize_planner_contract_task(
    feature_id: str,
    planner_packet_id: str,
    architect_packet_id: str,
    planner_contract_result: dict,
    agent_workdir: str | None,
    agent_sandbox: str | None,
    verifier_backend_profile: str | None,
    verifier_frontend_profile: str | None,
    verifier_frontend_commands: list[str] | None,
    verifier_observability_profile: str | None,
    verifier_observability_commands: list[str] | None,
    verifier_artifact_globs: list[str] | None,
    verifier_touches_frontend: bool,
    verifier_requires_frontend_visual: bool,
    verifier_include_day_live_canary: bool,
):
    logger = get_run_logger()
    base_execution_hints = {
        key: value
        for key, value in {
            'workdir': agent_workdir,
            'sandbox': agent_sandbox,
        }.items()
        if value not in (None, '')
    }
    materialized = materialize_planner_contract(
        feature_id=feature_id,
        planner_packet_id=planner_packet_id,
        architect_packet_id=architect_packet_id,
        contract=planner_contract_result['contract'],
        base_execution_hints=base_execution_hints,
        default_verifier_execution_hints={
            "runner": "verifier",
            "backend_profile": verifier_backend_profile,
            "frontend_profile": verifier_frontend_profile,
            "frontend_commands": verifier_frontend_commands or [],
            "observability_profile": verifier_observability_profile,
            "observability_commands": verifier_observability_commands or [],
            "artifact_globs": verifier_artifact_globs or [],
            "touches_frontend": verifier_touches_frontend,
            "requires_frontend_visual": verifier_requires_frontend_visual,
            "include_day_live_canary": verifier_include_day_live_canary,
        },
    )
    logger.info('Materialized packet graph with %s packets for %s', len(materialized['packets']), feature_id)
    return materialized


# START_FUNCTION_CONTRACT
# name: validate_planner_contract_task
# purpose: Validate materialized planner packet graph invariants.
# inputs:
#   feature_id: Feature identifier.
#   materialized_contract: Materialized contract dictionary with packets.
# returns: Validation result with valid boolean and issues list.
# side_effects: Reads architect manifest state/file.
# emitted_logs: Prefect task log line.
# error_behavior: Collects validation issues instead of raising for graph contract problems.
# END_FUNCTION_CONTRACT
@task(task_run_name="packet-graph:validate:{feature_id}")
def validate_planner_contract_task(
    feature_id: str,
    materialized_contract: dict,
):
    logger = get_run_logger()
    packets = list(materialized_contract.get("packets") or [])
    packets_by_id = packet_map(packets)
    issues: list[str] = []
    architect_manifest = load_architect_manifest(feature_id)

    for packet in packets:
        packet_id = str(packet.get("packet_id") or "")
        role = str(packet.get("role") or "")
        execution = packet_execution_contract(packet)
        if role == "reviewer":
            explicit_target = str(packet.get("review_target_packet_id") or "").strip()
            if not explicit_target:
                issues.append(f"{packet_id}: reviewer packet is missing explicit review_target_packet_id")
            elif explicit_target not in packets_by_id:
                issues.append(f"{packet_id}: explicit review target does not resolve to a generated packet")
        if role == "verifier":
            hints = dict(packet.get("execution_hints") or {})
            for key in ("backend_commands", "frontend_commands", "observability_commands"):
                value = hints.get(key)
                if value is None:
                    continue
                if not isinstance(value, list):
                    issues.append(f"{packet_id}: {key} must be a list")
                    continue
                for item in value:
                    if not isinstance(item, str) or not item.strip():
                        issues.append(f"{packet_id}: {key} contains empty/non-string command")
                    elif item.strip().startswith("{") or item.strip().startswith("["):
                        issues.append(f"{packet_id}: {key} contains structured text instead of shell command")
        if uses_today_week_observability(packet):
            if role != "verifier":
                issues.append(
                    f"{packet_id}: today-week canonical observability gate is allowed only on verifier packets"
                )
            observability_scope = normalize_observability_scope(execution.get("observability_scope"))
            if observability_scope != "wave_final":
                issues.append(
                    f"{packet_id}: today-week canonical observability gate must declare execution.observability_scope=wave_final"
                )
            canonical_flow_commands = string_command_list(execution.get("canonical_flow_commands"))
            include_day_live_canary = bool(execution.get("include_day_live_canary"))
            if not canonical_flow_commands and not include_day_live_canary:
                issues.append(
                    f"{packet_id}: today-week canonical observability gate must provide execution.canonical_flow_commands or include_day_live_canary"
                )
            architect_wave = architect_wave_contract(architect_manifest, str(packet.get("wave_id") or ""))
            if not architect_wave:
                issues.append(
                    f"{packet_id}: architect manifest does not define wave {packet.get('wave_id')} required to authorize today-week evidence ownership"
                )
            else:
                architect_scope = normalize_observability_scope(architect_wave.get("observability_scope"))
                architect_canonical = string_command_list(architect_wave.get("canonical_flow_commands"))
                architect_live_canary = bool(architect_wave.get("include_day_live_canary"))
                if architect_scope != "wave_final":
                    issues.append(
                        f"{packet_id}: architect manifest wave {packet.get('wave_id')} does not authorize today-week wave_final ownership"
                    )
                if not architect_canonical and not architect_live_canary:
                    issues.append(
                        f"{packet_id}: architect manifest wave {packet.get('wave_id')} lacks canonical_flow_commands/include_day_live_canary for today-week gate"
                    )
                missing_architect_commands = [
                    command for command in architect_canonical if command not in canonical_flow_commands
                ]
                unexpected_planner_commands = [
                    command for command in canonical_flow_commands if command not in architect_canonical
                ]
                if missing_architect_commands:
                    issues.append(
                        f"{packet_id}: planner canonical_flow_commands are missing architect-authorized commands {missing_architect_commands}"
                    )
                if architect_canonical and unexpected_planner_commands:
                    issues.append(
                        f"{packet_id}: planner canonical_flow_commands widen architect scope with unexpected commands {unexpected_planner_commands}"
                    )
        if execution:
            observability_scope = normalize_observability_scope(execution.get("observability_scope"))
            if observability_scope and observability_scope not in {"none", "packet_local", "wave_final"}:
                issues.append(f"{packet_id}: unsupported execution.observability_scope={execution.get('observability_scope')}")
            canonical_flow_commands = execution.get("canonical_flow_commands")
            if canonical_flow_commands is not None and not isinstance(canonical_flow_commands, list):
                issues.append(f"{packet_id}: execution.canonical_flow_commands must be a list")
            elif isinstance(canonical_flow_commands, list):
                for item in canonical_flow_commands:
                    if not isinstance(item, str) or not item.strip():
                        issues.append(f"{packet_id}: execution.canonical_flow_commands contains empty/non-string command")

    logger.info("Packet graph validation for %s issues=%s", feature_id, len(issues))
    return {"valid": not issues, "issues": issues}


_load_architect_manifest = load_architect_manifest
_architect_wave_contract = architect_wave_contract
_should_run_planner = should_run_planner
_architect_plan_next_action = architect_plan_next_action
_architect_packet_candidates_to_contract = architect_packet_candidates_to_contract
