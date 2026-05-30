# ############################################################################
# AI_HEADER: pipeline_tasks.architect_tasks
# ROLE: Architect artifact Prefect tasks for feature_pipeline.
# ############################################################################

# START_MODULE_CONTRACT
# purpose: Resolve and write architect artifact plans for feature_pipeline.
# inputs: Architect run payloads, feature metadata, business context, and artifact plans.
# returns: Architect artifact plan and written artifact metadata dictionaries.
# side_effects: May write architect artifact files through existing architect_artifacts APIs.
# emitted_logs: Prefect task logs.
# error_behavior: Preserves fallback behavior for unparseable architect output and propagates write errors.
# END_MODULE_CONTRACT

# START_MODULE_MAP
# mapping:
#   - function: resolve_architect_artifact_plan_task
#   - function: write_architect_artifacts_task
# END_MODULE_MAP

from __future__ import annotations

from prefect_grace.prefect_compat import get_run_logger, task
from prefect_grace.tasks.agent_output_parser import (
    parse_architect_artifact_plan_message,
    read_agent_message,
)
from prefect_grace.tasks.architect_artifacts import (
    default_architect_artifact_plan,
    write_architect_artifacts,
)


# START_FUNCTION_CONTRACT
# name: resolve_architect_artifact_plan_task
# purpose: Resolve architect artifact plan from agent output or fallback defaults.
# inputs:
#   architect_run: Architect run payload.
#   feature_id: Feature identifier.
#   title: Feature title.
#   summary: Feature summary.
#   business_context: Optional business context dictionary.
#   prefer_agent_output: Whether to parse agent output before fallback.
# returns: Dict with payload, source, and parser_error.
# side_effects: Reads agent message artifacts when requested.
# emitted_logs: Prefect task log line.
# error_behavior: Falls back to default plan on parser errors.
# END_FUNCTION_CONTRACT
@task(task_run_name="architect-artifacts:resolve:{feature_id}")
def resolve_architect_artifact_plan_task(
    architect_run: dict,
    *,
    feature_id: str,
    title: str,
    summary: str,
    business_context: dict | None,
    prefer_agent_output: bool,
) -> dict:
    logger = get_run_logger()
    parser_error = None
    payload = None
    if prefer_agent_output:
        try:
            payload = parse_architect_artifact_plan_message(
                read_agent_message(architect_run.get("last_message_path"), architect_run.get("stdout_path"))
            )
            source = "agent_output"
        except ValueError as exc:
            parser_error = str(exc)
    if payload is None:
        payload = default_architect_artifact_plan(
            feature_id=feature_id,
            title=title,
            summary=summary,
            business_context=business_context,
        )
        source = "fallback"
    logger.info("Resolved architect artifact plan source=%s parser_error=%s", source, parser_error)
    return {"payload": payload, "source": source, "parser_error": parser_error}


# START_FUNCTION_CONTRACT
# name: write_architect_artifacts_task
# purpose: Write architect artifacts from a resolved architect plan.
# inputs:
#   feature_id: Feature identifier.
#   architect_artifact_plan: Resolved plan dictionary with payload key.
# returns: Written artifact metadata dictionary.
# side_effects: Writes architect artifact files.
# emitted_logs: Prefect task log line.
# error_behavior: Propagates write_architect_artifacts errors.
# END_FUNCTION_CONTRACT
@task(task_run_name="architect-artifacts:write:{feature_id}")
def write_architect_artifacts_task(
    feature_id: str,
    architect_artifact_plan: dict,
) -> dict:
    logger = get_run_logger()
    written = write_architect_artifacts(
        feature_id=feature_id,
        architect_payload=architect_artifact_plan["payload"],
    )
    logger.info("Wrote architect slice docs for %s at %s", feature_id, written.get("slice_dir"))
    return written
