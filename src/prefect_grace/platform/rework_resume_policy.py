# ############################################################################
# AI_HEADER: rework_resume_policy
# ROLE: Decides whether coder rework can resume or needs fresh context.
# ############################################################################

# START_MODULE_CONTRACT
# purpose: Implement deterministic resume policy based on source hash changes.
# inputs: Packet ID, current/last source hashes, requested mode, rework reason.
# returns: ReworkResumeDecision with resume_allowed and recommended mode.
# side_effects: None (pure policy function).
# emitted_logs: None.
# error_behavior: Returns decision_required for ambiguous cases.
# END_MODULE_CONTRACT

# START_MODULE_MAP
# mapping:
#   - class: ReworkResumeDecision
#   - function: decide_rework_resume
# END_MODULE_MAP

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from prefect_grace.platform.packet_artifact_layout import resolve_packet_layout
from prefect_grace.platform.context_bundle import build_context_bundle

#START_BLOCK_MODELS
@dataclass
class ReworkResumeDecision:
    """
    Resume decision for coder rework sessions.

    Determines whether a coder can resume an existing session or must start
    with fresh bounded context based on source contract changes.
    """
    packet_id: str
    current_source_hash: str
    last_executed_source_hash: str | None
    resume_allowed: bool
    resume_block_reason: str | None
    recommended_rework_mode: str
    context_mode: str
    context_paths: list[str]

#END_BLOCK_MODELS
#START_BLOCK_POLICY
# START_FUNCTION_CONTRACT
# name: decide_rework_resume
# purpose: Decide whether coder rework can resume based on source hash changes.
# inputs:
#   packet_id: Packet identifier.
#   current_source_hash: Current EXECUTION_PACKET.md source hash.
#   last_executed_source_hash: Source hash from last coder attempt (may be None).
#   requested_rework_mode: Requested mode (light_resume, bounded_fresh, etc).
#   rework_reason: Reason for rework (contract_changed, reviewer_feedback, etc).
#   packet_dir: Path to packet directory for context bundle.
#   latest_coder_session_id: Latest coder session ID (may be None).
# returns: ReworkResumeDecision with resume decision and context paths.
# side_effects: None.
# emitted_logs: None.
# error_behavior: Returns decision_required for ambiguous cases.
# END_FUNCTION_CONTRACT
def decide_rework_resume(
    packet_id: str,
    current_source_hash: str,
    last_executed_source_hash: str | None,
    requested_rework_mode: str,
    rework_reason: str,
    packet_dir: Path,
    latest_coder_session_id: str | None = None,
) -> ReworkResumeDecision:
    # Rule 1: Missing last executed hash -> no resume
    if last_executed_source_hash is None:
        layout = resolve_packet_layout(packet_dir)
        context_paths = [str(p) for p in build_context_bundle(packet_dir, role="coder", mode="normal")]

        return ReworkResumeDecision(
            packet_id=packet_id,
            current_source_hash=current_source_hash,
            last_executed_source_hash=None,
            resume_allowed=False,
            resume_block_reason="missing_last_executed_hash",
            recommended_rework_mode="bounded_fresh",
            context_mode="bounded_fresh",
            context_paths=context_paths,
        )

    # Rule 2: Source hash changed -> contract changed -> no resume
    if current_source_hash != last_executed_source_hash:
        layout = resolve_packet_layout(packet_dir)
        context_paths = [str(p) for p in build_context_bundle(packet_dir, role="coder", mode="normal")]

        return ReworkResumeDecision(
            packet_id=packet_id,
            current_source_hash=current_source_hash,
            last_executed_source_hash=last_executed_source_hash,
            resume_allowed=False,
            resume_block_reason="contract_changed",
            recommended_rework_mode="bounded_fresh",
            context_mode="bounded_fresh",
            context_paths=context_paths,
        )

    # Rule 3: Same hash + light_resume requested -> check session state
    if requested_rework_mode == "light_resume":
        # Check if session exists
        if latest_coder_session_id is None:
            layout = resolve_packet_layout(packet_dir)
            context_paths = [str(p) for p in build_context_bundle(packet_dir, role="coder", mode="normal")]

            return ReworkResumeDecision(
                packet_id=packet_id,
                current_source_hash=current_source_hash,
                last_executed_source_hash=last_executed_source_hash,
                resume_allowed=False,
                resume_block_reason="missing_session",
                recommended_rework_mode="bounded_fresh",
                context_mode="bounded_fresh",
                context_paths=context_paths,
            )

        # Check if reason is reviewer implementation feedback
        reviewer_reasons = [
            "reviewer_feedback",
            "implementation_fix",
            "small_adjustment",
            "missing_selector",
            "assertion_mismatch",
            "typo_fix",
        ]

        if any(reason in rework_reason.lower() for reason in reviewer_reasons):
            return ReworkResumeDecision(
                packet_id=packet_id,
                current_source_hash=current_source_hash,
                last_executed_source_hash=last_executed_source_hash,
                resume_allowed=True,
                resume_block_reason=None,
                recommended_rework_mode="light_resume",
                context_mode="normal_latest",
                context_paths=[],  # Resume uses existing session context
            )

    # Rule 4: Same hash but not light_resume -> bounded fresh
    layout = resolve_packet_layout(packet_dir)
    context_paths = [str(p) for p in build_context_bundle(packet_dir, role="coder", mode="normal")]

    return ReworkResumeDecision(
        packet_id=packet_id,
        current_source_hash=current_source_hash,
        last_executed_source_hash=last_executed_source_hash,
        resume_allowed=False,
        resume_block_reason="decision_required",
        recommended_rework_mode="bounded_fresh",
        context_mode="bounded_fresh",
        context_paths=context_paths,
    )

#END_BLOCK_POLICY
