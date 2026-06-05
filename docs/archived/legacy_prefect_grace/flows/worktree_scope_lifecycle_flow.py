# ############################################################################
# AI_HEADER: worktree_scope_lifecycle_flow
# ROLE: Prefect flow exposing worktree scope lifecycle gate for operator visibility.
# ############################################################################

# START_MODULE_CONTRACT
# purpose: Expose worktree scope lifecycle evaluation as Prefect flow with artifact publication.
# inputs: Packet file, repo root, worktree root, packet ID, attempt, base ref.
# returns: Flow result dict with domain_status (passed/scope_blocked/worktree_error).
# side_effects: Creates worktree, publishes Prefect artifact (best-effort).
# emitted_logs: Prefect flow/task logs.
# error_behavior: Domain errors (scope_blocked) return as domain_status, not exceptions.
# END_MODULE_CONTRACT

# START_MODULE_MAP
# mapping:
#   - flow: worktree_scope_lifecycle_flow
#   - task: evaluate_worktree_scope_task
#   - task: publish_worktree_scope_artifact_task
# END_MODULE_MAP

from __future__ import annotations

from pathlib import Path
from typing import Any

from prefect_grace.prefect_compat import flow, get_run_logger, task


# START_FUNCTION_CONTRACT
# name: evaluate_worktree_scope_task
# purpose: Prefect task wrapper for evaluate_worktree_scope lifecycle gate.
# inputs:
#   packet_file: Path - Path to EXECUTION_PACKET.md.
#   repo_root: Path - Repository root directory.
#   worktree_root: Path - Worktree root directory.
#   project_key: str - Project key for branch naming.
#   packet_id: str - Packet ID.
#   attempt: int - Attempt number.
#   base_ref: str - Base git ref to branch from.
#   keep_on_failure: bool - If True, preserve worktree on block/error (default True).
# returns: dict[str, Any] - Lifecycle result as dict (from WorktreeScopeLifecycleResult.to_dict()).
# side_effects: Creates worktree if needed, preserves on block/error by default.
# emitted_logs: Task logs via Prefect logger.
# error_behavior: Returns domain errors as dict with status field, raises on unexpected errors.
# END_FUNCTION_CONTRACT
@task(name="evaluate-worktree-scope")
def evaluate_worktree_scope_task(
    *,
    packet_file: Path,
    repo_root: Path,
    worktree_root: Path,
    project_key: str,
    packet_id: str,
    attempt: int,
    base_ref: str,
    keep_on_failure: bool = True,
) -> dict[str, Any]:
    """
    Evaluate worktree scope lifecycle gate.

    Calls evaluate_worktree_scope() and returns result as dict.
    Domain errors (scope_blocked, worktree_error) are returned as status values,
    not raised as exceptions.
    """
    from prefect_grace.platform.worktree_scope_lifecycle import evaluate_worktree_scope

    logger = get_run_logger()
    logger.info(
        f"Evaluating worktree scope lifecycle: packet_id={packet_id}, attempt={attempt}"
    )

    result = evaluate_worktree_scope(
        packet_file=packet_file,
        repo_root=repo_root,
        worktree_root=worktree_root,
        project_key=project_key,
        packet_id=packet_id,
        attempt=attempt,
        base_ref=base_ref,
        keep_on_failure=keep_on_failure,
    )

    logger.info(f"Lifecycle evaluation complete: status={result.status}")

    return result.to_dict()


# START_FUNCTION_CONTRACT
# name: publish_worktree_scope_artifact_task
# purpose: Prefect task wrapper for artifact publication (best-effort).
# inputs:
#   result: dict[str, Any] - Lifecycle result dict from evaluate_worktree_scope_task.
# returns: list[str] - List of artifact IDs (empty if publication unavailable/failed).
# side_effects: Publishes Prefect markdown artifact if available.
# emitted_logs: Task logs via Prefect logger.
# error_behavior: Returns empty list on failure, does not raise.
# END_FUNCTION_CONTRACT
@task(name="publish-worktree-scope-artifact")
def publish_worktree_scope_artifact_task(result: dict[str, Any]) -> list[str]:
    """
    Publish worktree scope lifecycle artifact (best-effort).

    Calls publish_worktree_scope_lifecycle_artifact() and returns artifact IDs.
    Publication failure returns empty list, does not raise exception.
    """
    from prefect_grace.tasks.worktree_scope_artifacts import (
        publish_worktree_scope_lifecycle_artifact,
    )

    logger = get_run_logger()
    logger.info("Publishing worktree scope lifecycle artifact")

    try:
        artifact_ids = publish_worktree_scope_lifecycle_artifact(result)
        if artifact_ids:
            logger.info(f"Published {len(artifact_ids)} artifact(s)")
        else:
            logger.info("Artifact publication unavailable or returned no IDs")
        return artifact_ids
    except Exception as e:
        logger.warning(f"Artifact publication failed: {e}")
        return []


# START_FUNCTION_CONTRACT
# name: worktree_scope_lifecycle_flow
# purpose: Prefect flow exposing worktree scope lifecycle gate for operator visibility.
# inputs:
#   packet_file: str - Path to EXECUTION_PACKET.md.
#   repo_root: str - Repository root directory.
#   worktree_root: str - Worktree root directory.
#   project_key: str - Project key for branch naming.
#   packet_id: str - Packet ID.
#   attempt: int - Attempt number.
#   base_ref: str - Base git ref to branch from.
#   keep_on_failure: bool - If True, preserve worktree on block/error (default True).
# returns: dict[str, Any] - Flow result with domain_status, packet_id, attempt, artifact_ids, scope_guard.
# side_effects: Creates worktree, publishes artifact (best-effort).
# emitted_logs: Flow and task logs via Prefect logger.
# error_behavior: Domain errors return as domain_status field, unexpected errors may fail flow.
# END_FUNCTION_CONTRACT
@flow(
    name="prefect-grace-worktree-scope-lifecycle",
    flow_run_name="worktree-scope:{packet_id}:attempt-{attempt}",
)
def worktree_scope_lifecycle_flow(
    *,
    packet_file: str,
    repo_root: str,
    worktree_root: str,
    project_key: str,
    packet_id: str,
    attempt: int,
    base_ref: str,
    keep_on_failure: bool = True,
) -> dict[str, Any]:
    """
    Prefect flow for worktree scope lifecycle evaluation.

    Flow steps:
    1. Evaluate worktree scope lifecycle gate
    2. Publish markdown artifact (best-effort)
    3. Return domain_status and lifecycle details

    Domain status values:
    - passed: All changed files within allowed scope, no frozen violations
    - scope_blocked: Scope violations detected (frozen or outside allowed)
    - worktree_error: Packet parse, worktree, or scope validation error

    Flow completes successfully even when domain_status=scope_blocked.
    Scope blockers are domain outcomes, not Python exceptions.

    Returns:
        dict with keys:
        - ok: bool - True if domain_status=passed
        - domain_status: str - passed/scope_blocked/worktree_error
        - packet_id: str
        - attempt: int
        - worktree_path: str
        - branch_name: str
        - changed_files: list[str]
        - scope_guard: dict
        - artifact_ids: list[str]
        - artifact_error: str | None (if artifact publication failed)
    """
    logger = get_run_logger()
    logger.info(
        f"Starting worktree scope lifecycle flow: packet_id={packet_id}, attempt={attempt}"
    )

    # Step 1: Evaluate lifecycle gate
    lifecycle_result = evaluate_worktree_scope_task(
        packet_file=Path(packet_file),
        repo_root=Path(repo_root),
        worktree_root=Path(worktree_root),
        project_key=project_key,
        packet_id=packet_id,
        attempt=attempt,
        base_ref=base_ref,
        keep_on_failure=keep_on_failure,
    )

    # Step 2: Publish artifact (best-effort)
    artifact_ids = publish_worktree_scope_artifact_task(lifecycle_result)

    # Step 3: Build flow result
    flow_result = {
        "ok": lifecycle_result["ok"],
        "domain_status": lifecycle_result["status"],
        "packet_id": lifecycle_result["packet_id"],
        "attempt": lifecycle_result["attempt"],
        "worktree_path": lifecycle_result["worktree_path"],
        "branch_name": lifecycle_result["branch_name"],
        "changed_files": lifecycle_result["changed_files"],
        "scope_guard": lifecycle_result["scope_guard"],
        "artifact_ids": artifact_ids,
    }

    # Add artifact_error if publication returned empty list
    if not artifact_ids:
        flow_result["artifact_error"] = "Artifact publication unavailable or failed"

    logger.info(
        f"Flow complete: domain_status={flow_result['domain_status']}, "
        f"artifacts={len(artifact_ids)}"
    )

    return flow_result
