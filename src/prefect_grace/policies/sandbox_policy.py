"""
Sandbox bypass policy enforcement.

This module implements a hard policy gate for dangerous sandbox bypass
(danger-full-access) with audit logging and configuration-based control.
"""

import os
from typing import Any


class SandboxBypassDenied(Exception):
    """Raised when sandbox bypass is denied by policy."""
    pass


def check_sandbox_bypass_allowed(
    packet_id: str,
    reason: str,
    project_config: dict[str, Any] | None = None,
) -> tuple[bool, str]:
    """
    Check if sandbox bypass is allowed by policy.

    Policy precedence (highest to lowest):
    1. GRACE_ALLOW_SANDBOX_BYPASS environment variable
    2. project_config["security"]["allow_sandbox_bypass"]
    3. Default: DENY

    Args:
        packet_id: Packet identifier for audit trail
        reason: Human-readable reason for bypass request
        project_config: Project configuration dict (optional)

    Returns:
        Tuple of (allowed: bool, policy_reason: str)
        - If allowed: (True, "Allowed by <source>")
        - If denied: (False, "Sandbox bypass not allowed. Set...")
    """
    # Check environment variable (highest priority)
    env_value = os.environ.get("GRACE_ALLOW_SANDBOX_BYPASS", "").lower()
    if env_value in ("true", "1", "yes"):
        return (True, "Allowed by GRACE_ALLOW_SANDBOX_BYPASS environment variable")

    # Check project config
    if project_config is not None:
        security = project_config.get("security", {})
        if isinstance(security, dict):
            allow_bypass = security.get("allow_sandbox_bypass", False)
            if allow_bypass is True:
                return (True, "Allowed by project config security.allow_sandbox_bypass")

    # Default: DENY
    denial_message = (
        "Sandbox bypass not allowed. "
        "Set GRACE_ALLOW_SANDBOX_BYPASS=true environment variable "
        "or add 'security.allow_sandbox_bypass: true' to project.yaml"
    )
    return (False, denial_message)


def require_sandbox_bypass_allowed(
    packet_id: str,
    reason: str,
    project_config: dict[str, Any] | None = None,
) -> None:
    """
    Require sandbox bypass to be allowed by policy, raise if denied.

    Args:
        packet_id: Packet identifier for audit trail
        reason: Human-readable reason for bypass request
        project_config: Project configuration dict (optional)

    Raises:
        SandboxBypassDenied: If policy denies the bypass
    """
    allowed, policy_reason = check_sandbox_bypass_allowed(
        packet_id=packet_id,
        reason=reason,
        project_config=project_config,
    )

    if not allowed:
        raise SandboxBypassDenied(f"Sandbox bypass denied: {policy_reason}")
