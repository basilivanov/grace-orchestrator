"""
# ============================================================================
# AI_HEADER: GRACE Agent Failure Classifier Module
# ============================================================================
#
# This module provides deterministic classification of agent/API provider
# failures to distinguish quality rework from infrastructure/provider blockers.
# LLM agent failures are not all implementation failures - rate limits, auth
# errors, and network timeouts should route differently than code bugs.
#
# Key Concepts:
# - API/provider failures are NOT quality rework
# - Classification is deterministic (pattern matching, no LLM calls)
# - Fail-closed: unknown errors → unknown_api_error (requires operator action)
# - Retryable failures (rate_limit, timeout) vs operator action (auth, quota)
# - Classification metadata flows to downstream routing decisions
#
# Module Dependencies:
# - No external dependencies (pure pattern matching)
# - No Prefect imports (pure classification logic)
#
# ============================================================================
"""

from dataclasses import dataclass
from typing import Any

# START_MODULE_CONTRACT
# Module: agent_failure_classifier
# Purpose: Classify agent/API provider failures for routing decisions
# Exports: AgentFailureClassification, classify_agent_failure
# Dependencies: None (pure pattern matching)
# Constraints: No LLM calls, no network requests, deterministic, fail-closed
# END_MODULE_CONTRACT

# START_MODULE_MAP
# Block: models - AgentFailureClassification dataclass
# Block: patterns - Pattern definitions for each failure category
# Block: classifier - classify_agent_failure function
# END_MODULE_MAP

#START_BLOCK_MODELS
@dataclass(frozen=True)
class AgentFailureClassification:
    """
    Result of classifying an agent/API provider failure.

    Fields:
    - category: Failure category (none, rate_limit, quota_exceeded, auth_failed,
                network_timeout, provider_unavailable, unknown_api_error)
    - retryable: Whether failure can be retried later
    - quality_rework: Whether this is quality rework (always False for API errors)
    - operator_action_required: Whether operator intervention is needed
    - reason: Human-readable description of the failure
    - matched_pattern: Pattern that triggered classification (None if category=none)
    """
    category: str
    retryable: bool
    quality_rework: bool
    operator_action_required: bool
    reason: str
    matched_pattern: str | None

    # START_FUNCTION_CONTRACT
    # Function: to_dict
    # Purpose: Serialize AgentFailureClassification to dict for JSON output
    # Args: None (instance method)
    # Returns: Dict with category, retryable, quality_rework, operator_action_required, reason, matched_pattern
    # Inputs: self
    # Side_effects: None (pure function)
    # Emitted_logs: None
    # Error_behavior: Never raises
    # END_FUNCTION_CONTRACT
    def to_dict(self) -> dict[str, Any]:
        """Serialize to dict for JSON output."""
        return {
            "category": self.category,
            "retryable": self.retryable,
            "quality_rework": self.quality_rework,
            "operator_action_required": self.operator_action_required,
            "reason": self.reason,
            "matched_pattern": self.matched_pattern,
        }

#END_BLOCK_MODELS
#START_BLOCK_PATTERNS
# Pattern definitions for each failure category
# Priority order: rate_limit > auth_failed > quota_exceeded > network_timeout > provider_unavailable

RATE_LIMIT_PATTERNS = [
    "429",
    "rate limit",
    "rate_limit",
    "too many requests",
    "rate_limit_exceeded",
    "ratelimit",
]

AUTH_FAILED_PATTERNS = [
    "401",
    "403",
    "authentication failed",
    "invalid api key",
    "invalid_api_key",
    "unauthorized",
    "forbidden",
    "auth failed",
    "authentication error",
]

QUOTA_EXCEEDED_PATTERNS = [
    "quota exceeded",
    "insufficient quota",
    "quota_limit_reached",
    "quota limit",
    "out of quota",
]

NETWORK_TIMEOUT_PATTERNS = [
    "connection timeout",
    "read timeout",
    "timed out",
    "timeout error",
    "connect timeout",
    "request timeout",
]

PROVIDER_UNAVAILABLE_PATTERNS = [
    "502",
    "503",
    "service unavailable",
    "bad gateway",
    "server error",
    "temporarily unavailable",
]

#END_BLOCK_PATTERNS
#START_BLOCK_CLASSIFIER
# START_FUNCTION_CONTRACT
# Function: classify_agent_failure
# Purpose: Classify agent/API provider failure from stderr/stdout/exit_code
# Args:
#   - stdout_text: Agent stdout output (default "")
#   - stderr_text: Agent stderr output (default "")
#   - exit_code: Process exit code (default None)
#   - termination_reason: Launcher termination reason (default None)
# Returns: AgentFailureClassification with category and metadata
# Inputs: Text outputs and exit code from agent process
# Side_effects: None (pure function)
# Emitted_logs: None
# Error_behavior: Never raises, returns classification (fail-closed)
# Behavior:
#   - Checks stderr and stdout for patterns (case-insensitive)
#   - Priority: rate_limit > auth_failed > quota_exceeded > network_timeout > provider_unavailable
#   - If exit_code == 0 and no patterns → category="none"
#   - If exit_code != 0 and no patterns → category="unknown_api_error"
#   - API failures have quality_rework=False
#   - Retryable: rate_limit, network_timeout, provider_unavailable
#   - Operator action: auth_failed, quota_exceeded, unknown_api_error
# END_FUNCTION_CONTRACT
def classify_agent_failure(
    *,
    stdout_text: str = "",
    stderr_text: str = "",
    exit_code: int | None = None,
    termination_reason: str | None = None,
) -> AgentFailureClassification:
    """
    Classify agent/API provider failure from stderr/stdout/exit_code.

    Checks for patterns in stderr and stdout (case-insensitive):
    - HTTP 429, "rate limit", "too many requests" → rate_limit
    - HTTP 401, HTTP 403, "authentication failed", "invalid api key" → auth_failed
    - "quota exceeded", "insufficient quota" → quota_exceeded
    - "connection timeout", "read timeout", "timed out" → network_timeout
    - HTTP 502, HTTP 503, "service unavailable" → provider_unavailable
    - exit_code != 0 and no patterns → unknown_api_error
    - exit_code == 0 and no patterns → none

    Returns AgentFailureClassification with category and metadata.
    """
    # Combine stderr and stdout for pattern matching
    combined_text = f"{stderr_text}\n{stdout_text}".lower()

    # Check rate_limit patterns (highest priority)
    for pattern in RATE_LIMIT_PATTERNS:
        if pattern.lower() in combined_text:
            return AgentFailureClassification(
                category="rate_limit",
                retryable=True,
                quality_rework=False,
                operator_action_required=False,
                reason="Rate limit exceeded - retry after delay",
                matched_pattern=pattern,
            )

    # Check auth_failed patterns
    for pattern in AUTH_FAILED_PATTERNS:
        if pattern.lower() in combined_text:
            return AgentFailureClassification(
                category="auth_failed",
                retryable=False,
                quality_rework=False,
                operator_action_required=True,
                reason="Authentication failed - check API credentials",
                matched_pattern=pattern,
            )

    # Check quota_exceeded patterns
    for pattern in QUOTA_EXCEEDED_PATTERNS:
        if pattern.lower() in combined_text:
            return AgentFailureClassification(
                category="quota_exceeded",
                retryable=False,
                quality_rework=False,
                operator_action_required=True,
                reason="Quota exceeded - increase quota or wait for reset",
                matched_pattern=pattern,
            )

    # Check network_timeout patterns
    for pattern in NETWORK_TIMEOUT_PATTERNS:
        if pattern.lower() in combined_text:
            return AgentFailureClassification(
                category="network_timeout",
                retryable=True,
                quality_rework=False,
                operator_action_required=False,
                reason="Network timeout - retry with backoff",
                matched_pattern=pattern,
            )

    # Check provider_unavailable patterns
    for pattern in PROVIDER_UNAVAILABLE_PATTERNS:
        if pattern.lower() in combined_text:
            return AgentFailureClassification(
                category="provider_unavailable",
                retryable=True,
                quality_rework=False,
                operator_action_required=False,
                reason="Provider unavailable - retry later",
                matched_pattern=pattern,
            )

    # Fail-closed: if exit_code != 0 and no patterns matched → unknown_api_error
    if exit_code is not None and exit_code != 0:
        return AgentFailureClassification(
            category="unknown_api_error",
            retryable=False,
            quality_rework=False,
            operator_action_required=True,
            reason=f"Unknown error (exit_code={exit_code}) - requires investigation",
            matched_pattern=None,
        )

    # No patterns matched and exit_code == 0 (or None) → none
    return AgentFailureClassification(
        category="none",
        retryable=False,
        quality_rework=False,
        operator_action_required=False,
        reason="No API failure detected",
        matched_pattern=None,
    )

#END_BLOCK_CLASSIFIER
