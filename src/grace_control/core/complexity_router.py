# ############################################################################
# AI_HEADER: complexity_router
# ROLE: Route packets to appropriate executor tier based on acceptance profile.
# ############################################################################

# START_MODULE_CONTRACT
# purpose: Select executor tier (cheap/standard/premium) based on packet profile and complexity.
# inputs: acceptance_profile (FAST/NORMAL/STRICT), optional spec_json for complexity analysis.
# returns: ExecutorTier enum value.
# side_effects: None.
# emitted_logs: None.
# error_behavior: Never raises — defaults to STANDARD on unknown input.
# END_MODULE_CONTRACT

# START_MODULE_MAP
# mapping:
#   - enum: ExecutorTier
#   - function: route_packet
#   - function: estimate_complexity
# END_MODULE_MAP

from __future__ import annotations

import enum


class ExecutorTier(enum.Enum):
    CHEAP = "cheap"        # Gemini Flash — fast, low cost
    STANDARD = "standard"  # Gemini Pro / Claude Sonnet — balanced
    PREMIUM = "premium"    # Claude Opus — highest quality


#START_BLOCK_ROUTER
# START_FUNCTION_CONTRACT
# name: route_packet
# purpose: Select executor tier based on acceptance profile + scope complexity.
# inputs:
#   acceptance_profile: FAST, NORMAL, or STRICT.
#   spec_json: Optional packet spec dict with scope, requirements, etc.
# returns: ExecutorTier.
# side_effects: None.
# emitted_logs: None.
# error_behavior: Never raises.
# END_FUNCTION_CONTRACT
def route_packet(acceptance_profile: str, spec_json: dict | None = None) -> ExecutorTier:
    profile = (acceptance_profile or "NORMAL").upper()
    scope_lines = estimate_complexity(spec_json)

    if profile == "FAST":
        return ExecutorTier.CHEAP
    if profile == "STRICT":
        return ExecutorTier.PREMIUM

    # NORMAL: use complexity to decide
    if scope_lines > 200:
        return ExecutorTier.PREMIUM
    if scope_lines > 100:
        return ExecutorTier.STANDARD
    return ExecutorTier.CHEAP


# START_FUNCTION_CONTRACT
# name: estimate_complexity
# purpose: Estimate packet complexity from spec_json (number of scope files, requirements).
# inputs: spec_json dict or None.
# returns: Integer complexity score (higher = more complex).
# side_effects: None.
# emitted_logs: None.
# error_behavior: Never raises.
# END_FUNCTION_CONTRACT
def estimate_complexity(spec_json: dict | None = None) -> int:
    if not spec_json:
        return 0
    scope = spec_json.get("scope", "")
    if isinstance(scope, list):
        return len(scope) * 50
    if isinstance(scope, str):
        return 50 if scope else 0
    return 0

#END_BLOCK_ROUTER
