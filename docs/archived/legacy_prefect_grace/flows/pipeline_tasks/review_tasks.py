# ############################################################################
# AI_HEADER: pipeline_tasks.review_tasks
# ROLE: Reviewer decision and routing Prefect tasks for feature_pipeline.
# ############################################################################

# START_MODULE_CONTRACT
# purpose: Resolve reviewer decisions, route reviewer verdicts, and record simple review-router reviews.
# inputs: Packet ids, reviewer packet ids, reviewer run payloads, verdicts, reasons, and routing policy values.
# returns: Reviewer decision and route dictionaries.
# side_effects: Writes review/packet/rework state and sends packet status notifications through existing APIs.
# emitted_logs: Prefect task logs.
# error_behavior: Preserves existing parse fallback behavior and propagates state update errors.
# END_MODULE_CONTRACT

# START_MODULE_MAP
# mapping:
#   - function: route_reviewer_verdict_task
#   - function: resolve_reviewer_decision_task
#   - function: review_task
# END_MODULE_MAP

from __future__ import annotations

import sys

from prefect_grace.flows.pipeline_helpers.rework_routing import (
    REWORK_ROUTE_REQUIRES_PLANNER,
    REWORK_ROUTE_REQUIRES_USER_DECISION,
    REWORK_ROUTE_SELF_RESOLVABLE,
    REWORK_ROUTING_ARCHITECT_FIRST,
    REWORK_ROUTING_AUTO_BUNDLE,
    classify_rework_route,
)
from prefect_grace.flows.pipeline_tasks.execution_tasks import mark_packet_status_task
from prefect_grace.models import PacketStatus, ReviewVerdict
from prefect_grace.prefect_compat import get_run_logger, task
from prefect_grace.tasks.agent_output_parser import resolve_reviewer_decision
from prefect_grace.tasks.review_router import (
    create_architect_decision_from_review,
    create_rework_bundle_from_review,
    create_rework_from_review,
    record_review,
)
from prefect_grace.tasks.state_store import find_record
from prefect_grace.tasks.telegram_notify import notify_packet_event


def _facade_attr(name: str, default):
    facade = sys.modules.get("prefect_grace.flows.feature_pipeline")
    return getattr(facade, name, default) if facade is not None else default


# START_FUNCTION_CONTRACT
# name: route_reviewer_verdict_task
# purpose: Route a reviewer decision into packet status updates, rework packets, or architect decisions.
# inputs: Coder/reviewer packet ids, reviewer decision payload, create_rework flag, routing policy, and optional architect packet.
# returns: Review route dictionary.
# side_effects: Writes reviews, updates packet statuses, creates rework/decision records, and sends notifications.
# emitted_logs: Prefect task log lines.
# error_behavior: Propagates invalid verdict/status and state errors.
# END_FUNCTION_CONTRACT
@task(task_run_name="review-route:{coder_packet_id}")
def route_reviewer_verdict_task(
    coder_packet_id: str,
    reviewer_packet_id: str,
    reviewer_decision: dict,
    create_rework: bool,
    rework_routing_policy: str = REWORK_ROUTING_ARCHITECT_FIRST,
    architect_rework_packet: dict | None = None,
):
    logger = _facade_attr("get_run_logger", get_run_logger)()
    verdict = ReviewVerdict(reviewer_decision["packet_verdict"])
    review_reasons = list(reviewer_decision.get("reasons") or [])
    follow_up_action = str(reviewer_decision.get("follow_up_action") or "none")
    try:
        packet_record = _facade_attr("find_record", find_record)("packets", "packets", "packet_id", coder_packet_id)
    except KeyError:
        packet_record = {}
        logger.warning(
            "Reviewer route could not find packet record for %s during notify payload build",
            coder_packet_id,
        )
    rework = None
    decision = None
    route_classification = classify_rework_route(reviewer_decision)
    review = _facade_attr("record_review", record_review)(
        packet_id=coder_packet_id,
        verdict=verdict,
        reasons=review_reasons,
        follow_up_action=follow_up_action,
    )
    if verdict == ReviewVerdict.ACCEPTED:
        _facade_attr("mark_packet_status_task", mark_packet_status_task)(reviewer_packet_id, PacketStatus.ACCEPTED.value)
        _facade_attr("mark_packet_status_task", mark_packet_status_task)(coder_packet_id, PacketStatus.ACCEPTED.value)
    elif verdict == ReviewVerdict.REWORK_REQUIRED:
        _facade_attr("mark_packet_status_task", mark_packet_status_task)(reviewer_packet_id, PacketStatus.ACCEPTED.value)
        if create_rework:
            if route_classification == REWORK_ROUTE_SELF_RESOLVABLE:
                if rework_routing_policy == REWORK_ROUTING_AUTO_BUNDLE:
                    rework = create_rework_bundle_from_review(
                        packet_id=coder_packet_id,
                        reviewer_packet_id=reviewer_packet_id,
                        reasons=review_reasons,
                    )
                else:
                    rework = architect_rework_packet
                    if rework is None:
                        decision = create_architect_decision_from_review(
                            coder_packet_id,
                            review_reasons,
                            route_classification=route_classification,
                            requested_action=(
                                "Architect rework packet did not produce a bounded direct coder packet; "
                                "inspect architect routing output before continuing."
                            ),
                        )
            elif route_classification in {REWORK_ROUTE_REQUIRES_USER_DECISION, REWORK_ROUTE_REQUIRES_PLANNER}:
                decision = create_architect_decision_from_review(
                    coder_packet_id,
                    review_reasons,
                    route_classification=route_classification,
                )
        _facade_attr("mark_packet_status_task", mark_packet_status_task)(coder_packet_id, PacketStatus.REWORK_REQUIRED.value)
    elif verdict == ReviewVerdict.ESCALATE_TO_ARCHITECT:
        _facade_attr("mark_packet_status_task", mark_packet_status_task)(reviewer_packet_id, PacketStatus.ACCEPTED.value)
        decision = create_architect_decision_from_review(
            coder_packet_id,
            review_reasons,
            route_classification=REWORK_ROUTE_REQUIRES_USER_DECISION,
        )
        _facade_attr("mark_packet_status_task", mark_packet_status_task)(coder_packet_id, PacketStatus.ESCALATE_TO_ARCHITECT.value)
    else:
        _facade_attr("mark_packet_status_task", mark_packet_status_task)(reviewer_packet_id, PacketStatus.BLOCKED.value)
        _facade_attr("mark_packet_status_task", mark_packet_status_task)(coder_packet_id, PacketStatus.BLOCKED.value)
    logger.info("Reviewer routed verdict=%s for packet %s", verdict.value, coder_packet_id)
    _facade_attr("notify_packet_event", notify_packet_event)(
        feature_id=str(packet_record.get("feature_id") or ""),
        packet_id=coder_packet_id,
        role=str(packet_record.get("role") or ""),
        status=verdict.value,
        wave_id=str(packet_record.get("wave_id") or ""),
        title=str(packet_record.get("title") or ""),
        reasons=review_reasons,
    )
    return {
        "review": review,
        "rework": rework,
        "decision": decision,
        "reviewer_verdict": verdict.value,
        "route_classification": route_classification,
        "rework_routing_policy": rework_routing_policy,
        "decision_source": reviewer_decision.get("source"),
        "parser_error": reviewer_decision.get("parser_error"),
    }


# START_FUNCTION_CONTRACT
# name: resolve_reviewer_decision_task
# purpose: Resolve reviewer decision from agent output or fallback values.
# inputs:
#   reviewer_run: Reviewer run payload.
#   reviewer_verdict: Optional fallback verdict.
#   review_reasons: Optional fallback reasons.
#   prefer_agent_output: Whether to parse agent output first.
# returns: Reviewer decision dictionary.
# side_effects: Reads agent message artifacts when requested.
# emitted_logs: Prefect task log line.
# error_behavior: Returns blocked parse_error decision on parser failure.
# END_FUNCTION_CONTRACT
@task(task_run_name="review-decision:resolve")
def resolve_reviewer_decision_task(
    reviewer_run: dict,
    reviewer_verdict: str | None,
    review_reasons: list[str] | None,
    prefer_agent_output: bool,
):
    logger = get_run_logger()
    try:
        decision = resolve_reviewer_decision(
            reviewer_run,
            fallback_verdict=reviewer_verdict,
            fallback_reasons=review_reasons,
            prefer_agent_output=prefer_agent_output,
        )
    except ValueError as exc:
        decision = {
            "packet_verdict": ReviewVerdict.BLOCKED.value,
            "follow_up_action": "none",
            "reasons": [f"Reviewer output parse failed: {exc}"],
            "source": "parse_error",
            "parser_error": str(exc),
            "raw_message": "",
        }
    logger.info("Resolved reviewer decision source=%s verdict=%s", decision.get("source"), decision.get("packet_verdict"))
    return decision


# START_FUNCTION_CONTRACT
# name: review_task
# purpose: Record a standalone review-router verdict and optional localized rework packet.
# inputs:
#   packet_id: Packet identifier.
#   verdict: Review verdict string.
#   reasons: Review reasons.
#   create_rework: Whether to create localized rework for rework_required verdicts.
# returns: Review and optional rework dictionary.
# side_effects: Writes review and optional rework state.
# emitted_logs: None.
# error_behavior: Propagates invalid verdict and review/rework creation errors.
# END_FUNCTION_CONTRACT
@task(task_run_name="review-record:{packet_id}:{verdict}")
def review_task(packet_id: str, verdict: str, reasons: list[str], create_rework: bool):
    review = record_review(
        packet_id=packet_id,
        verdict=ReviewVerdict(verdict),
        reasons=reasons,
        follow_up_action="localized_rework" if create_rework else "none",
    )
    rework = None
    if verdict == ReviewVerdict.REWORK_REQUIRED.value and create_rework:
        rework = create_rework_from_review(packet_id, reasons)
    return {"review": review, "rework": rework}
