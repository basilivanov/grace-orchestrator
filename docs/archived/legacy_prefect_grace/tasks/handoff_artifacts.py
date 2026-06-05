# ############################################################################
# AI_HEADER: handoff_artifacts
# ROLE: Helpers for writing verifier/reviewer handoff artifacts.
# ############################################################################

# START_MODULE_CONTRACT
# purpose: Provide helpers for writing handoff artifacts (evidence, review, rework).
# inputs: Packet directory, artifact data.
# returns: Paths to written artifact files.
# side_effects: Creates artifact directories and files.
# emitted_logs: None.
# error_behavior: Raises IOError if write fails.
# END_MODULE_CONTRACT

# START_MODULE_MAP
# mapping:
#   - function: write_handoff_summary
#   - function: format_evidence_summary
#   - function: format_review_summary
# END_MODULE_MAP

from __future__ import annotations

from pathlib import Path
from typing import Any

from prefect_grace.platform.packet_artifacts import write_review, write_evidence, write_rework

# START_BLOCK: handoff_helpers

# START_FUNCTION_CONTRACT
# name: write_handoff_summary
# purpose: Update SUMMARY.md with latest handoff status.
# inputs:
#   packet_dir: Path to packet directory.
#   handoff_result: PacketHandoffResult dict.
# returns: Path to updated SUMMARY.md.
# side_effects: Creates or updates SUMMARY.md.
# emitted_logs: None.
# error_behavior: Raises IOError if write fails.
# END_FUNCTION_CONTRACT
def write_handoff_summary(
    packet_dir: Path,
    handoff_result: dict[str, Any],
) -> Path:
    """Update SUMMARY.md with latest handoff status."""
    summary_content = f"""# Packet Summary

**Packet ID:** {handoff_result['packet_id']}
**Attempt:** {handoff_result['attempt']}
**Status:** {handoff_result['domain_status']}

## Verifier Result

- **OK:** {handoff_result['verifier']['ok']}
- **Marker Found:** {handoff_result['verifier']['marker_found']}
- **Errors:** {len(handoff_result['verifier']['errors'])}

## Reviewer Result

"""

    if handoff_result['reviewer']:
        summary_content += f"""- **OK:** {handoff_result['reviewer']['ok']}
- **Marker Found:** {handoff_result['reviewer']['marker_found']}
- **Errors:** {len(handoff_result['reviewer']['errors'])}
"""
    else:
        summary_content += "- Not executed (verifier failed)\n"

    summary_content += f"""
## Artifacts

- **Evidence Manifest:** {handoff_result['evidence_manifest_path'] or 'None'}
- **Review:** {handoff_result['review_path'] or 'None'}
- **Rework:** {handoff_result['rework_path'] or 'None'}
"""

    summary_path = packet_dir / "SUMMARY.md"
    summary_path.write_text(summary_content, encoding="utf-8")

    return summary_path


# START_FUNCTION_CONTRACT
# name: format_evidence_summary
# purpose: Format evidence manifest for human-readable summary.
# inputs:
#   evidence_json: Parsed evidence manifest dict.
# returns: Formatted summary string.
# side_effects: None (pure function).
# emitted_logs: None.
# error_behavior: Returns empty string if evidence_json is None.
# END_FUNCTION_CONTRACT
def format_evidence_summary(evidence_json: dict[str, Any] | None) -> str:
    """Format evidence manifest for human-readable summary."""
    if not evidence_json:
        return "No evidence manifest"

    lines = ["## Evidence Summary\n"]

    requirement_results = evidence_json.get("requirement_results", [])
    if requirement_results:
        lines.append(f"**Total Requirements:** {len(requirement_results)}\n")

        status_counts = {}
        for req in requirement_results:
            status = req.get("status", "unknown")
            status_counts[status] = status_counts.get(status, 0) + 1

        lines.append("\n**Status Breakdown:**\n")
        for status, count in sorted(status_counts.items()):
            lines.append(f"- {status}: {count}\n")

    return "".join(lines)


# START_FUNCTION_CONTRACT
# name: format_review_summary
# purpose: Format reviewer decision for human-readable summary.
# inputs:
#   decision_json: Parsed reviewer decision dict.
# returns: Formatted summary string.
# side_effects: None (pure function).
# emitted_logs: None.
# error_behavior: Returns empty string if decision_json is None.
# END_FUNCTION_CONTRACT
def format_review_summary(decision_json: dict[str, Any] | None) -> str:
    """Format reviewer decision for human-readable summary."""
    if not decision_json:
        return "No reviewer decision"

    lines = ["## Review Summary\n"]

    verdict = decision_json.get("packet_verdict", "unknown")
    lines.append(f"**Verdict:** {verdict}\n")

    route_classification = decision_json.get("route_classification")
    if route_classification:
        lines.append(f"**Route Classification:** {route_classification}\n")

    rework_mode = decision_json.get("rework_mode")
    if rework_mode:
        lines.append(f"**Rework Mode:** {rework_mode}\n")

    reasons = decision_json.get("reasons", [])
    if reasons:
        lines.append("\n**Reasons:**\n")
        for reason in reasons:
            lines.append(f"- {reason}\n")

    return "".join(lines)

# END_BLOCK: handoff_helpers
