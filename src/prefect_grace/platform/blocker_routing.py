"""
# ============================================================================
# AI_HEADER: GRACE Blocker Routing Module
# ============================================================================
#
# This module provides deterministic routing of evidence blockers to the
# correct role. Different blocker types require different remediation:
# - Implementation failures route to coder
# - Contract failures route to architect
# - Artifact reference failures route to verifier/pipeline
# - Environment failures route to infra/operator
#
# Key Concepts:
# - Blocker routing is deterministic (not LLM-based)
# - Invalid contracts route to architect (not coder)
# - Missing artifacts route to verifier/pipeline (not coder)
# - wave_final evidence pending is not packet-blocking
# - Pure function with no side effects
#
# Module Dependencies:
# - No external dependencies (pure routing logic)
# - No Prefect imports
#
# ============================================================================
"""

from dataclasses import dataclass
from typing import Any

# START_MODULE_CONTRACT
# Module: blocker_routing
# Purpose: Route evidence blockers to correct role for remediation
# Exports: BlockerRoute, route_evidence_blocker
# Dependencies: None (pure routing logic)
# Constraints: No Prefect imports, deterministic routing, pure function
# END_MODULE_CONTRACT

# START_MODULE_MAP
# Block: models - Blocker route dataclass
# Block: routing_table - Blocker code to role mapping
# Block: router - Route blocker to correct role
# END_MODULE_MAP

#START_BLOCK_MODELS
@dataclass(frozen=True)
class BlockerRoute:
    """Blocker routing result.

    Fields:
    - blocker_code: Blocker type code
    - route_to: Role to route blocker to
    - message: Human-readable routing message
    """
    blocker_code: str
    route_to: str
    message: str

    # START_FUNCTION_CONTRACT
    # Function: to_dict
    # Purpose: Serialize BlockerRoute to dict for JSON output
    # Args: None (instance method)
    # Returns: Dict with blocker_code, route_to, message
    # Inputs: self
    # Side_effects: None (pure function)
    # Emitted_logs: None
    # Error_behavior: Never raises
    # END_FUNCTION_CONTRACT
    def to_dict(self) -> dict[str, Any]:
        """Serialize to dict for JSON output."""
        return {
            "blocker_code": self.blocker_code,
            "route_to": self.route_to,
            "message": self.message,
        }

#END_BLOCK_MODELS
#START_BLOCK_ROUTING_TABLE
# Blocker routing table
# Maps blocker codes to (route_to, message_template)
BLOCKER_ROUTES = {
    "implementation_failed": (
        "coder",
        "Implementation failure - code does not work as expected",
    ),
    "verification_failed": (
        "coder",
        "Verification failure - tests fail due to implementation issues",
    ),
    "failed_verification": (
        "coder",
        "Verification command failure - implementation-owned issue",
    ),
    "evidence_contract_invalid": (
        "architect",
        "Evidence contract invalid - impossible/unowned/unprofiled evidence requirement",
    ),
    "missing_verification_profile": (
        "architect",
        "Verification profile not found - architect must define profile",
    ),
    "artifact_reference_invalid": (
        "verifier",
        "Artifact reference invalid - claimed path does not exist",
    ),
    "evidence_not_generated": (
        "verifier",
        "Evidence not generated - verifier didn't produce required evidence",
    ),
    "environment_blocker": (
        "infra",
        "Environment blocker - infrastructure or configuration issue",
    ),
    "scope_violation": (
        "architect",
        "Scope violation - requires architect decision on scope expansion",
    ),
    "wave_final_evidence_pending": (
        "none",
        "wave_final evidence pending - not packet-blocking",
    ),
    "review_rework_required": (
        "coder",
        "Review rework required - reviewer feedback needs implementation changes",
    ),
    "packet_local_deferred": (
        "verifier",
        "packet_local evidence deferred - verifier must produce in packet scope",
    ),
    "unknown_evidence_id": (
        "verifier",
        "Unknown evidence ID - evidence not in contract",
    ),
    "invalid_status": (
        "verifier",
        "Invalid evidence status - verifier returned invalid status",
    ),
    "missing_id": (
        "architect",
        "Missing evidence ID - contract requirement missing id field",
    ),
    "duplicate_id": (
        "architect",
        "Duplicate evidence ID - contract has duplicate requirement ids",
    ),
    "unknown_kind": (
        "architect",
        "Unknown evidence kind - contract uses invalid kind value",
    ),
    "unknown_stage": (
        "architect",
        "Unknown evidence stage - contract uses invalid stage value",
    ),
    "unknown_owner": (
        "architect",
        "Unknown evidence owner - contract uses invalid owner value",
    ),
    "unknown_producer": (
        "architect",
        "Unknown evidence producer - contract uses invalid producer value",
    ),
    "required_without_owner": (
        "architect",
        "Required evidence without owner - contract missing owner assignment",
    ),
    "required_without_producer": (
        "architect",
        "Required evidence without producer - contract missing producer assignment",
    ),
    "wave_final_coder_blocking": (
        "architect",
        "wave_final evidence marked coder_blocking - invalid contract configuration",
    ),
}

#END_BLOCK_ROUTING_TABLE
#START_BLOCK_ROUTER
# START_FUNCTION_CONTRACT
# Function: route_evidence_blocker
# Purpose: Route evidence blocker to correct role
# Args:
#   - error: Dict with blocker information (must have 'code' key)
# Returns: BlockerRoute with route_to and message
# Inputs: Dict with blocker code and optional message
# Side_effects: None (pure function)
# Emitted_logs: None
# Error_behavior: Never raises, defaults to architect for unknown codes
# Behavior:
#   - Looks up blocker code in routing table
#   - Returns route with role and message
#   - Falls back to "architect" for unknown blocker codes
#   - Pure function with no side effects
#   - Deterministic routing
# END_FUNCTION_CONTRACT
def route_evidence_blocker(error: dict[str, Any]) -> BlockerRoute:
    """Route evidence blocker to correct role.

    Routing rules:
    - implementation_failed: coder
    - verification_failed: coder (if caused by implementation test failure)
    - failed_verification: coder (if command failure is implementation-owned)
    - evidence_contract_invalid: architect
    - missing_verification_profile: architect/planner
    - artifact_reference_invalid: verifier/pipeline
    - evidence_not_generated: verifier/pipeline
    - environment_blocker: infra/operator
    - scope_violation: architect decision
    - wave_final_evidence_pending: not packet-blocking
    - review_rework_required: coder/reviewer route

    Returns BlockerRoute with route_to and message.
    """
    blocker_code = error.get("code", "unknown")

    # Look up route in table
    if blocker_code in BLOCKER_ROUTES:
        route_to, message_template = BLOCKER_ROUTES[blocker_code]
        message = error.get("message", message_template)
    else:
        # Unknown blocker code - route to architect for triage
        route_to = "architect"
        message = f"Unknown blocker code: {blocker_code} - requires architect triage"

    return BlockerRoute(
        blocker_code=blocker_code,
        route_to=route_to,
        message=message,
    )

#END_BLOCK_ROUTER
