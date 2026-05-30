# ############################################################################
# AI_HEADER: e2e_packet_runner_flow
# ROLE: Prefect flow wrapper for complete deterministic E2E packet execution.
# ############################################################################

# START_MODULE_CONTRACT
# purpose: Expose full E2E packet execution as a Prefect flow with operator artifact publication.
# inputs: Project, packet, state and worktree paths plus dry-run execution flags.
# returns: E2E packet run result dict with artifact_ids.
# side_effects: Creates worktree, may run fake handoff agents, publishes artifact best-effort.
# emitted_logs: Prefect flow/task logs.
# error_behavior: Domain outcomes return as data; unexpected wrapper errors may fail the flow.
# END_MODULE_CONTRACT

# START_MODULE_MAP
# mapping:
#   - flow: e2e_packet_runner_flow
#   - task: run_e2e_packet_task
#   - task: publish_e2e_packet_artifact_task
# END_MODULE_MAP

from __future__ import annotations

from pathlib import Path
from typing import Any

from prefect_grace.platform.e2e_packet_runner import run_e2e_packet
from prefect_grace.prefect_compat import flow, task
from prefect_grace.tasks.e2e_packet_artifacts import publish_e2e_packet_run_artifact


# START_FUNCTION_CONTRACT
# name: run_e2e_packet_task
# purpose: Prefect task wrapper for run_e2e_packet.
# inputs: Same execution arguments as e2e_packet_runner_flow.
# returns: dict[str, Any] - Serialized E2E packet run result.
# side_effects: Delegates all E2E execution side effects to run_e2e_packet.
# emitted_logs: None (Prefect task logs).
# error_behavior: Returns domain outcomes as data; unexpected errors may raise.
# END_FUNCTION_CONTRACT
@task(name="run-e2e-packet")
def run_e2e_packet_task(
    *,
    project_root: str,
    packet_path: str,
    state_root: str,
    worktree_root: str,
    project_key: str,
    packet_id: str,
    attempt: int = 1,
    base_ref: str = "HEAD",
    dry_run: bool = True,
    execute_agent: bool = False,
    fake_verifier_output: str | None = None,
    fake_reviewer_output: str | None = None,
    timeout_seconds: int = 3600,
    keep_worktree: bool = True,
) -> dict[str, Any]:
    """Run the platform E2E packet orchestrator and serialize its result."""
    result = run_e2e_packet(
        project_root=Path(project_root),
        packet_path=Path(packet_path),
        state_root=Path(state_root),
        worktree_root=Path(worktree_root),
        project_key=project_key,
        attempt=attempt,
        base_ref=base_ref,
        dry_run=dry_run,
        execute_agent=execute_agent,
        fake_verifier_output=Path(fake_verifier_output) if fake_verifier_output else None,
        fake_reviewer_output=Path(fake_reviewer_output) if fake_reviewer_output else None,
        timeout_seconds=timeout_seconds,
        keep_worktree=keep_worktree,
    )
    return result.to_dict()


# START_FUNCTION_CONTRACT
# name: publish_e2e_packet_artifact_task
# purpose: Prefect task wrapper for publish_e2e_packet_run_artifact.
# inputs:
#   result: dict[str, Any] - E2E packet runner result dict.
# returns: list[str] - Published artifact IDs or empty list.
# side_effects: Creates Prefect markdown artifact if available.
# emitted_logs: None (Prefect task logs).
# error_behavior: Returns empty list if publication is unavailable or fails.
# END_FUNCTION_CONTRACT
@task(name="publish-e2e-packet-artifact")
def publish_e2e_packet_artifact_task(result: dict[str, Any]) -> list[str]:
    """Publish the E2E result as a best-effort operator artifact."""
    return publish_e2e_packet_run_artifact(result)


# START_FUNCTION_CONTRACT
# name: e2e_packet_runner_flow
# purpose: Prefect flow for complete deterministic E2E packet execution.
# inputs: Project, packet, state and worktree paths plus dry-run execution flags.
# returns: dict[str, Any] - E2E packet result with artifact_ids.
# side_effects: Delegates execution to run_e2e_packet and publishes an artifact best-effort.
# emitted_logs: Prefect flow/task logs.
# error_behavior: Domain outcomes return as data; unexpected wrapper errors may fail flow.
# END_FUNCTION_CONTRACT
@flow(
    name="prefect-grace-e2e-packet-runner",
    flow_run_name="e2e-packet:{packet_id}:attempt-{attempt}",
)
def e2e_packet_runner_flow(
    *,
    project_root: str,
    packet_path: str,
    state_root: str,
    worktree_root: str,
    project_key: str,
    packet_id: str,
    attempt: int = 1,
    base_ref: str = "HEAD",
    dry_run: bool = True,
    execute_agent: bool = False,
    fake_verifier_output: str | None = None,
    fake_reviewer_output: str | None = None,
    timeout_seconds: int = 3600,
    keep_worktree: bool = True,
) -> dict[str, Any]:
    """Run one complete E2E packet orchestration path under a Prefect flow."""
    result = run_e2e_packet_task(
        project_root=project_root,
        packet_path=packet_path,
        state_root=state_root,
        worktree_root=worktree_root,
        project_key=project_key,
        packet_id=packet_id,
        attempt=attempt,
        base_ref=base_ref,
        dry_run=dry_run,
        execute_agent=execute_agent,
        fake_verifier_output=fake_verifier_output,
        fake_reviewer_output=fake_reviewer_output,
        timeout_seconds=timeout_seconds,
        keep_worktree=keep_worktree,
    )
    artifact_ids = publish_e2e_packet_artifact_task(result)
    result["artifact_ids"] = artifact_ids
    return result
