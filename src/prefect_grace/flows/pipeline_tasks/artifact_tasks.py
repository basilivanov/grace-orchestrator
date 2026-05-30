# ############################################################################
# AI_HEADER: pipeline_tasks.artifact_tasks
# ROLE: Verifier and Prefect artifact publication tasks for feature_pipeline.
# ############################################################################

# START_MODULE_CONTRACT
# purpose: Resolve verifier results, record verifier evidence, and publish feature/packet artifacts.
# inputs: Verifier run/result payloads, feature records, packet results, review routes, wave routes, and final statuses.
# returns: Verifier result/record dictionaries and artifact id lists.
# side_effects: Reads verifier artifacts, writes verification records, and publishes Prefect artifacts through existing APIs.
# emitted_logs: Prefect task logs.
# error_behavior: Preserves verifier parse fallback behavior and propagates recording/publish errors.
# END_MODULE_CONTRACT

# START_MODULE_MAP
# mapping:
#   - function: resolve_verifier_result_task
#   - function: record_verifier_result_task
#   - function: publish_packet_review_artifacts_task
#   - function: publish_feature_artifacts_task
# END_MODULE_MAP

from __future__ import annotations

import sys

from prefect_grace.flows.pipeline_helpers.evidence_collector import enrich_verifier_evidence_paths
from prefect_grace.models import (
    FrontendVisualVerdict,
    ObservabilityVerdict,
    TestVerdict,
)
from prefect_grace.prefect_compat import get_run_logger, task
from prefect_grace.tasks.agent_output_parser import resolve_verifier_result
from prefect_grace.tasks.prefect_artifacts import publish_feature_artifacts, publish_packet_task_artifacts
from prefect_grace.tasks.state_store import find_record
from prefect_grace.tasks.verification_router import record_verification


def _facade_attr(name: str, default):
    facade = sys.modules.get("prefect_grace.flows.feature_pipeline")
    return getattr(facade, name, default) if facade is not None else default


# START_FUNCTION_CONTRACT
# name: resolve_verifier_result_task
# purpose: Resolve verifier result from agent output or fallback values and enrich evidence paths.
# inputs: Verifier run payload, fallback verifier verdicts/evidence, blocking issues, and parse preference.
# returns: Verifier result dictionary.
# side_effects: Reads verifier output artifacts and supplemental evidence metadata.
# emitted_logs: Prefect task log line.
# error_behavior: Returns failed parse_error verifier result on parser failure.
# END_FUNCTION_CONTRACT
@task(task_run_name="verifier-result:resolve")
def resolve_verifier_result_task(
    verifier_run: dict,
    verifier_test_verdict: str | None,
    verifier_observability_verdict: str | None,
    verifier_frontend_visual_verdict: str | None,
    verifier_commands_run: list[str] | None,
    verifier_evidence_paths: list[str] | None,
    verifier_blocking_issues: list[str] | None,
    prefer_agent_output: bool,
):
    logger = get_run_logger()
    try:
        result = resolve_verifier_result(
            verifier_run,
            fallback_test_verdict=verifier_test_verdict,
            fallback_observability_verdict=verifier_observability_verdict,
            fallback_frontend_visual_verdict=verifier_frontend_visual_verdict,
            fallback_commands_run=verifier_commands_run,
            fallback_evidence_paths=verifier_evidence_paths,
            fallback_blocking_issues=verifier_blocking_issues,
            prefer_agent_output=prefer_agent_output,
        )
        result = enrich_verifier_evidence_paths(verifier_run, result)
    except ValueError as exc:
        result = {
            "test_verdict": TestVerdict.FAILED.value,
            "observability_verdict": ObservabilityVerdict.NO_EVIDENCE_BLOCKER.value,
            "frontend_visual_verdict": FrontendVisualVerdict.NOT_APPLICABLE.value,
            "commands_run": [],
            "evidence_paths": [],
            "blocking_issues": [f"Verifier output parse failed: {exc}"],
            "source": "parse_error",
            "parser_error": str(exc),
            "raw_message": "",
        }
    logger.info(
        "Resolved verifier result source=%s test=%s obs=%s",
        result.get("source"),
        result.get("test_verdict"),
        result.get("observability_verdict"),
    )
    return result


# START_FUNCTION_CONTRACT
# name: record_verifier_result_task
# purpose: Persist verifier result evidence and publish packet task artifacts.
# inputs:
#   verifier_packet_id: Verifier packet identifier.
#   verifier_result: Resolved verifier result dictionary.
# returns: Verification record dictionary.
# side_effects: Writes verification record and publishes Prefect artifacts.
# emitted_logs: Prefect task log lines.
# error_behavior: Propagates recording/publish errors.
# END_FUNCTION_CONTRACT
@task(task_run_name="record-verifier:{verifier_packet_id}")
def record_verifier_result_task(
    verifier_packet_id: str,
    verifier_result: dict,
):
    logger = get_run_logger()
    record = record_verification(
        packet_id=verifier_packet_id,
        test_verdict=verifier_result["test_verdict"],
        observability_verdict=verifier_result["observability_verdict"],
        frontend_visual_verdict=verifier_result["frontend_visual_verdict"],
        commands_run=list(verifier_result.get("commands_run") or []),
        evidence_paths=list(verifier_result.get("evidence_paths") or []),
        blocking_issues=list(verifier_result.get("blocking_issues") or []),
    )
    logger.info("Recorded verifier evidence for %s", verifier_packet_id)
    artifact_ids = publish_packet_task_artifacts(verification=record)
    if artifact_ids:
        logger.info("Published %s verifier task artifacts for %s", len(artifact_ids), verifier_packet_id)
    return record


# START_FUNCTION_CONTRACT
# name: publish_packet_review_artifacts_task
# purpose: Publish packet review artifacts for a reviewer route.
# inputs:
#   review_route: Review route dictionary.
# returns: Prefect artifact id list.
# side_effects: Publishes Prefect artifacts through existing API.
# emitted_logs: Prefect task log line.
# error_behavior: Propagates artifact publication errors.
# END_FUNCTION_CONTRACT
@task(task_run_name="packet-review-artifacts:{review_route[review][packet_id]}")
def publish_packet_review_artifacts_task(review_route: dict):
    logger = get_run_logger()
    artifact_ids = publish_packet_task_artifacts(review_route=review_route)
    logger.info("Published %s packet review artifacts", len(artifact_ids))
    return artifact_ids


# START_FUNCTION_CONTRACT
# name: publish_feature_artifacts_task
# purpose: Publish feature-level Prefect artifacts for the current pipeline state.
# inputs: Feature record, packet results, optional verification/review/wave route/final status payloads.
# returns: Prefect artifact id list.
# side_effects: Reads latest feature record and publishes Prefect artifacts.
# emitted_logs: Prefect task log line.
# error_behavior: Propagates artifact publication errors.
# END_FUNCTION_CONTRACT
@task(task_run_name="feature-artifacts:{feature[feature_id]}")
def publish_feature_artifacts_task(
    feature: dict,
    packet_results: dict,
    verification: dict | None,
    review_route: dict | None,
    wave_route: dict | None,
    final_status: dict | None,
):
    logger = get_run_logger()
    current_feature = feature
    feature_id = str(feature.get("feature_id") or "").strip()
    if feature_id:
        try:
            current_feature = find_record("features", "features", "feature_id", feature_id)
        except KeyError:
            current_feature = feature
    publisher = _facade_attr("publish_feature_artifacts", publish_feature_artifacts)
    artifact_ids = publisher(
        feature=current_feature,
        packet_results=packet_results,
        verification=verification,
        review_route=review_route,
        wave_route=wave_route,
        final_status=final_status,
    )
    logger.info("Published %s feature artifacts", len(artifact_ids))
    return artifact_ids
