# AI_HEADER
# module: prefect_grace.tasks.prefect_submitter
# purpose: Submit Prefect flow runs for features and packet runners.
# canon: GRACE Canon Script Discipline
# status: active
# owner: prefect-grace
# last_verified: 2026-05-26
# dependencies: prefect_grace.runtime_config
# END_AI_HEADER

# START_MODULE_CONTRACT
# module_name: prefect_submitter
# purpose: Provide Prefect flow run submission helpers for feature pipeline and packet runner deployments.
# responsibilities:
#   - Build flow parameters for feature, managed packet, and E2E packet runs.
#   - Submit flow runs to Prefect deployments with idempotency keys.
#   - Return JSON-safe run references.
# dependencies:
#   - prefect_grace.runtime_config
#   - prefect (lazy import inside functions)
# state: stateless
# concurrency: safe
# error_handling: Raises RuntimeError if Prefect unavailable, propagates Prefect client errors.
# END_MODULE_CONTRACT

# START_MODULE_MAP
# Public API:
#   - FEATURE_DEPLOYMENT_NAME: str
#   - MANAGED_PACKET_DEPLOYMENT_NAME: str
#   - E2E_PACKET_DEPLOYMENT_NAME: str
#   - parse_scheduled_time(value: str | None) -> datetime | None
#   - feature_flow_parameters(...) -> dict[str, Any]
#   - feature_flow_run_name(feature_id: str, title: str | None) -> str
#   - managed_packet_flow_run_name(packet_id: str, title: str | None) -> str
#   - managed_packet_flow_parameters(...) -> dict[str, Any]
#   - e2e_packet_flow_run_name(packet_id: str, attempt: int, title: str | None) -> str
#   - e2e_packet_flow_parameters(...) -> dict[str, Any]
#   - build_feature_submission_request(...) -> dict[str, Any]
#   - build_managed_packet_submission_request(...) -> dict[str, Any]
#   - build_e2e_packet_submission_request(...) -> dict[str, Any]
#   - submit_feature_flow_run(...) -> dict[str, Any]
#   - submit_managed_packet_flow_run(...) -> dict[str, Any]
#   - submit_e2e_packet_flow_run(...) -> dict[str, Any]
# Internal:
#   None
# END_MODULE_MAP

from __future__ import annotations

from datetime import datetime, timezone
import os
from typing import Any

from prefect_grace.runtime_config import load_runtime_config

FEATURE_DEPLOYMENT_NAME = "prefect-grace-feature-pipeline/live-feature-pipeline"
MANAGED_PACKET_DEPLOYMENT_NAME = "prefect-grace-managed-packet-runner/live-managed-packet-runner"
E2E_PACKET_DEPLOYMENT_NAME = "prefect-grace-e2e-packet-runner/live-e2e-packet-runner"


# START_FUNCTION_CONTRACT
# name: parse_scheduled_time
# purpose: Parse ISO8601 scheduled time string to UTC datetime.
# inputs:
#   value: Optional ISO8601 string with optional Z suffix.
# returns: datetime in UTC timezone, or None if value is None/empty.
# side_effects: None.
# emitted_logs: None.
# error_behavior: Raises ValueError if string is malformed.
# END_FUNCTION_CONTRACT
def parse_scheduled_time(value: str | None) -> datetime | None:
    if not value:
        return None
    parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


# START_FUNCTION_CONTRACT
# name: feature_flow_parameters
# purpose: Build flow parameters dict for feature pipeline deployment.
# inputs:
#   feature_id: Feature identifier.
#   title: Feature title.
#   summary: Feature summary.
#   implementation_title: Optional implementation packet title.
#   implementation_summary: Optional implementation packet summary.
#   execute: Whether to run in execute mode (default False = dry_run).
#   timeout_seconds: Flow timeout in seconds.
#   verifier_backend_profile: Backend verification profile name.
#   verifier_frontend_profile: Frontend verification profile name.
#   verifier_frontend_commands: Custom frontend verification commands.
#   verifier_observability_profile: Observability verification profile name.
#   verifier_observability_commands: Custom observability verification commands.
#   verifier_artifact_globs: Glob patterns for verification artifacts.
#   verifier_touches_frontend: Whether feature touches frontend code.
#   verifier_requires_frontend_visual: Whether feature requires visual frontend testing.
#   verifier_include_day_live_canary: Whether to include day-live canary checks.
#   prefer_agent_output: Whether to prefer agent output format.
#   run_planner: Whether to run planner phase.
#   agent_workdir: Agent working directory override.
#   agent_sandbox: Agent sandbox mode.
#   business_context: Business context metadata.
#   planner_contract: Planner contract specification.
#   commit_hash: Git commit hash for feature.
# returns: dict[str, Any] with all flow parameters.
# side_effects: None.
# emitted_logs: None.
# error_behavior: None.
# END_FUNCTION_CONTRACT
def feature_flow_parameters(
    *,
    feature_id: str,
    title: str,
    summary: str,
    implementation_title: str | None = None,
    implementation_summary: str | None = None,
    execute: bool = False,
    timeout_seconds: int = 3600,
    verifier_backend_profile: str | None = "backend_quick",
    verifier_frontend_profile: str | None = None,
    verifier_frontend_commands: list[str] | None = None,
    verifier_observability_profile: str | None = None,
    verifier_observability_commands: list[str] | None = None,
    verifier_artifact_globs: list[str] | None = None,
    verifier_touches_frontend: bool = False,
    verifier_requires_frontend_visual: bool = False,
    verifier_include_day_live_canary: bool = False,
    prefer_agent_output: bool = True,
    run_planner: bool | None = None,
    agent_workdir: str | None = None,
    agent_sandbox: str | None = None,
    business_context: dict[str, Any] | None = None,
    planner_contract: dict[str, Any] | None = None,
    commit_hash: str | None = None,
) -> dict[str, Any]:
    return {
        "feature_id": feature_id,
        "title": title,
        "summary": summary,
        "implementation_title": implementation_title or "Live Implementation Packet",
        "implementation_summary": implementation_summary
        or "Execute the feature through architect, planner, coder, verifier, reviewer, and architect wave gate.",
        "dry_run": not bool(execute),
        "timeout_seconds": int(timeout_seconds),
        "verifier_backend_profile": verifier_backend_profile,
        "verifier_frontend_profile": verifier_frontend_profile,
        "verifier_frontend_commands": list(verifier_frontend_commands or []),
        "verifier_observability_profile": verifier_observability_profile,
        "verifier_observability_commands": list(verifier_observability_commands or []),
        "verifier_artifact_globs": list(verifier_artifact_globs or []),
        "verifier_touches_frontend": bool(verifier_touches_frontend),
        "verifier_requires_frontend_visual": bool(verifier_requires_frontend_visual),
        "verifier_include_day_live_canary": bool(verifier_include_day_live_canary),
        "prefer_agent_output": bool(prefer_agent_output),
        "run_planner": run_planner,
        "agent_workdir": agent_workdir,
        "agent_sandbox": agent_sandbox,
        "business_context": dict(business_context or {}),
        "planner_contract": dict(planner_contract or {}) if planner_contract else None,
        "commit_hash": str(commit_hash or "").strip() or None,
    }


# START_FUNCTION_CONTRACT
# name: feature_flow_run_name
# purpose: Generate Prefect flow run name for feature pipeline run.
# inputs:
#   feature_id: Feature identifier.
#   title: Optional feature title.
# returns: Flow run name string in format "feature:{feature_id}:{title}" or "feature:{feature_id}".
# side_effects: None.
# emitted_logs: None.
# error_behavior: None.
# END_FUNCTION_CONTRACT
def feature_flow_run_name(feature_id: str, title: str | None = None) -> str:
    clean_feature_id = str(feature_id or "unknown-feature")
    clean_title = str(title or "").strip()
    if clean_title:
        return f"feature:{clean_feature_id}:{clean_title}"
    return f"feature:{clean_feature_id}"


# START_FUNCTION_CONTRACT
# name: managed_packet_flow_run_name
# purpose: Generate Prefect flow run name for managed packet runner.
# inputs:
#   packet_id: Packet identifier.
#   title: Optional packet title.
# returns: Flow run name string in format "packet:{packet_id}:{title}" or "packet:{packet_id}".
# side_effects: None.
# emitted_logs: None.
# error_behavior: None.
# END_FUNCTION_CONTRACT
def managed_packet_flow_run_name(packet_id: str, title: str | None = None) -> str:
    clean_packet_id = str(packet_id or "unknown-packet")
    clean_title = str(title or "").strip()
    if clean_title:
        return f"packet:{clean_packet_id}:{clean_title}"
    return f"packet:{clean_packet_id}"


# START_FUNCTION_CONTRACT
# name: e2e_packet_flow_run_name
# purpose: Generate Prefect flow run name for E2E packet runner.
# inputs:
#   packet_id: Packet identifier.
#   attempt: Packet execution attempt number.
#   title: Optional packet title.
# returns: Flow run name string with packet and attempt.
# side_effects: None.
# emitted_logs: None.
# error_behavior: None.
# END_FUNCTION_CONTRACT
def e2e_packet_flow_run_name(packet_id: str, attempt: int, title: str | None = None) -> str:
    clean_packet_id = str(packet_id or "unknown-packet")
    clean_title = str(title or "").strip()
    base = f"e2e-packet:{clean_packet_id}:attempt-{int(attempt)}"
    if clean_title:
        return f"{base}:{clean_title}"
    return base


# START_FUNCTION_CONTRACT
# name: managed_packet_flow_parameters
# purpose: Build flow parameters dict for managed packet runner deployment.
# inputs:
#   packet_file: Path to packet execution file.
#   repo_root: Repository root directory.
#   worktree_root: Worktree root directory for isolated execution.
#   project_key: Project identifier.
#   packet_id: Packet identifier.
#   attempt: Packet execution attempt number.
#   base_ref: Git base reference (default "HEAD").
#   dry_run: Whether to run in dry-run mode (default False).
#   execute_agent: Whether to execute live agents (default False).
#   timeout_seconds: Flow timeout in seconds.
#   runtime_state_root: Optional runtime state root for managed runner lookup.
# returns: dict[str, Any] with all flow parameters.
# side_effects: None.
# emitted_logs: None.
# error_behavior: None.
# END_FUNCTION_CONTRACT
def managed_packet_flow_parameters(
    *,
    packet_file: str,
    repo_root: str,
    worktree_root: str,
    project_key: str,
    packet_id: str,
    attempt: int,
    base_ref: str = "HEAD",
    dry_run: bool = False,
    execute_agent: bool = False,
    timeout_seconds: int = 3600,
    runtime_state_root: str | None = None,
    managed_result_payload_path: str | None = None,
    managed_result_payload_root: str | None = None,
) -> dict[str, Any]:
    parameters = {
        "packet_file": str(packet_file),
        "repo_root": str(repo_root),
        "worktree_root": str(worktree_root),
        "project_key": str(project_key),
        "packet_id": str(packet_id),
        "attempt": int(attempt),
        "base_ref": str(base_ref),
        "dry_run": bool(dry_run),
        "execute_agent": bool(execute_agent),
        "timeout_seconds": int(timeout_seconds),
    }
    if runtime_state_root:
        parameters["runtime_state_root"] = str(runtime_state_root)
    if managed_result_payload_path:
        parameters["managed_result_payload_path"] = str(managed_result_payload_path)
        parameters["managed_result_payload_root"] = str(managed_result_payload_root or "")
    return parameters


# START_FUNCTION_CONTRACT
# name: e2e_packet_flow_parameters
# purpose: Build flow parameters dict for E2E packet runner deployment.
# inputs:
#   project_root: Project repository root directory.
#   packet_path: Path to packet execution file.
#   state_root: Runtime state root directory.
#   worktree_root: Worktree root directory for isolated execution.
#   project_key: Project identifier.
#   packet_id: Packet identifier.
#   attempt: Packet execution attempt number.
#   base_ref: Git base reference.
#   dry_run: Whether the E2E runner should use dry-run agent behavior.
#   execute_agent: Whether to allow live agent execution inside the E2E runner.
#   timeout_seconds: Flow timeout in seconds.
#   keep_worktree: Whether the E2E runner keeps the worktree after execution.
# returns: dict[str, Any] with e2e_packet_runner_flow-compatible parameters.
# side_effects: None.
# emitted_logs: None.
# error_behavior: None.
# END_FUNCTION_CONTRACT
def e2e_packet_flow_parameters(
    *,
    project_root: str,
    packet_path: str,
    state_root: str,
    worktree_root: str,
    project_key: str,
    packet_id: str,
    attempt: int,
    base_ref: str = "HEAD",
    dry_run: bool = True,
    execute_agent: bool = False,
    timeout_seconds: int = 3600,
    keep_worktree: bool = True,
) -> dict[str, Any]:
    return {
        "project_root": str(project_root),
        "packet_path": str(packet_path),
        "state_root": str(state_root),
        "worktree_root": str(worktree_root),
        "project_key": str(project_key),
        "packet_id": str(packet_id),
        "attempt": int(attempt),
        "base_ref": str(base_ref),
        "dry_run": bool(dry_run),
        "execute_agent": bool(execute_agent),
        "timeout_seconds": int(timeout_seconds),
        "keep_worktree": bool(keep_worktree),
    }


# START_FUNCTION_CONTRACT
# name: _dedupe_tags
# purpose: Preserve tag order while removing duplicates and empty values.
# inputs:
#   tags: Candidate tag list.
# returns: List of unique non-empty tags.
# side_effects: None.
# emitted_logs: None.
# error_behavior: None.
# END_FUNCTION_CONTRACT
def _dedupe_tags(tags: list[str]) -> list[str]:
    seen = set()
    result = []
    for tag in tags:
        clean_tag = str(tag or "").strip()
        if clean_tag and clean_tag not in seen:
            result.append(clean_tag)
            seen.add(clean_tag)
    return result


# START_FUNCTION_CONTRACT
# name: build_feature_submission_request
# purpose: Build submission request dict for feature flow run (no Prefect calls).
# inputs:
#   parameters: Flow parameters dict from feature_flow_parameters().
#   scheduled_for: Optional ISO8601 scheduled time string.
#   tags: Optional additional tags for flow run.
#   idempotency_key: Optional idempotency key (auto-generated if None).
# returns: dict[str, Any] with deployment_name, parameters, scheduled_time, flow_run_name, idempotency_key, tags, work_queue_name.
# side_effects: None.
# emitted_logs: None.
# error_behavior: None.
# END_FUNCTION_CONTRACT
def build_feature_submission_request(
    *,
    parameters: dict[str, Any],
    scheduled_for: str | None = None,
    tags: list[str] | None = None,
    idempotency_key: str | None = None,
) -> dict[str, Any]:
    runtime = load_runtime_config()
    scheduled_time = parse_scheduled_time(scheduled_for) or datetime.now(timezone.utc)
    feature_id = str(parameters.get("feature_id") or "")
    title = str(parameters.get("title") or "")
    flow_tags = ["grace", "live", f"feature:{feature_id}", "prefect-native-queue", *(tags or [])]

    return {
        "deployment_name": FEATURE_DEPLOYMENT_NAME,
        "parameters": parameters,
        "scheduled_time": scheduled_time,
        "flow_run_name": feature_flow_run_name(feature_id, title),
        "idempotency_key": idempotency_key or f"grace-feature:{feature_id}:{scheduled_time.isoformat()}",
        "labels": {"grace.feature_id": feature_id},
        "tags": flow_tags,
        "work_queue_name": runtime.live_queue_name,
        "api_url": runtime.api_url,
        "feature_id": feature_id,
        "title": title,
    }


# START_FUNCTION_CONTRACT
# name: build_managed_packet_submission_request
# purpose: Build submission request dict for managed packet flow run (no Prefect calls).
# inputs:
#   parameters: Flow parameters dict from managed_packet_flow_parameters().
#   scheduled_for: Optional ISO8601 scheduled time string.
#   tags: Optional additional tags for flow run.
#   idempotency_key: Optional idempotency key (auto-generated if None).
# returns: dict[str, Any] with deployment_name, parameters, scheduled_time, flow_run_name, idempotency_key, tags, work_queue_name.
# side_effects: None.
# emitted_logs: None.
# error_behavior: None.
# END_FUNCTION_CONTRACT
def build_managed_packet_submission_request(
    *,
    parameters: dict[str, Any],
    scheduled_for: str | None = None,
    tags: list[str] | None = None,
    idempotency_key: str | None = None,
) -> dict[str, Any]:
    runtime = load_runtime_config()
    scheduled_time = parse_scheduled_time(scheduled_for) or datetime.now(timezone.utc)
    packet_id = str(parameters.get("packet_id") or "")
    project_key = str(parameters.get("project_key") or "")
    flow_tags = ["grace", "packet", "managed-runner", f"packet:{packet_id}", f"project:{project_key}", *(tags or [])]

    return {
        "deployment_name": MANAGED_PACKET_DEPLOYMENT_NAME,
        "parameters": parameters,
        "scheduled_time": scheduled_time,
        "flow_run_name": managed_packet_flow_run_name(packet_id),
        "idempotency_key": idempotency_key or f"grace-packet:{project_key}:{packet_id}:{scheduled_time.isoformat()}",
        "labels": {"grace.packet_id": packet_id, "grace.project_key": project_key},
        "tags": flow_tags,
        "work_queue_name": runtime.live_queue_name,
        "api_url": runtime.api_url,
        "packet_id": packet_id,
        "project_key": project_key,
    }


# START_FUNCTION_CONTRACT
# name: build_e2e_packet_submission_request
# purpose: Build submission request dict for E2E packet flow run (no Prefect calls).
# inputs:
#   parameters: Flow parameters dict from e2e_packet_flow_parameters().
#   scheduled_for: Optional ISO8601 scheduled time string.
#   tags: Optional additional tags for flow run.
#   idempotency_key: Optional idempotency key.
#   deployment_name: Prefect deployment name to submit.
# returns: dict[str, Any] with deployment_name, parameters, scheduled_time, flow_run_name, idempotency_key, tags, work_queue_name.
# side_effects: None.
# emitted_logs: None.
# error_behavior: None.
# END_FUNCTION_CONTRACT
def build_e2e_packet_submission_request(
    *,
    parameters: dict[str, Any],
    scheduled_for: str | None = None,
    tags: list[str] | None = None,
    idempotency_key: str | None = None,
    deployment_name: str = E2E_PACKET_DEPLOYMENT_NAME,
) -> dict[str, Any]:
    runtime = load_runtime_config()
    scheduled_time = parse_scheduled_time(scheduled_for) or datetime.now(timezone.utc)
    packet_id = str(parameters.get("packet_id") or "")
    project_key = str(parameters.get("project_key") or "")
    attempt = int(parameters.get("attempt") or 1)
    flow_tags = _dedupe_tags(
        [
            "grace",
            "packet",
            "e2e",
            f"packet:{packet_id}",
            f"project:{project_key}",
            *(tags or []),
        ]
    )

    return {
        "deployment_name": deployment_name,
        "parameters": parameters,
        "scheduled_time": scheduled_time,
        "flow_run_name": e2e_packet_flow_run_name(packet_id, attempt),
        "idempotency_key": idempotency_key
        or f"grace-packet:{project_key}:{packet_id}:attempt-{attempt:04d}:{scheduled_time.isoformat()}",
        "labels": {"grace.packet_id": packet_id, "grace.project_key": project_key},
        "tags": flow_tags,
        "work_pool_name": runtime.work_pool_name,
        "work_queue_name": runtime.live_queue_name,
        "api_url": runtime.api_url,
        "packet_id": packet_id,
        "project_key": project_key,
        "attempt": attempt,
    }


# START_FUNCTION_CONTRACT
# name: submit_feature_flow_run
# purpose: Submit a Prefect flow run for feature pipeline deployment (delegates to runtime adapter).
# inputs:
#   parameters: Flow parameters dict from feature_flow_parameters().
#   scheduled_for: Optional ISO8601 scheduled time string.
#   tags: Optional additional tags for flow run.
#   idempotency_key: Optional idempotency key (auto-generated if None).
# returns: dict[str, Any] with flow_run_id, deployment_id, feature_id, title, status, scheduled_for, work_queue_name, tags.
# side_effects: Creates Prefect flow run via runtime adapter.
# emitted_logs: None.
# error_behavior: Raises RuntimeError if Prefect unavailable, propagates Prefect client errors.
# END_FUNCTION_CONTRACT
def submit_feature_flow_run(
    *,
    parameters: dict[str, Any],
    scheduled_for: str | None = None,
    tags: list[str] | None = None,
    idempotency_key: str | None = None,
) -> dict[str, Any]:
    """Wrapper for backward compatibility - delegates to runtime adapter for Prefect calls."""
    from prefect_grace.platform.runtime_adapter import FeatureSubmitter
    submitter = FeatureSubmitter()
    return submitter(
        parameters=parameters,
        scheduled_for=scheduled_for,
        tags=tags,
        idempotency_key=idempotency_key,
    )


# START_FUNCTION_CONTRACT
# name: submit_managed_packet_flow_run
# purpose: Submit a Prefect flow run for managed packet runner deployment (delegates to runtime adapter).
# inputs:
#   parameters: Flow parameters dict from managed_packet_flow_parameters().
#   scheduled_for: Optional ISO8601 scheduled time string.
#   tags: Optional additional tags for flow run.
#   idempotency_key: Optional idempotency key (auto-generated if None).
# returns: dict[str, Any] with flow_run_id, flow_run_name, deployment_id, deployment_name, packet_id, project_key, status, scheduled_for, work_queue_name, url, tags.
# side_effects: Creates Prefect flow run via runtime adapter.
# emitted_logs: None.
# error_behavior: Raises RuntimeError if Prefect unavailable, propagates Prefect client errors.
# END_FUNCTION_CONTRACT
def submit_managed_packet_flow_run(
    *,
    parameters: dict[str, Any],
    scheduled_for: str | None = None,
    tags: list[str] | None = None,
    idempotency_key: str | None = None,
) -> dict[str, Any]:
    """Wrapper for backward compatibility - delegates to runtime adapter for Prefect calls."""
    from prefect_grace.platform.runtime_adapter import ManagedPacketSubmitter
    submitter = ManagedPacketSubmitter()
    return submitter(
        parameters=parameters,
        scheduled_for=scheduled_for,
        tags=tags,
        idempotency_key=idempotency_key,
    )


# START_FUNCTION_CONTRACT
# name: submit_e2e_packet_flow_run
# purpose: Submit a Prefect flow run for E2E packet runner deployment.
# inputs:
#   parameters: Flow parameters dict from e2e_packet_flow_parameters().
#   scheduled_for: Optional ISO8601 scheduled time string.
#   tags: Optional additional tags for flow run.
#   idempotency_key: Optional idempotency key.
#   deployment_name: Prefect deployment name to submit.
# returns: dict[str, Any] with flow_run_id, flow_run_name, deployment_name, packet_id, project_key, status, scheduled_for, work queue/pool metadata, url, tags.
# side_effects: Creates Prefect flow run via runtime adapter.
# emitted_logs: None.
# error_behavior: Raises RuntimeError if Prefect unavailable, propagates Prefect client errors.
# END_FUNCTION_CONTRACT
def submit_e2e_packet_flow_run(
    *,
    parameters: dict[str, Any],
    scheduled_for: str | None = None,
    tags: list[str] | None = None,
    idempotency_key: str | None = None,
    deployment_name: str = E2E_PACKET_DEPLOYMENT_NAME,
) -> dict[str, Any]:
    """Wrapper for backward compatibility - delegates to runtime adapter for Prefect calls."""
    from prefect_grace.platform.runtime_adapter import E2EPacketSubmitter
    submitter = E2EPacketSubmitter(deployment_name=deployment_name)
    return submitter(
        parameters=parameters,
        scheduled_for=scheduled_for,
        tags=tags,
        idempotency_key=idempotency_key,
    )
