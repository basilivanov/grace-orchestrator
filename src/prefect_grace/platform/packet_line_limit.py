# ############################################################################
# AI_HEADER: packet_line_limit
# ROLE: Guards against oversized EXECUTION_PACKET.md files.
# ############################################################################

# START_MODULE_CONTRACT
# purpose: Check EXECUTION_PACKET.md line count and flag oversized packets.
# inputs: Path to EXECUTION_PACKET.md file.
# returns: Dict with line count, status, and warnings.
# side_effects: None.
# emitted_logs: None.
# error_behavior: Returns error status if file not found.
# END_MODULE_CONTRACT

# START_MODULE_MAP
# mapping:
#   - function: check_line_limit
# END_MODULE_MAP

from __future__ import annotations

from pathlib import Path
from typing import Any

#START_BLOCK_LINE_LIMIT_GUARD
# Line limit thresholds
RECOMMENDED_MAX_LINES = 400
WARNING_THRESHOLD = 600
BLOCKER_THRESHOLD = 1000

# START_FUNCTION_CONTRACT
# name: check_line_limit
# purpose: Check EXECUTION_PACKET.md line count against thresholds.
# inputs:
#   packet_file: Path to EXECUTION_PACKET.md file.
#   strict: If True, treat warnings as errors for new packets.
# returns: Dict with line_count, status (ok/warning/blocker), and messages.
# side_effects: None.
# emitted_logs: None.
# error_behavior: Returns error status if file not found.
# END_FUNCTION_CONTRACT
def check_line_limit(
    packet_file: Path,
    strict: bool = False,
) -> dict[str, Any]:
    if not packet_file.exists():
        return {
            "line_count": 0,
            "status": "error",
            "messages": [f"File not found: {packet_file}"],
        }

    lines = packet_file.read_text(encoding="utf-8").splitlines()
    line_count = len(lines)

    messages = []
    status = "ok"

    if line_count > BLOCKER_THRESHOLD:
        status = "blocker"
        messages.append(
            f"BLOCKER: EXECUTION_PACKET.md has {line_count} lines "
            f"(threshold: {BLOCKER_THRESHOLD}). "
            "This is a context-risk blocker. "
            "Move runtime history to SUMMARY.md, REVIEWS/, EVIDENCE/, REWORK/."
        )
    elif line_count > WARNING_THRESHOLD:
        status = "warning" if not strict else "blocker"
        messages.append(
            f"WARNING: EXECUTION_PACKET.md has {line_count} lines "
            f"(threshold: {WARNING_THRESHOLD}). "
            "Consider moving runtime artifacts to separate files."
        )
    elif line_count > RECOMMENDED_MAX_LINES:
        messages.append(
            f"INFO: EXECUTION_PACKET.md has {line_count} lines "
            f"(recommended max: {RECOMMENDED_MAX_LINES}). "
            "This is acceptable but consider keeping it shorter."
        )

    return {
        "line_count": line_count,
        "status": status,
        "messages": messages,
        "thresholds": {
            "recommended": RECOMMENDED_MAX_LINES,
            "warning": WARNING_THRESHOLD,
            "blocker": BLOCKER_THRESHOLD,
        },
    }

#END_BLOCK_LINE_LIMIT_GUARD
