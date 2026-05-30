# ############################################################################
# AI_HEADER: pipeline_tasks.wave_tasks
# ROLE: Architect wave decision Prefect tasks for feature_pipeline.
# ############################################################################

# START_MODULE_CONTRACT
# purpose: Resolve architect wave decisions and route wave verdicts for feature_pipeline.
# inputs: Feature ids, wave ids, architect packet ids, architect run payloads, fallback verdicts, and reasons.
# returns: Wave decision and wave route dictionaries.
# side_effects: Writes wave reviews and packet statuses through existing APIs.
# emitted_logs: Prefect task logs.
# error_behavior: Preserves parse fallback behavior and propagates state update errors.
# END_MODULE_CONTRACT

# START_MODULE_MAP
# mapping:
#   - function: route_architect_wave_verdict_task
#   - function: resolve_wave_decision_task
# END_MODULE_MAP

from __future__ import annotations

from prefect_grace.flows.pipeline_tasks.execution_tasks import mark_packet_status_task
from prefect_grace.models import PacketStatus, WaveVerdict
from prefect_grace.prefect_compat import get_run_logger, task
from prefect_grace.tasks.agent_output_parser import resolve_wave_decision
from prefect_grace.tasks.review_router import record_wave_review


# START_FUNCTION_CONTRACT
# name: route_architect_wave_verdict_task
# purpose: Record and apply an architect wave gate verdict.
# inputs:
#   feature_id: Feature identifier.
#   wave_id: Wave identifier.
#   architect_packet_id: Architect gate packet id.
#   wave_decision: Resolved wave decision dictionary.
# returns: Wave route dictionary.
# side_effects: Writes wave review and updates architect packet status.
# emitted_logs: Prefect task log line.
# error_behavior: Propagates invalid verdict/status and state update errors.
# END_FUNCTION_CONTRACT
@task(task_run_name="wave-route:{feature_id}:{wave_id}")
def route_architect_wave_verdict_task(
    feature_id: str,
    wave_id: str,
    architect_packet_id: str,
    wave_decision: dict,
):
    logger = get_run_logger()
    verdict = WaveVerdict(wave_decision["wave_verdict"])
    wave_reasons = list(wave_decision.get("reasons") or [])
    review = record_wave_review(
        feature_id=feature_id,
        wave_id=wave_id,
        architect_packet_id=architect_packet_id,
        verdict=verdict,
        reasons=wave_reasons,
    )
    if verdict == WaveVerdict.ACCEPTED:
        mark_packet_status_task(architect_packet_id, PacketStatus.ACCEPTED.value)
    elif verdict == WaveVerdict.REWORK_REQUIRED:
        mark_packet_status_task(architect_packet_id, PacketStatus.REWORK_REQUIRED.value)
    else:
        mark_packet_status_task(architect_packet_id, PacketStatus.BLOCKED.value)
    logger.info("Architect wave gate routed verdict=%s for %s/%s", verdict.value, feature_id, wave_id)
    return {
        "wave_review": review,
        "wave_verdict": verdict.value,
        "decision_source": wave_decision.get("source"),
        "parser_error": wave_decision.get("parser_error"),
    }


# START_FUNCTION_CONTRACT
# name: resolve_wave_decision_task
# purpose: Resolve architect wave decision from agent output or fallback values.
# inputs:
#   architect_wave_run: Architect wave run payload.
#   wave_verdict: Optional fallback verdict.
#   wave_reasons: Optional fallback reasons.
#   prefer_agent_output: Whether to parse agent output first.
# returns: Wave decision dictionary.
# side_effects: Reads agent message artifacts when requested.
# emitted_logs: Prefect task log line.
# error_behavior: Returns blocked parse_error decision on parser failure.
# END_FUNCTION_CONTRACT
@task(task_run_name="wave-decision:resolve")
def resolve_wave_decision_task(
    architect_wave_run: dict,
    wave_verdict: str | None,
    wave_reasons: list[str] | None,
    prefer_agent_output: bool,
):
    logger = get_run_logger()
    try:
        decision = resolve_wave_decision(
            architect_wave_run,
            fallback_verdict=wave_verdict,
            fallback_reasons=wave_reasons,
            prefer_agent_output=prefer_agent_output,
        )
    except ValueError as exc:
        decision = {
            "wave_verdict": WaveVerdict.BLOCKED.value,
            "reasons": [f"Architect wave output parse failed: {exc}"],
            "source": "parse_error",
            "parser_error": str(exc),
            "raw_message": "",
        }
    logger.info("Resolved architect wave decision source=%s verdict=%s", decision.get("source"), decision.get("wave_verdict"))
    return decision
