# AI_HEADER: codex_launcher_helpers
# START_MODULE_CONTRACT
# END_MODULE_CONTRACT
# START_MODULE_MAP
# END_MODULE_MAP

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

from prefect_grace.platform.state_store import PacketRegistryStore

STATE_ROOT = Path(__file__).resolve().parents[2] / "state"
DEFAULT_STALL_TIMEOUT_SECONDS = 900.0
DEFAULT_MAX_AUTO_RESUME_ATTEMPTS = 1

def _normalize_resume_strategy(value: Any) -> str:
    strategy = str(value or "none").strip().lower().replace("-", "_")
    if strategy not in {"none", "feature_role", "packet_parent"}:
        return "none"
    return strategy

def _normalize_non_negative_int(value: Any, *, default: int = 0) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return default
    return max(parsed, 0)

def _normalize_positive_float(value: Any) -> float | None:
    if value in (None, ""):
        return None
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return None
    if parsed <= 0:
        return None
    return parsed

def _check_resume_allowed(packet_id: str, resume_strategy: str, logger: logging.Logger | None = None) -> bool:
    """
    Check if resume is allowed for this packet based on registry state.

    Returns True if resume is allowed, False if blocked by source hash change.
    For managed resume strategies (feature_role, packet_parent), registry errors fail closed.
    """
    is_managed_strategy = resume_strategy in {"feature_role", "packet_parent"}

    try:
        registry = PacketRegistryStore(STATE_ROOT)
        packet_record = registry.load_packet(packet_id)

        if packet_record is None:
            # No registry record, allow resume (backward compatibility)
            return True

        resume_allowed = packet_record.get("resume_allowed")
        if resume_allowed is False:
            resume_block_reason = packet_record.get("resume_block_reason", "unknown")
            if logger is not None:
                logger.warning(
                    "Resume blocked for packet=%s reason=%s. Forcing fresh session.",
                    packet_id,
                    resume_block_reason,
                )
            return False

        # resume_allowed is True or None (not set), allow resume
        return True
    except Exception as e:
        # For managed strategies, fail closed on registry errors
        if is_managed_strategy:
            if logger is not None:
                logger.error(
                    "Registry error for managed resume strategy packet=%s strategy=%s error=%s. Blocking resume for safety.",
                    packet_id,
                    resume_strategy,
                    str(e),
                )
            return False

        # For legacy/none strategy, fail open for backward compatibility
        if logger is not None:
            logger.warning(
                "Failed to check resume_allowed for packet=%s error=%s. Allowing resume (legacy strategy).",
                packet_id,
                str(e),
            )
        return True

def _resolve_resume_strategy(packet: dict[str, Any], role_defaults: dict[str, Any]) -> str:
    execution_hints = dict(packet.get("execution_hints") or {})
    return _normalize_resume_strategy(execution_hints.get("resume_strategy") or role_defaults.get("resume_strategy"))

def _resolve_stall_timeout_seconds(
    packet: dict[str, Any],
    role_defaults: dict[str, Any],
    explicit_timeout: float | None,
) -> float | None:
    if explicit_timeout is not None:
        return explicit_timeout
    execution_hints = dict(packet.get("execution_hints") or {})
    resolved = _normalize_positive_float(
        execution_hints.get("stall_timeout_seconds", role_defaults.get("stall_timeout_seconds"))
    )
    if resolved is not None:
        return resolved
    return DEFAULT_STALL_TIMEOUT_SECONDS

def _resolve_max_auto_resume_attempts(packet: dict[str, Any], role_defaults: dict[str, Any]) -> int:
    execution_hints = dict(packet.get("execution_hints") or {})
    return _normalize_non_negative_int(
        execution_hints.get("max_auto_resume_attempts", role_defaults.get("max_auto_resume_attempts")),
        default=0,
    )
