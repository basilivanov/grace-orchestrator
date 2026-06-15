from __future__ import annotations

from typing import Any

from grace_control.core.uid import generate_unique_id, new_packet_uid
from grace_control.db.schema import Packet, PacketState
from grace_control.core.structured_logger import GraceLogger

_log = GraceLogger("rework_packet_service")

RUNTIME_FAILURE_CODES = frozenset({
    "auth_error",
    "timeout",
    "worktree_missing",
    "not_git",
    "AGENT_WORKTREE_NOT_GIT",
    "AGENT_NO_CHANGES_PRODUCED",
    "AGENT_DIFF_INSPECTION_FAILED",
    "AGENT_CHANGED_OUT_OF_SCOPE",
})


def _is_runtime_failure(result_json: dict[str, Any] | None) -> bool:
    if not result_json:
        return False
    diagnostics = result_json.get("diagnostics") or {}
    failure_code = diagnostics.get("failure_code", "") or result_json.get("failure_code", "")
    if failure_code in RUNTIME_FAILURE_CODES:
        return True
    return False


def create_rework_packet(
    db,
    *,
    original_packet_id: str,
    feature_id: str,
    wave_id: str,
    original_spec: dict[str, Any],
    acceptance_profile: str,
    title: str,
    slug: str,
    max_attempts: int,
    verdict_source: str,
    summary: str,
    blocking_issues: list[str],
    coder_instructions: list[str] | None = None,
) -> Packet:
    pkt_id = generate_unique_id(db, Packet, new_packet_uid)

    allowed_write_scope = original_spec.get("scope", []) or original_spec.get("allowed_write_scope", [])
    frozen_scope = original_spec.get("frozen_scope", [])
    verification = original_spec.get("verification", {})
    target_repo_root = original_spec.get("target_repo_root", "")
    workspace_mode = original_spec.get("workspace_mode", "")

    if not allowed_write_scope:
        allowed_write_scope = original_spec.get("allowed_paths", ["src/grace_control/"])
    if not frozen_scope:
        frozen_scope = original_spec.get("restricted_paths",
                                          original_spec.get("forbidden_paths", ["docs/archived/"]))

    rework_spec: dict[str, Any] = {
        "origin": "review_rework",
        "parent_packet_id": original_packet_id,
        "original_packet_id": original_packet_id,
        "title": f"Rework: {title}",
        "description": f"Review rework for {original_packet_id}",
        "scope": allowed_write_scope,
        "frozen_scope": frozen_scope,
        "verification": verification,
        "target_repo_root": target_repo_root,
        "priority": "immediate",
        "acceptance_profile": acceptance_profile,
        "rework_source": verdict_source,
        "rework_summary": summary,
        "blocking_issues": blocking_issues,
        "coder_instructions": coder_instructions or [],
        "rework_prompt": (
            "This is a review rework packet.\n"
            "Do not redesign.\n"
            "Only fix the reviewer blocking issues.\n"
            "Stay inside allowed scope.\n"
            "Preserve original intent."
        ),
    }
    if workspace_mode:
        rework_spec["workspace_mode"] = workspace_mode

    packet = Packet(
        id=pkt_id,
        feature_id=feature_id,
        wave_id=wave_id,
        slug=f"{slug}-rework",
        title=f"Rework: {title}",
        spec_json=rework_spec,
        state=PacketState.READY.value,
        acceptance_profile=acceptance_profile,
        attempt_count=0,
        max_attempts=max_attempts,
    )
    db.add(packet)

    _log.info("rework_packet_created",
              original_packet_id=original_packet_id,
              rework_packet_id=pkt_id,
              verdict_source=verdict_source,
              summary=summary[:200] if summary else "")

    return packet
