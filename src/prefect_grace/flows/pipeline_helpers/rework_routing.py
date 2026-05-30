# ############################################################################
# AI_HEADER: pipeline_helpers.rework_routing
# ROLE: Pure rework routing and classification helpers for feature_pipeline.
# ############################################################################

# START_MODULE_CONTRACT
# purpose: Classify reviewer rework routes and normalize rework modes without mutating packet or feature state.
# inputs: Reviewer decisions, reasons, packet dictionaries, and execution hints.
# returns: Normalized route/mode strings or adjusted reviewer decision dictionaries.
# side_effects: None.
# emitted_logs: None.
# error_behavior: Invalid optional values fall back to existing default route and mode behavior.
# END_MODULE_CONTRACT

# START_MODULE_MAP
# mapping:
#   - function: normalize_reviewer_decision_for_pipeline
#   - function: packet_execution_contract
#   - function: string_command_list
#   - function: uses_today_week_observability
#   - function: classify_rework_route
#   - function: classify_rework_mode
# END_MODULE_MAP

from __future__ import annotations

from prefect_grace.models import ReviewVerdict

_EVIDENCE_ONLY_REVIEW_MARKERS = (
    "evidence",
    "visual",
    "observability",
    "artifact",
    "screenshot",
    "proof",
    "no-evidence-blocker",
    "canonical logs",
)
_TERMINAL_REVIEW_MARKERS = (
    "architect decision",
    "business",
    "scope expansion",
    "slice boundary",
    "decomposition",
    "orchestration wiring",
    "invalid verifier command",
    "malformed pipeline contract",
    "schema",
    "environment unavailable",
)
_OBSERVABILITY_REVIEW_MARKERS = (
    "observability",
    "no-evidence-blocker",
    "canonical logs",
    "canonical evidence",
    "trace_id",
    "correlation_id",
    "request_id",
    "report_id",
)

_TODAY_WEEK_MARKER = "tools/post_test_review.py --profile today-week"

REWORK_ROUTE_SELF_RESOLVABLE = "self_resolvable_rework"
REWORK_ROUTE_REQUIRES_USER_DECISION = "requires_user_decision"
REWORK_ROUTE_REQUIRES_PLANNER = "requires_planner"
REWORK_ROUTING_ARCHITECT_FIRST = "architect_first"
REWORK_ROUTING_AUTO_BUNDLE = "auto_bundle"
REWORK_MODE_LIGHT_RESUME = "light_resume"
REWORK_MODE_BOUNDED_FRESH = "bounded_fresh"
REWORK_MODE_DECISION_REQUIRED = "decision_required"

_USER_DECISION_REVIEW_MARKERS = (
    "business decision",
    "product decision",
    "user decision",
    "ask the user",
    "requires user",
    "requires architect/business",
    "business",
    "product",
    "pricing",
    "legal",
    "compliance",
    "policy decision",
    "scope expansion",
    "change business semantics",
)
_PLANNER_REVIEW_MARKERS = (
    "planner",
    "decomposition",
    "reslice",
    "re-slice",
    "split packet",
    "packet graph",
    "wave graph",
    "dependency graph",
    "multi-wave",
    "multiple waves",
    "slice boundary",
    "execution topology",
)


# START_FUNCTION_CONTRACT
# name: normalize_reviewer_decision_for_pipeline
# purpose: Convert evidence-only blocked reviewer decisions into localized rework while preserving terminal blockers.
# inputs:
#   decision: Reviewer decision dictionary.
# returns: Original or normalized reviewer decision dictionary.
# side_effects: None.
# emitted_logs: None.
# error_behavior: None.
# END_FUNCTION_CONTRACT
def normalize_reviewer_decision_for_pipeline(decision: dict) -> dict:
    if str(decision.get("packet_verdict") or "") != ReviewVerdict.BLOCKED.value:
        return decision
    reasons = [str(item).strip() for item in list(decision.get("reasons") or []) if str(item).strip()]
    if not reasons:
        return decision
    lowered = [reason.lower() for reason in reasons]
    if any(any(marker in reason for marker in _TERMINAL_REVIEW_MARKERS) for reason in lowered):
        return decision
    if not all(any(marker in reason for marker in _EVIDENCE_ONLY_REVIEW_MARKERS) for reason in lowered):
        return decision
    return {
        **decision,
        "packet_verdict": ReviewVerdict.REWORK_REQUIRED.value,
        "follow_up_action": "localized_rework",
        "source": "pipeline_normalized_rework",
    }


# START_FUNCTION_CONTRACT
# name: packet_execution_contract
# purpose: Resolve a packet's execution contract from verification profile or execution hints.
# inputs:
#   packet: Packet dictionary.
# returns: Execution contract dictionary.
# side_effects: None.
# emitted_logs: None.
# error_behavior: None.
# END_FUNCTION_CONTRACT
def packet_execution_contract(packet: dict) -> dict:
    verification_profile = dict(packet.get("verification_profile") or {})
    execution = verification_profile.get("execution")
    if isinstance(execution, dict):
        return dict(execution)
    return dict(packet.get("execution_hints") or {})


# START_FUNCTION_CONTRACT
# name: string_command_list
# purpose: Normalize a scalar or list command field into a clean list of strings.
# inputs:
#   value: Raw command field.
# returns: List of non-empty command strings.
# side_effects: None.
# emitted_logs: None.
# error_behavior: None.
# END_FUNCTION_CONTRACT
def string_command_list(value: object) -> list[str]:
    if value in (None, "", []):
        return []
    if isinstance(value, list):
        return [str(item).strip() for item in value if str(item).strip()]
    return [str(value).strip()] if str(value).strip() else []


# START_FUNCTION_CONTRACT
# name: uses_today_week_observability
# purpose: Detect whether a packet asks for the today-week observability profile or command.
# inputs:
#   packet: Packet dictionary.
# returns: True when today-week observability is requested.
# side_effects: None.
# emitted_logs: None.
# error_behavior: None.
# END_FUNCTION_CONTRACT
def uses_today_week_observability(packet: dict) -> bool:
    execution = packet_execution_contract(packet)
    observability_commands = string_command_list(execution.get("observability_commands"))
    observability_profile = str(execution.get("observability_profile") or "").strip().lower()
    return observability_profile == "today-week" or any(_TODAY_WEEK_MARKER in command for command in observability_commands)


# START_FUNCTION_CONTRACT
# name: escalate_repeated_observability_rework_for_pipeline
# purpose: Escalate repeated observability-only rework for a parent packet into a pipeline blocker.
# inputs:
#   decision: Reviewer decision dictionary.
#   target_packet_id: Target packet id.
#   packets_by_id: Packet lookup dictionary.
# returns: Original or escalated decision dictionary.
# side_effects: None.
# emitted_logs: None.
# error_behavior: None.
# END_FUNCTION_CONTRACT
def escalate_repeated_observability_rework_for_pipeline(
    decision: dict,
    *,
    target_packet_id: str,
    packets_by_id: dict[str, dict],
) -> dict:
    if str(decision.get("packet_verdict") or "") != ReviewVerdict.REWORK_REQUIRED.value:
        return decision
    target_packet = dict(packets_by_id.get(str(target_packet_id)) or {})
    parent_packet_id = str(target_packet.get("parent_packet_id") or "").strip()
    if not parent_packet_id:
        return decision
    reasons = [str(item).strip() for item in list(decision.get("reasons") or []) if str(item).strip()]
    if not reasons:
        return decision
    lowered = [reason.lower() for reason in reasons]
    if any(any(marker in reason for marker in _TERMINAL_REVIEW_MARKERS) for reason in lowered):
        return decision
    if not any(any(marker in reason for marker in _OBSERVABILITY_REVIEW_MARKERS) for reason in lowered):
        return decision
    repeated_reason = (
        f"Repeated observability-only rework for {parent_packet_id} still did not produce canonical evidence; "
        "pipeline repair required before another coder packet."
    )
    if not any("pipeline repair" in reason.lower() for reason in reasons):
        reasons = [*reasons, repeated_reason]
    return {
        **decision,
        "packet_verdict": ReviewVerdict.BLOCKED.value,
        "follow_up_action": "none",
        "reasons": reasons,
        "source": "pipeline_rework_escalation",
    }


# START_FUNCTION_CONTRACT
# name: normalize_rework_route_classification
# purpose: Normalize an explicit rework route classification string.
# inputs:
#   value: Raw classification.
# returns: One of the existing rework route constants.
# side_effects: None.
# emitted_logs: None.
# error_behavior: Unknown values fall back to self_resolvable_rework.
# END_FUNCTION_CONTRACT
def normalize_rework_route_classification(value: object) -> str:
    classification = str(value or "").strip().lower().replace("-", "_")
    aliases = {
        "self_resolvable": REWORK_ROUTE_SELF_RESOLVABLE,
        "localized_rework": REWORK_ROUTE_SELF_RESOLVABLE,
        "direct_rework": REWORK_ROUTE_SELF_RESOLVABLE,
        "architect_direct_rework": REWORK_ROUTE_SELF_RESOLVABLE,
        "user_decision": REWORK_ROUTE_REQUIRES_USER_DECISION,
        "architect_decision": REWORK_ROUTE_REQUIRES_USER_DECISION,
        "product_decision": REWORK_ROUTE_REQUIRES_USER_DECISION,
        "planner": REWORK_ROUTE_REQUIRES_PLANNER,
        "planner_required": REWORK_ROUTE_REQUIRES_PLANNER,
    }
    classification = aliases.get(classification, classification)
    if classification not in {
        REWORK_ROUTE_SELF_RESOLVABLE,
        REWORK_ROUTE_REQUIRES_USER_DECISION,
        REWORK_ROUTE_REQUIRES_PLANNER,
    }:
        return REWORK_ROUTE_SELF_RESOLVABLE
    return classification


# START_FUNCTION_CONTRACT
# name: normalize_rework_mode
# purpose: Normalize an explicit rework mode string.
# inputs:
#   value: Raw mode.
# returns: One of the existing rework mode constants.
# side_effects: None.
# emitted_logs: None.
# error_behavior: Unknown values fall back to bounded_fresh.
# END_FUNCTION_CONTRACT
def normalize_rework_mode(value: object) -> str:
    mode = str(value or "").strip().lower().replace("-", "_")
    aliases = {
        "light": REWORK_MODE_LIGHT_RESUME,
        "resume": REWORK_MODE_LIGHT_RESUME,
        "packet_local_resume": REWORK_MODE_LIGHT_RESUME,
        "small_fix": REWORK_MODE_LIGHT_RESUME,
        "smallfix": REWORK_MODE_LIGHT_RESUME,
        "fresh": REWORK_MODE_BOUNDED_FRESH,
        "bounded": REWORK_MODE_BOUNDED_FRESH,
        "fresh_packet": REWORK_MODE_BOUNDED_FRESH,
        "execution": REWORK_MODE_BOUNDED_FRESH,
        "rework": REWORK_MODE_BOUNDED_FRESH,
        "gate": REWORK_MODE_DECISION_REQUIRED,
        "decision": REWORK_MODE_DECISION_REQUIRED,
        "gate_decision": REWORK_MODE_DECISION_REQUIRED,
        "architect_decision": REWORK_MODE_DECISION_REQUIRED,
    }
    mode = aliases.get(mode, mode)
    if mode not in {
        REWORK_MODE_LIGHT_RESUME,
        REWORK_MODE_BOUNDED_FRESH,
        REWORK_MODE_DECISION_REQUIRED,
    }:
        return REWORK_MODE_BOUNDED_FRESH
    return mode


# START_FUNCTION_CONTRACT
# name: classify_rework_route_from_reasons
# purpose: Classify reviewer reasons into the existing rework route categories.
# inputs:
#   reasons: Reviewer reason strings.
# returns: Rework route classification string.
# side_effects: None.
# emitted_logs: None.
# error_behavior: Empty or unrecognized reasons fall back to self_resolvable_rework.
# END_FUNCTION_CONTRACT
def classify_rework_route_from_reasons(reasons: list[str]) -> str:
    lowered = [str(reason).strip().lower() for reason in reasons if str(reason).strip()]
    if any(any(marker in reason for marker in _USER_DECISION_REVIEW_MARKERS) for reason in lowered):
        return REWORK_ROUTE_REQUIRES_USER_DECISION
    if any(any(marker in reason for marker in _PLANNER_REVIEW_MARKERS) for reason in lowered):
        return REWORK_ROUTE_REQUIRES_PLANNER
    return REWORK_ROUTE_SELF_RESOLVABLE


# START_FUNCTION_CONTRACT
# name: classify_rework_route
# purpose: Classify a reviewer decision into self-resolvable, user-decision, or planner-required routing.
# inputs:
#   decision: Reviewer decision dictionary.
# returns: Rework route classification string.
# side_effects: None.
# emitted_logs: None.
# error_behavior: Missing optional fields fall back to self_resolvable_rework.
# END_FUNCTION_CONTRACT
def classify_rework_route(decision: dict) -> str:
    explicit = decision.get("route_classification")
    if explicit:
        return normalize_rework_route_classification(explicit)
    follow_up = str(decision.get("follow_up_action") or "").strip().lower().replace("-", "_")
    if follow_up == "architect_decision":
        return REWORK_ROUTE_REQUIRES_USER_DECISION
    return classify_rework_route_from_reasons(list(decision.get("reasons") or []))


# START_FUNCTION_CONTRACT
# name: classify_rework_mode
# purpose: Classify a reviewer decision into light resume, bounded fresh, or decision-required mode.
# inputs:
#   decision: Reviewer decision dictionary.
#   route_classification: Normalized route classification.
#   target_packet: Optional target packet dictionary.
# returns: Rework mode string.
# side_effects: None.
# emitted_logs: None.
# error_behavior: Missing optional fields fall back to bounded_fresh.
# END_FUNCTION_CONTRACT
def classify_rework_mode(*, decision: dict, route_classification: str, target_packet: dict | None = None) -> str:
    explicit = decision.get("rework_mode")
    if explicit:
        explicit_mode = normalize_rework_mode(explicit)
        if explicit_mode == REWORK_MODE_LIGHT_RESUME and route_classification != REWORK_ROUTE_SELF_RESOLVABLE:
            return REWORK_MODE_DECISION_REQUIRED
        return explicit_mode
    if route_classification != REWORK_ROUTE_SELF_RESOLVABLE:
        return REWORK_MODE_DECISION_REQUIRED
    target = dict(target_packet or {})
    role = str(target.get("role") or "").strip().lower()
    parent_packet_id = str(target.get("parent_packet_id") or "").strip()
    reasons = [str(reason).strip() for reason in list(decision.get("reasons") or []) if str(reason).strip()]
    if role == "coder" and not parent_packet_id and 0 < len(reasons) <= 2:
        return REWORK_MODE_LIGHT_RESUME
    return REWORK_MODE_BOUNDED_FRESH


_normalize_reviewer_decision_for_pipeline = normalize_reviewer_decision_for_pipeline
_packet_execution_contract = packet_execution_contract
_string_command_list = string_command_list
_uses_today_week_observability = uses_today_week_observability
_escalate_repeated_observability_rework_for_pipeline = escalate_repeated_observability_rework_for_pipeline
_normalize_rework_route_classification = normalize_rework_route_classification
_normalize_rework_mode = normalize_rework_mode
_classify_rework_route_from_reasons = classify_rework_route_from_reasons
_classify_rework_route = classify_rework_route
_classify_rework_mode = classify_rework_mode
