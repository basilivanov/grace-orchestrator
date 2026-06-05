# ############################################################################
# AI_HEADER: pipeline_phases.context
# ROLE: Runtime context and dependency containers for feature_pipeline phase runners.
# ############################################################################

# START_MODULE_CONTRACT
# purpose: Provide explicit data containers shared by plain-Python feature pipeline phase runners.
# inputs: Feature pipeline parameters, facade-bound dependency callables, and mutable orchestration state.
# returns: Typed dataclass instances used by phase runners.
# side_effects: None.
# emitted_logs: None.
# error_behavior: Performs no IO and raises only normal dataclass construction errors.
# END_MODULE_CONTRACT

# START_MODULE_MAP
# mapping:
#   - dataclass: PipelineRuntime
#   - dataclass: PipelineDeps
#   - dataclass: PipelineState
#   - function: pipeline_return
# END_MODULE_MAP

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable


AnyCallable = Callable[..., Any]


@dataclass(frozen=True)
class PipelineRuntime:
    feature_id: str
    title: str
    summary: str
    implementation_title: str
    implementation_summary: str
    dry_run: bool
    timeout_seconds: int
    verifier_backend_profile: str | None
    verifier_frontend_profile: str | None
    verifier_frontend_commands: list[str] | None
    verifier_observability_profile: str | None
    verifier_observability_commands: list[str] | None
    verifier_artifact_globs: list[str] | None
    verifier_touches_frontend: bool
    verifier_requires_frontend_visual: bool
    verifier_include_day_live_canary: bool
    agent_workdir: str | None
    agent_sandbox: str | None
    business_context: dict | None
    planner_contract: dict | None
    reviewer_verdict: str | None
    review_reasons: list[str] | None
    verifier_test_verdict: str | None
    verifier_observability_verdict: str | None
    verifier_frontend_visual_verdict: str | None
    verifier_commands_run: list[str] | None
    verifier_evidence_paths: list[str] | None
    verifier_blocking_issues: list[str] | None
    wave_verdict: str | None
    wave_reasons: list[str] | None
    create_rework: bool
    prefer_agent_output: bool
    run_architect: bool
    run_planner: bool | None
    commit_hash: str | None
    rework_routing_policy: str
    reviewer_verdict_script: list[str] | None
    review_reasons_script: list[list[str]] | None
    wave_verdict_script: list[str] | None
    wave_reasons_script: list[list[str]] | None


@dataclass(frozen=True)
class PipelineDeps:
    tags: AnyCallable
    seed_feature_packets_task: AnyCallable
    mark_feature_in_progress_task: AnyCallable
    record_canon_digest_task: AnyCallable
    run_packet_task: AnyCallable
    run_verifier_packet_task: AnyCallable
    mark_packet_status_task: AnyCallable
    resolve_architect_artifact_plan_task: AnyCallable
    write_architect_artifacts_task: AnyCallable
    publish_feature_artifacts_task: AnyCallable
    resolve_planner_contract_task: AnyCallable
    materialize_planner_contract_task: AnyCallable
    validate_planner_contract_task: AnyCallable
    resolve_verifier_result_task: AnyCallable
    record_verifier_result_task: AnyCallable
    resolve_reviewer_decision_task: AnyCallable
    route_reviewer_verdict_task: AnyCallable
    publish_packet_review_artifacts_task: AnyCallable
    resolve_wave_decision_task: AnyCallable
    route_architect_wave_verdict_task: AnyCallable
    final_failure: AnyCallable
    post_acceptance_final_status: AnyCallable
    final_user_summary: AnyCallable
    should_run_planner: AnyCallable
    architect_plan_next_action: AnyCallable
    architect_packet_candidates_to_contract: AnyCallable
    sync_architect_manifest_packets: AnyCallable
    load_architect_manifest: AnyCallable
    build_wave_progression: AnyCallable
    persist_wave_progression: AnyCallable
    set_wave_progression_status: AnyCallable
    required_wave_progression_issues: AnyCallable
    wave_id_from_issue: AnyCallable
    next_required_wave_id: AnyCallable
    all_required_waves_accepted: AnyCallable
    wave_packets_by_wave_id: AnyCallable
    packet_map: AnyCallable
    order_packets_for_wave: AnyCallable
    missing_internal_dependencies: AnyCallable
    append_unique_packet: AnyCallable
    packet_result_key: AnyCallable
    packet_has_downstream_reviewer: AnyCallable
    reviewer_target_packet_id: AnyCallable
    normalize_reviewer_decision_for_pipeline: AnyCallable
    escalate_repeated_observability_rework_for_pipeline: AnyCallable
    classify_rework_route: AnyCallable
    classify_rework_mode: AnyCallable
    create_architect_rework_packet_from_review: AnyCallable
    build_architect_direct_rework: AnyCallable
    build_light_resume_followup: AnyCallable
    build_direct_rework_followup_packets: AnyCallable
    update_record: AnyCallable
    mark_feature_status: AnyCallable
    notify_feature_event: AnyCallable


@dataclass
class PipelineState:
    seeded: dict = field(default_factory=dict)
    packet_results: dict[str, dict] = field(default_factory=dict)
    review_route: dict | None = None
    canon_digest_packet_id: str = ""
    architect_packet_id: str = ""
    should_run_planner: bool = False
    planner_packet: dict | None = None
    planner_packet_id: str = ""
    planner_required: bool = False
    materialized_contract: dict = field(default_factory=dict)
    generated_packets: list[dict] = field(default_factory=list)
    packets_by_id: dict[str, dict] = field(default_factory=dict)
    wave_packets_by_id: dict[str, list[dict]] = field(default_factory=dict)
    wave_progression: list[dict[str, object]] = field(default_factory=list)
    verification_records: list[dict] = field(default_factory=list)
    review_routes: list[dict] = field(default_factory=list)
    wave_routes: list[dict] = field(default_factory=list)
    wave_packet_sets: dict[str, set[str]] = field(default_factory=dict)
    completed_packet_ids: set[str] = field(default_factory=set)
    reviewer_decision_index: int = 0
    wave_decision_index: int = 0


# START_FUNCTION_CONTRACT
# name: pipeline_return
# purpose: Build the common feature pipeline return envelope for wave and finalization branches.
# inputs:
#   state: Mutable pipeline state containing seeded feature, runs, verification records, reviews, and wave routes.
#   final_status: Branch-specific final status payload.
# returns: Feature pipeline result dictionary with common execution keys.
# side_effects: None.
# emitted_logs: None.
# error_behavior: Propagates missing required state keys.
# END_FUNCTION_CONTRACT
def pipeline_return(state: PipelineState, final_status: dict) -> dict:
    return {
        "feature": state.seeded["feature"],
        "seeded": state.seeded,
        "runs": state.packet_results,
        "verification_records": state.verification_records,
        "review_routes": state.review_routes,
        "wave_routes": state.wave_routes,
        "final_status": final_status,
    }
