# ############################################################################
# AI_HEADER: verifier_reviewer_handoff_flow
# ROLE: Prefect flow for verifier-reviewer handoff execution.
# ############################################################################

# START_MODULE_CONTRACT
# purpose: Prefect flow wrapper for verifier-reviewer handoff.
# inputs: Packet paths, coder result, launcher functions.
# returns: PacketHandoffResult dict.
# side_effects: Launches verifier/reviewer agents, writes artifacts.
# emitted_logs: Prefect flow logs.
# error_behavior: Returns handoff_error status on unexpected errors.
# END_MODULE_CONTRACT

# START_MODULE_MAP
# mapping:
#   - flow: verifier_reviewer_handoff_flow
# END_MODULE_MAP

from __future__ import annotations

from pathlib import Path
from typing import Any, Callable

from prefect_grace.prefect_compat import flow, get_run_logger
from prefect_grace.platform.verifier_reviewer_handoff import run_verifier_reviewer_handoff

# START_BLOCK: handoff_flow

# START_FUNCTION_CONTRACT
# name: verifier_reviewer_handoff_flow
# purpose: Prefect flow for verifier-reviewer handoff execution.
# inputs:
#   packet_dir: Path to packet directory.
#   packet_file: Path to EXECUTION_PACKET.md.
#   attempt: Attempt number.
#   coder_result: Coder managed packet result dict.
#   verifier_launcher: Function to launch verifier agent.
#   reviewer_launcher: Function to launch reviewer agent.
#   project: Optional project context.
#   dry_run: Whether to run in dry-run mode (default True).
# returns: PacketHandoffResult dict.
# side_effects: Launches agents, writes artifacts.
# emitted_logs: Prefect flow logs.
# error_behavior: Returns handoff_error status on unexpected errors.
# END_FUNCTION_CONTRACT
@flow(
    name="prefect-grace-verifier-reviewer-handoff",
    flow_run_name="handoff:{packet_id}:attempt-{attempt}",
)
def verifier_reviewer_handoff_flow(
    packet_dir: Path | str,
    packet_file: Path | str,
    attempt: int,
    coder_result: dict[str, Any],
    verifier_launcher: Callable[..., dict[str, Any]],
    reviewer_launcher: Callable[..., dict[str, Any]],
    project: Any | None = None,
    dry_run: bool = True,
) -> dict[str, Any]:
    """Execute verifier-reviewer handoff flow.

    Args:
        packet_dir: Path to packet directory
        packet_file: Path to EXECUTION_PACKET.md
        attempt: Attempt number
        coder_result: Coder managed packet result
        verifier_launcher: Function to launch verifier agent
        reviewer_launcher: Function to launch reviewer agent
        project: Optional project context
        dry_run: Whether to run in dry-run mode

    Returns:
        PacketHandoffResult dict with handoff outcome
    """
    logger = get_run_logger()

    packet_dir = Path(packet_dir)
    packet_file = Path(packet_file)
    packet_id = coder_result.get("packet_id", "unknown")

    logger.info(f"Starting verifier-reviewer handoff for {packet_id}, attempt {attempt}")
    logger.info(f"Dry run: {dry_run}")

    try:
        result = run_verifier_reviewer_handoff(
            packet_dir=packet_dir,
            packet_file=packet_file,
            attempt=attempt,
            coder_result=coder_result,
            verifier_launcher=verifier_launcher,
            reviewer_launcher=reviewer_launcher,
            project=project,
            dry_run=dry_run,
        )

        logger.info(f"Handoff completed with status: {result.domain_status}")

        return result.to_dict()

    except Exception as e:
        logger.error(f"Handoff flow failed: {e}")

        # Return handoff_error result
        from prefect_grace.platform.verifier_reviewer_handoff import (
            PacketHandoffResult,
            HandoffAgentResult,
        )

        error_result = PacketHandoffResult(
            ok=False,
            domain_status="handoff_error",
            packet_id=packet_id,
            attempt=attempt,
            verifier=HandoffAgentResult(
                ok=False,
                role="verifier",
                packet_id=packet_id,
                raw_output="",
                parsed_json=None,
                marker_found=False,
                errors=[f"Flow execution failed: {e}"],
            ),
            reviewer=None,
            evidence_manifest_path=None,
            review_path=None,
            rework_path=None,
            blocker_reason=f"Flow execution failed: {e}",
        )

        return error_result.to_dict()

# END_BLOCK: handoff_flow
