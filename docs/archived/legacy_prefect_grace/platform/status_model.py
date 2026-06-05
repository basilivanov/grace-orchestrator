"""
# ============================================================================
# AI_HEADER: GRACE Status Model Module
# ============================================================================
#
# This module provides a strict, centralized status model for GRACE
# orchestration to prevent drift between source packet intent, runtime
# registry state, and execution domain outcomes.
#
# Key Concepts:
# - Three status layers: SourcePacketStatus, RegistryStatus, DomainStatus
# - Legacy string normalization for backward compatibility
# - Deterministic domain-to-registry transitions
# - No behavior change unless explicitly tested
# - Enums are internal; public JSON outputs remain strings
#
# Module Dependencies:
# - No external GRACE modules (pure status model)
# - Standard library only (enum, dataclasses)
#
# ============================================================================
"""

from enum import Enum
from dataclasses import dataclass
from typing import Optional

# START_MODULE_CONTRACT
# Module: status_model
# Purpose: Centralized status model for GRACE orchestration
# Exports: SourcePacketStatus, RegistryStatus, DomainStatus, StatusTransition,
#          normalize_source_status, normalize_registry_status, normalize_domain_status,
#          apply_domain_result_to_registry, is_terminal_registry_status,
#          is_runnable_registry_status, is_failure_domain_status, is_scope_domain_status
# Dependencies: enum, dataclasses (standard library only)
# Constraints: Fail-closed normalization, no external GRACE modules, backward compatible
# END_MODULE_CONTRACT

# START_MODULE_MAP
# Block: status_enums - SourcePacketStatus, RegistryStatus, DomainStatus enums
# Block: status_transition - StatusTransition dataclass
# Block: normalization - normalize_source_status, normalize_registry_status, normalize_domain_status
# Block: transition_helpers - apply_domain_result_to_registry
# Block: predicates - is_terminal_registry_status, is_runnable_registry_status, is_failure_domain_status, is_scope_domain_status
# END_MODULE_MAP

#START_BLOCK_STATUS_ENUMS
class SourcePacketStatus(str, Enum):
    """Status values that appear in source EXECUTION_PACKET.md files."""
    DRAFT = "draft"
    READY = "ready"
    BLOCKED = "blocked"
    SUPERSEDED = "superseded"
    ACCEPTED = "accepted"  # legacy-compatible only


class RegistryStatus(str, Enum):
    """Runtime registry state for packet execution tracking."""
    READY = "ready"
    READY_FOR_RETRY = "ready_for_retry"
    WAITING_FOR_DEPENDENCIES = "waiting_for_dependencies"
    RUNNING = "running"
    BLOCKED = "blocked"
    CASCADING_BLOCKED = "cascading_blocked"
    ACCEPTED = "accepted"
    CHANGED_AFTER_ACCEPTANCE = "changed_after_acceptance"


class DomainStatus(str, Enum):
    """Execution domain outcome from coder/verifier/reviewer agents."""
    ACCEPTED = "accepted"
    REWORK_REQUIRED = "rework_required"
    BLOCKED = "blocked"
    SCOPE_BLOCKED = "scope_blocked"
    AGENT_FAILED = "agent_failed"
    VERIFIER_FAILED = "verifier_failed"
    REVIEWER_FAILED = "reviewer_failed"
    RUNNER_ERROR = "runner_error"
    HANDOFF_ERROR = "handoff_error"
    CHECK_PASSED = "passed"  # compatibility alias for local gates only

#END_BLOCK_STATUS_ENUMS
#START_BLOCK_STATUS_TRANSITION
@dataclass
class StatusTransition:
    """Result of applying a domain status to registry state."""
    registry_status: RegistryStatus
    reason: str
    is_terminal: bool
    is_failure: bool

#END_BLOCK_STATUS_TRANSITION
#START_BLOCK_NORMALIZATION
# START_FUNCTION_CONTRACT
# Function: normalize_source_status
# Purpose: Normalize source packet status from string or enum to SourcePacketStatus
# Args:
#   - value: SourcePacketStatus | str | None - Source packet status value to normalize
# Returns: SourcePacketStatus - Normalized enum value
# Inputs: value (enum, string, or None)
# Side_effects: None (pure function)
# Emitted_logs: None
# Error_behavior: Never raises, defaults to READY for None/empty/unknown
# Behavior:
#   - If value is already SourcePacketStatus enum, return as-is
#   - If value is known string, map to corresponding enum
#   - If value is None or empty, default to READY (legacy parser behavior)
#   - If value is unknown string, default to READY with warning
# Safety:
#   - Unknown strings default to READY, not ACCEPTED
#   - None/empty defaults to READY for backward compatibility
# END_FUNCTION_CONTRACT
def normalize_source_status(
    value: SourcePacketStatus | str | None
) -> SourcePacketStatus:
    if isinstance(value, SourcePacketStatus):
        return value

    if value is None or value == "":
        return SourcePacketStatus.READY

    # Normalize string to lowercase for comparison
    value_lower = str(value).lower().strip()

    # Map known strings to enums
    mapping = {
        "draft": SourcePacketStatus.DRAFT,
        "ready": SourcePacketStatus.READY,
        "blocked": SourcePacketStatus.BLOCKED,
        "superseded": SourcePacketStatus.SUPERSEDED,
        "accepted": SourcePacketStatus.ACCEPTED,
    }

    if value_lower in mapping:
        return mapping[value_lower]

    # Unknown string defaults to READY
    return SourcePacketStatus.READY


# START_FUNCTION_CONTRACT
# Function: normalize_registry_status
# Purpose: Normalize registry status from string or enum to RegistryStatus
# Args:
#   - value: RegistryStatus | str | None - Registry status value to normalize
# Returns: RegistryStatus - Normalized enum value
# Inputs: value (enum, string, or None)
# Side_effects: None (pure function)
# Emitted_logs: None
# Error_behavior: Never raises, defaults to READY for None/empty, BLOCKED for unknown
# Behavior:
#   - If value is already RegistryStatus enum, return as-is
#   - If value is known string, map to corresponding enum
#   - If value is None or empty, default to READY
#   - If value is unknown string, default to BLOCKED (safe fallback)
# Safety:
#   - Unknown strings default to BLOCKED, not ACCEPTED
#   - None/empty defaults to READY for backward compatibility
# END_FUNCTION_CONTRACT
def normalize_registry_status(
    value: RegistryStatus | str | None
) -> RegistryStatus:
    if isinstance(value, RegistryStatus):
        return value

    if value is None or value == "":
        return RegistryStatus.READY

    # Normalize string to lowercase for comparison
    value_lower = str(value).lower().strip()

    # Map known strings to enums
    mapping = {
        "ready": RegistryStatus.READY,
        "ready_for_retry": RegistryStatus.READY_FOR_RETRY,
        "waiting_for_dependencies": RegistryStatus.WAITING_FOR_DEPENDENCIES,
        "running": RegistryStatus.RUNNING,
        "blocked": RegistryStatus.BLOCKED,
        "cascading_blocked": RegistryStatus.CASCADING_BLOCKED,
        "accepted": RegistryStatus.ACCEPTED,
        "changed_after_acceptance": RegistryStatus.CHANGED_AFTER_ACCEPTANCE,
    }

    if value_lower in mapping:
        return mapping[value_lower]

    # Unknown string defaults to BLOCKED (safe fallback)
    return RegistryStatus.BLOCKED


# START_FUNCTION_CONTRACT
# Function: normalize_domain_status
# Purpose: Normalize domain execution status from string or enum to DomainStatus
# Args:
#   - value: DomainStatus | str | None - Domain status value to normalize
# Returns: DomainStatus - Normalized enum value
# Inputs: value (enum, string, or None)
# Side_effects: None (pure function)
# Emitted_logs: None
# Error_behavior: Never raises, defaults to RUNNER_ERROR for None/empty/unknown
# Behavior:
#   - If value is already DomainStatus enum, return as-is
#   - If value is known string, map to corresponding enum
#   - If value is None or empty, default to RUNNER_ERROR (safe fallback)
#   - If value is unknown string, default to RUNNER_ERROR (safe fallback)
# Safety:
#   - Unknown strings default to RUNNER_ERROR, never ACCEPTED
#   - None/empty defaults to RUNNER_ERROR for safety
#   - "passed" maps to CHECK_PASSED for local gate compatibility
# END_FUNCTION_CONTRACT
def normalize_domain_status(
    value: DomainStatus | str | None
) -> DomainStatus:
    if isinstance(value, DomainStatus):
        return value

    if value is None or value == "":
        return DomainStatus.RUNNER_ERROR

    # Normalize string to lowercase for comparison
    value_lower = str(value).lower().strip()

    # Map known strings to enums
    mapping = {
        "accepted": DomainStatus.ACCEPTED,
        "rework_required": DomainStatus.REWORK_REQUIRED,
        "blocked": DomainStatus.BLOCKED,
        "scope_blocked": DomainStatus.SCOPE_BLOCKED,
        "agent_failed": DomainStatus.AGENT_FAILED,
        "verifier_failed": DomainStatus.VERIFIER_FAILED,
        "reviewer_failed": DomainStatus.REVIEWER_FAILED,
        "runner_error": DomainStatus.RUNNER_ERROR,
        "handoff_error": DomainStatus.HANDOFF_ERROR,
        "passed": DomainStatus.CHECK_PASSED,
    }

    if value_lower in mapping:
        return mapping[value_lower]

    # Unknown string defaults to RUNNER_ERROR (safe fallback)
    return DomainStatus.RUNNER_ERROR

#END_BLOCK_NORMALIZATION
#START_BLOCK_TRANSITION_HELPERS
# START_FUNCTION_CONTRACT
# Function: apply_domain_result_to_registry
# Purpose: Map domain execution result to registry status transition
# Args:
#   - domain_status: DomainStatus | str - Domain execution outcome
#   - current_registry_status: RegistryStatus | str | None - Current registry state (unused in MVP, reserved for future)
#   - api_failure_category: str | None - Optional API failure metadata (unused in MVP, reserved for future)
# Returns: StatusTransition - New registry status, reason, terminal flag, failure flag
# Inputs: domain_status (enum or string), optional current_registry_status, optional api_failure_category
# Side_effects: None (pure function)
# Emitted_logs: None
# Error_behavior: Never raises, unknown domain status maps to blocked
# Behavior:
#   - accepted → accepted (terminal, not failure)
#   - passed → accepted (terminal, not failure, local gate compatibility)
#   - rework_required → ready_for_retry (not terminal, not failure)
#   - blocked → blocked (terminal, failure)
#   - scope_blocked → blocked with scope_violation reason (terminal, failure)
#   - agent_failed → blocked (terminal, failure)
#   - verifier_failed → blocked (terminal, failure)
#   - reviewer_failed → blocked (terminal, failure)
#   - runner_error → blocked (terminal, failure)
#   - handoff_error → blocked (terminal, failure)
#   - unknown → blocked with unknown_domain_status reason (terminal, failure)
# Safety:
#   - Unknown domain status maps to blocked, never accepted
#   - Terminal failures cannot auto-retry
#   - rework_required is not a failure (quality rework)
# END_FUNCTION_CONTRACT
def apply_domain_result_to_registry(
    domain_status: DomainStatus | str,
    current_registry_status: RegistryStatus | str | None = None,
    *,
    api_failure_category: str | None = None,
) -> StatusTransition:
    # Check if input is unknown string before normalization
    original_value = domain_status
    is_unknown = False
    if isinstance(domain_status, str) and not isinstance(domain_status, DomainStatus):
        value_lower = str(domain_status).lower().strip()
        known_strings = {
            "accepted", "rework_required", "blocked", "scope_blocked",
            "agent_failed", "verifier_failed", "reviewer_failed",
            "runner_error", "handoff_error", "passed"
        }
        if value_lower not in known_strings and value_lower != "":
            is_unknown = True

    # Normalize domain status
    domain = normalize_domain_status(domain_status)

    # Handle unknown status first
    if is_unknown:
        return StatusTransition(
            registry_status=RegistryStatus.BLOCKED,
            reason=f"unknown_domain_status:{original_value}",
            is_terminal=True,
            is_failure=True,
        )

    # Transition table
    if domain == DomainStatus.ACCEPTED:
        return StatusTransition(
            registry_status=RegistryStatus.ACCEPTED,
            reason="execution_accepted",
            is_terminal=True,
            is_failure=False,
        )

    if domain == DomainStatus.CHECK_PASSED:
        return StatusTransition(
            registry_status=RegistryStatus.ACCEPTED,
            reason="local_gate_passed",
            is_terminal=True,
            is_failure=False,
        )

    if domain == DomainStatus.REWORK_REQUIRED:
        return StatusTransition(
            registry_status=RegistryStatus.READY_FOR_RETRY,
            reason="quality_rework",
            is_terminal=False,
            is_failure=False,
        )

    if domain == DomainStatus.BLOCKED:
        return StatusTransition(
            registry_status=RegistryStatus.BLOCKED,
            reason="domain_blocked",
            is_terminal=True,
            is_failure=True,
        )

    if domain == DomainStatus.SCOPE_BLOCKED:
        return StatusTransition(
            registry_status=RegistryStatus.BLOCKED,
            reason="scope_violation",
            is_terminal=True,
            is_failure=True,
        )

    if domain == DomainStatus.AGENT_FAILED:
        return StatusTransition(
            registry_status=RegistryStatus.BLOCKED,
            reason="agent_execution_failed",
            is_terminal=True,
            is_failure=True,
        )

    if domain == DomainStatus.VERIFIER_FAILED:
        return StatusTransition(
            registry_status=RegistryStatus.BLOCKED,
            reason="verifier_failed",
            is_terminal=True,
            is_failure=True,
        )

    if domain == DomainStatus.REVIEWER_FAILED:
        return StatusTransition(
            registry_status=RegistryStatus.BLOCKED,
            reason="reviewer_failed",
            is_terminal=True,
            is_failure=True,
        )

    if domain == DomainStatus.RUNNER_ERROR:
        return StatusTransition(
            registry_status=RegistryStatus.BLOCKED,
            reason="runner_error",
            is_terminal=True,
            is_failure=True,
        )

    if domain == DomainStatus.HANDOFF_ERROR:
        return StatusTransition(
            registry_status=RegistryStatus.BLOCKED,
            reason="handoff_error",
            is_terminal=True,
            is_failure=True,
        )

    # This should not be reached due to early unknown check and normalization
    # But keep as safety fallback
    return StatusTransition(
        registry_status=RegistryStatus.BLOCKED,
        reason="runner_error",
        is_terminal=True,
        is_failure=True,
    )

#END_BLOCK_TRANSITION_HELPERS
#START_BLOCK_PREDICATES
# START_FUNCTION_CONTRACT
# Function: is_terminal_registry_status
# Purpose: Check if registry status is terminal (no further execution)
# Args:
#   - status: RegistryStatus | str - Registry status to check
# Returns: bool - True if terminal, False otherwise
# Inputs: status (enum or string)
# Side_effects: None (pure function)
# Emitted_logs: None
# Error_behavior: Never raises
# Behavior:
#   - Terminal: accepted, blocked, cascading_blocked, changed_after_acceptance
#   - Not terminal: ready, ready_for_retry, waiting_for_dependencies, running
# END_FUNCTION_CONTRACT
def is_terminal_registry_status(status: RegistryStatus | str) -> bool:
    status_enum = normalize_registry_status(status)
    terminal_statuses = {
        RegistryStatus.ACCEPTED,
        RegistryStatus.BLOCKED,
        RegistryStatus.CASCADING_BLOCKED,
        RegistryStatus.CHANGED_AFTER_ACCEPTANCE,
    }
    return status_enum in terminal_statuses


# START_FUNCTION_CONTRACT
# Function: is_runnable_registry_status
# Purpose: Check if registry status allows execution
# Args:
#   - status: RegistryStatus | str - Registry status to check
# Returns: bool - True if runnable, False otherwise
# Inputs: status (enum or string)
# Side_effects: None (pure function)
# Emitted_logs: None
# Error_behavior: Never raises
# Behavior:
#   - Runnable: ready, ready_for_retry
#   - Not runnable: waiting_for_dependencies, running, blocked, cascading_blocked, accepted, changed_after_acceptance
# END_FUNCTION_CONTRACT
def is_runnable_registry_status(status: RegistryStatus | str) -> bool:
    status_enum = normalize_registry_status(status)
    runnable_statuses = {
        RegistryStatus.READY,
        RegistryStatus.READY_FOR_RETRY,
    }
    return status_enum in runnable_statuses


# START_FUNCTION_CONTRACT
# Function: is_failure_domain_status
# Purpose: Check if domain status represents a failure
# Args:
#   - status: DomainStatus | str - Domain status to check
# Returns: bool - True if failure, False otherwise
# Inputs: status (enum or string)
# Side_effects: None (pure function)
# Emitted_logs: None
# Error_behavior: Never raises
# Behavior:
#   - Failure: blocked, scope_blocked, agent_failed, verifier_failed, reviewer_failed, runner_error, handoff_error
#   - Not failure: accepted, rework_required, passed
# END_FUNCTION_CONTRACT
def is_failure_domain_status(status: DomainStatus | str) -> bool:
    status_enum = normalize_domain_status(status)
    failure_statuses = {
        DomainStatus.BLOCKED,
        DomainStatus.SCOPE_BLOCKED,
        DomainStatus.AGENT_FAILED,
        DomainStatus.VERIFIER_FAILED,
        DomainStatus.REVIEWER_FAILED,
        DomainStatus.RUNNER_ERROR,
        DomainStatus.HANDOFF_ERROR,
    }
    return status_enum in failure_statuses


# START_FUNCTION_CONTRACT
# Function: is_scope_domain_status
# Purpose: Check if domain status is scope-related
# Args:
#   - status: DomainStatus | str - Domain status to check
# Returns: bool - True if scope-related, False otherwise
# Inputs: status (enum or string)
# Side_effects: None (pure function)
# Emitted_logs: None
# Error_behavior: Never raises
# Behavior:
#   - Scope-related: scope_blocked
#   - Not scope-related: all other statuses
# END_FUNCTION_CONTRACT
def is_scope_domain_status(status: DomainStatus | str) -> bool:
    status_enum = normalize_domain_status(status)
    return status_enum == DomainStatus.SCOPE_BLOCKED

#END_BLOCK_PREDICATES
