"""
Audit logger for security-sensitive operations.

Logs sandbox bypass attempts to JSONL format for compliance and security review.
"""

import json
import logging
import os
import socket
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

DEFAULT_AUDIT_LOG_PATH = "/var/lib/grace-orchestrator/audit/sandbox_bypass.jsonl"


def log_sandbox_bypass_attempt(
    packet_id: str,
    allowed: bool,
    reason: str,
    policy_reason: str,
    audit_log_path: str | None = None,
) -> None:
    """
    Log a sandbox bypass attempt to JSONL audit file.

    This function implements graceful degradation - if logging fails,
    it logs a warning but does not fail the operation.

    Args:
        packet_id: Packet identifier
        allowed: Whether the bypass was allowed
        reason: Human-readable reason for bypass request
        policy_reason: Policy decision reason
        audit_log_path: Path to audit log file (default: DEFAULT_AUDIT_LOG_PATH)
    """
    if audit_log_path is None:
        audit_log_path = DEFAULT_AUDIT_LOG_PATH

    try:
        # Create parent directories if needed
        log_path = Path(audit_log_path)
        log_path.parent.mkdir(parents=True, exist_ok=True)

        # Build audit entry
        entry: dict[str, Any] = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "packet_id": packet_id,
            "allowed": allowed,
            "reason": reason,
            "policy_reason": policy_reason,
            "hostname": socket.gethostname(),
            "user": os.environ.get("USER", "unknown"),
        }

        # Append to JSONL file
        with open(log_path, "a") as f:
            f.write(json.dumps(entry) + "\n")

    except Exception as e:
        # Graceful degradation - log warning but don't fail operation
        logger.warning(
            "Failed to write sandbox bypass audit log to %s: %s",
            audit_log_path,
            e,
        )
