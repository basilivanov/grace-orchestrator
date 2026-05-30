# ############################################################################
# AI_HEADER: managed_packet_runner_flow
# ROLE: Prefect flow for managed packet execution with artifact publication.
# ############################################################################

# START_MODULE_CONTRACT
# purpose: Prefect flow wrapper for managed packet execution with best-effort artifact publication.
# inputs: Packet file, repo root, worktree root, project key, packet ID, attempt, base ref, execution flags.
# returns: Managed packet run result dict.
# side_effects: Creates worktree, launches agent if execute_agent=True and dry_run=False, evaluates scope, publishes artifact.
# emitted_logs: Prefect flow logs.
# error_behavior: Flow completes for domain statuses scope_blocked and agent_failed (domain outcomes, not exceptions). Unexpected errors fail the flow.
# END_MODULE_CONTRACT

# START_MODULE_MAP
# mapping:
#   - flow: managed_packet_runner_flow
#   - task: run_managed_packet_task
#   - task: publish_managed_packet_artifact_task
# END_MODULE_MAP

from __future__ import annotations

from pathlib import Path
from typing import Any

from prefect_grace.prefect_compat import flow, task
from prefect_grace.platform.managed_packet_runner import run_managed_packet
from prefect_grace.tasks.managed_packet_artifacts import (
    publish_managed_packet_run_artifact,
    write_managed_result_payload,
)


# START_FUNCTION_CONTRACT
# name: run_managed_packet_task
# purpose: Prefect task wrapper for run_managed_packet.
# inputs: Same as run_managed_packet.
# returns: dict[str, Any] - Managed packet run result dict.
# side_effects: Creates worktree, launches agent if execute_agent=True and dry_run=False, evaluates scope.
# emitted_logs: None (Prefect task logs).
# error_behavior: Returns result dict with domain status, does not raise for domain outcomes.
# END_FUNCTION_CONTRACT
@task(name="run-managed-packet")
def run_managed_packet_task(
    *,
    packet_file: str,
    repo_root: str,
    worktree_root: str,
    project_key: str,
    packet_id: str,
    attempt: int,
    base_ref: str,
    dry_run: bool = True,
    execute_agent: bool = False,
    timeout_seconds: int = 3600,
    keep_worktree: bool = True,
    runtime_state_root: str | None = None,
) -> dict[str, Any]:
    """
    Prefect task wrapper for run_managed_packet.

    Args:
        packet_file: Path to EXECUTION_PACKET.md
        repo_root: Repository root directory
        worktree_root: Worktree root directory
        project_key: Project identifier
        packet_id: Packet identifier
        attempt: Execution attempt number
        base_ref: Git base reference
        dry_run: Safe default, no agent execution
        execute_agent: Explicitly allow live agent execution
        timeout_seconds: Agent timeout
        keep_worktree: Preserve worktree after execution
        runtime_state_root: Optional runtime state root for packet registry lookup

    Returns:
        Managed packet run result dict
    """
    result = run_managed_packet(
        packet_file=Path(packet_file),
        repo_root=Path(repo_root),
        worktree_root=Path(worktree_root),
        project_key=project_key,
        packet_id=packet_id,
        attempt=attempt,
        base_ref=base_ref,
        dry_run=dry_run,
        execute_agent=execute_agent,
        timeout_seconds=timeout_seconds,
        keep_worktree=keep_worktree,
        runtime_state_root=runtime_state_root,
    )
    return result.to_dict()


# START_FUNCTION_CONTRACT
# name: publish_managed_packet_artifact_task
# purpose: Prefect task wrapper for publish_managed_packet_run_artifact.
# inputs:
#   result: dict[str, Any] - Managed packet run result dict.
# returns: list[str] - List of artifact IDs (empty if unavailable/failed).
# side_effects: Creates Prefect markdown artifact if available.
# emitted_logs: None (Prefect task logs).
# error_behavior: Returns empty list on failure, does not raise.
# END_FUNCTION_CONTRACT
@task(name="publish-managed-packet-artifact")
def publish_managed_packet_artifact_task(result: dict[str, Any]) -> list[str]:
    """
    Prefect task wrapper for publish_managed_packet_run_artifact.

    Best-effort publication:
    - Returns empty list if Prefect artifacts are unavailable
    - Returns empty list if publication fails
    - Does not raise exceptions

    Args:
        result: Managed packet run result dict

    Returns:
        List of artifact IDs (empty if unavailable/failed)
    """
    return publish_managed_packet_run_artifact(result)


# START_FUNCTION_CONTRACT
# name: managed_packet_runner_flow
# purpose: Prefect flow for managed packet execution with artifact publication.
# inputs: Packet file, repo root, worktree root, project key, packet ID, attempt, base ref, execution flags.
# returns: dict[str, Any] - Managed packet run result dict with artifact_ids.
# side_effects: Creates worktree, launches agent if execute_agent=True and dry_run=False, evaluates scope, publishes artifact.
# emitted_logs: Prefect flow logs.
# error_behavior: Flow completes for domain statuses scope_blocked and agent_failed (domain outcomes). Unexpected errors fail the flow.
# END_FUNCTION_CONTRACT
@flow(
    name="prefect-grace-managed-packet-runner",
    flow_run_name="managed-packet:{packet_id}:attempt-{attempt}",
)
def managed_packet_runner_flow(
    *,
    packet_file: str,
    repo_root: str,
    worktree_root: str,
    project_key: str,
    packet_id: str,
    attempt: int,
    base_ref: str,
    dry_run: bool = True,
    execute_agent: bool = False,
    timeout_seconds: int = 3600,
    keep_worktree: bool = True,
    runtime_state_root: str | None = None,
    managed_result_payload_path: str | None = None,
    managed_result_payload_root: str | None = None,
) -> dict[str, Any]:
    """
    Prefect flow for managed packet execution with artifact publication.

    Flow completes successfully for domain statuses scope_blocked and agent_failed
    (these are domain outcomes, not Python exceptions).

    Args:
        packet_file: Path to EXECUTION_PACKET.md
        repo_root: Repository root directory
        worktree_root: Worktree root directory
        project_key: Project identifier
        packet_id: Packet identifier
        attempt: Execution attempt number
        base_ref: Git base reference
        dry_run: Safe default, no agent execution
        execute_agent: Explicitly allow live agent execution
        timeout_seconds: Agent timeout
        keep_worktree: Preserve worktree after execution
        runtime_state_root: Optional runtime state root for packet registry lookup
        managed_result_payload_path: Optional bounded JSON result payload path
        managed_result_payload_root: Required root when managed_result_payload_path is set

    Returns:
        Managed packet run result dict with artifact_ids
    """
    # Run managed packet
    result = run_managed_packet_task(
        packet_file=packet_file,
        repo_root=repo_root,
        worktree_root=worktree_root,
        project_key=project_key,
        packet_id=packet_id,
        attempt=attempt,
        base_ref=base_ref,
        dry_run=dry_run,
        execute_agent=execute_agent,
        timeout_seconds=timeout_seconds,
        keep_worktree=keep_worktree,
        runtime_state_root=runtime_state_root,
    )

    # Publish artifact (best-effort)
    artifact_ids = publish_managed_packet_artifact_task(result)

    # Add artifact_ids to result
    result["artifact_ids"] = artifact_ids
    result_payload_path = write_managed_result_payload(
        result,
        payload_path=managed_result_payload_path,
        payload_root=managed_result_payload_root,
    )
    if result_payload_path:
        result["managed_result_payload_path"] = result_payload_path

    return result
