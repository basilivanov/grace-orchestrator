# ############################################################################
# AI_HEADER: packet_summary
# ROLE: Writes and updates SUMMARY.md for GRACE packet current state.
# ############################################################################

# START_MODULE_CONTRACT
# purpose: Write/update SUMMARY.md with bounded current state (under 120 lines).
# inputs: Packet directory, status dict with current state.
# returns: Path to written SUMMARY.md.
# side_effects: Writes SUMMARY.md file.
# emitted_logs: None.
# error_behavior: Raises IOError if write fails.
# END_MODULE_CONTRACT

# START_MODULE_MAP
# mapping:
#   - function: write_summary
# END_MODULE_MAP

from __future__ import annotations

from pathlib import Path
from typing import Any

from prefect_grace.platform.packet_artifact_layout import (
    resolve_packet_layout,
    latest_review,
    latest_evidence_manifest,
    latest_rework,
)

#START_BLOCK_SUMMARY_WRITER
# START_FUNCTION_CONTRACT
# name: write_summary
# purpose: Write or update SUMMARY.md with current packet state.
# inputs:
#   packet_dir: Path to packet directory.
#   status: Dict with current state (packet_id, current_status, current_attempt, etc).
# returns: Path to written SUMMARY.md.
# side_effects: Writes SUMMARY.md file, overwrites if exists.
# emitted_logs: None.
# error_behavior: Raises IOError if write fails.
# END_FUNCTION_CONTRACT
def write_summary(packet_dir: Path, status: dict[str, Any]) -> Path:
    layout = resolve_packet_layout(packet_dir)

    # Resolve latest artifact paths
    review_path = latest_review(layout)
    evidence_path = latest_evidence_manifest(layout)
    rework_path = latest_rework(layout)

    # Build summary content (bounded, under 120 lines)
    lines = [
        "# Packet Summary",
        "",
        "## Metadata",
        "",
        f"- **packet_id:** `{status.get('packet_id', 'unknown')}`",
        f"- **feature_id:** `{status.get('feature_id', 'unknown')}`",
        f"- **wave_id:** `{status.get('wave_id', 'unknown')}`",
        "",
        "## Current State",
        "",
        f"- **Status:** `{status.get('current_status', 'unknown')}`",
        f"- **Attempt:** `{status.get('current_attempt', 1)}`",
        f"- **Last Updated:** `{status.get('last_updated', 'unknown')}`",
        "",
        "## Latest Artifacts",
        "",
    ]

    if review_path:
        rel_path = review_path.relative_to(packet_dir)
        lines.append(f"- **Latest Review:** `{rel_path}`")
    else:
        lines.append("- **Latest Review:** None")

    if evidence_path:
        rel_path = evidence_path.relative_to(packet_dir)
        lines.append(f"- **Latest Evidence:** `{rel_path}`")
    else:
        lines.append("- **Latest Evidence:** None")

    if rework_path:
        rel_path = rework_path.relative_to(packet_dir)
        lines.append(f"- **Latest Rework:** `{rel_path}`")
    else:
        lines.append("- **Latest Rework:** None")

    lines.extend([
        "",
        "## Open Blockers",
        "",
    ])

    blockers = status.get("open_blockers", [])
    if blockers:
        for blocker in blockers:
            lines.append(f"- {blocker}")
    else:
        lines.append("None")

    lines.extend([
        "",
        "## Next Action",
        "",
        status.get("next_action", "Awaiting controller decision."),
        "",
        "## Latest Verification Summary",
        "",
    ])

    verification = status.get("verification_summary", "No verification run yet.")
    lines.append(verification)

    lines.append("")

    # Write summary (bounded rewrite, not append)
    summary_content = "\n".join(lines)
    layout.summary.write_text(summary_content, encoding="utf-8")

    return layout.summary

#END_BLOCK_SUMMARY_WRITER
