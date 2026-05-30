# ############################################################################
# AI_HEADER: pipeline_phases.planning_phase
# ROLE: Architect/planner/materialization phase runner for feature_pipeline.
# ############################################################################

# START_MODULE_CONTRACT
# purpose: Run architect and planner setup, materialize packets, validate the graph, and initialize wave progression.
# inputs: Pipeline runtime, mutable state from bootstrap, and facade-bound dependencies.
# returns: Optional early final result for planning or graph failures.
# side_effects: Delegates to Prefect tasks and state helpers that write artifacts, packets, and feature progression.
# emitted_logs: Delegated Prefect task logs.
# error_behavior: Preserves feature_pipeline planning failure envelopes and return dictionaries.
# END_MODULE_CONTRACT

# START_MODULE_MAP
# mapping:
#   - function: run_planning_phase
# END_MODULE_MAP

from __future__ import annotations

import logging

from prefect_grace.models import FeatureStatus, PacketStatus

from prefect_grace.flows.pipeline_phases.context import PipelineDeps, PipelineRuntime, PipelineState

logger = logging.getLogger(__name__)


def _bootstrap_return(state: PipelineState, final_status: dict) -> dict:
    return {
        "feature": state.seeded["feature"],
        "seeded": state.seeded,
        "runs": state.packet_results,
        "review_route": state.review_route,
        "final_status": final_status,
    }


# START_FUNCTION_CONTRACT
# name: run_planning_phase
# purpose: Execute W00 architect/planner orchestration and prepare validated execution waves.
# inputs:
#   runtime: Feature pipeline parameters.
#   deps: Facade-bound task and helper dependencies.
#   state: Bootstrap phase state to mutate.
# returns: Optional final result dictionary when planning cannot continue.
# side_effects: Runs/marks W00 packets, writes artifacts, materializes packet contracts, and persists wave progression.
# emitted_logs: Delegated Prefect task logs.
# error_behavior: Returns existing branch-specific final envelopes for architect, planner, and wave-plan failures.
# END_FUNCTION_CONTRACT
def run_planning_phase(runtime: PipelineRuntime, deps: PipelineDeps, state: PipelineState) -> dict | None:
    with deps.tags(f"feature:{runtime.feature_id}", "flow:feature-pipeline"):
        if runtime.run_architect:
            with deps.tags("wave:W00", "role:architect"):
                architect_run = deps.run_packet_task(
                    state.architect_packet_id,
                    runtime.dry_run,
                    runtime.timeout_seconds,
                )
        else:
            architect_run = {
                "packet_id": state.architect_packet_id,
                "returncode": 0,
                "launcher": "skipped",
                "stdout_path": "",
                "stderr_path": "",
                "last_message_path": "",
            }
        state.packet_results["architect"] = architect_run
        if architect_run.get("returncode") != 0:
            final_status = deps.final_failure(
                feature_id=runtime.feature_id,
                category="environment_blocked",
                next_action="inspect-failed-architect",
            )
            deps.publish_feature_artifacts_task(
                state.seeded["feature"],
                state.packet_results,
                None,
                state.review_route,
                None,
                final_status,
            )
            return _bootstrap_return(state, final_status)
        with deps.tags("wave:W00", "role:architect"):
            deps.mark_packet_status_task(state.architect_packet_id, PacketStatus.ACCEPTED.value)

        architect_artifact_plan = deps.resolve_architect_artifact_plan_task(
            architect_run,
            feature_id=runtime.feature_id,
            title=runtime.title,
            summary=runtime.summary,
            business_context=runtime.business_context,
            prefer_agent_output=runtime.prefer_agent_output,
        )
        state.packet_results["architect_artifact_plan"] = architect_artifact_plan
        architect_artifacts = deps.write_architect_artifacts_task(runtime.feature_id, architect_artifact_plan)
        state.packet_results["architect_artifacts"] = architect_artifacts
        deps.publish_feature_artifacts_task(
            state.seeded["feature"],
            state.packet_results,
            None,
            state.review_route,
            None,
            None,
        )

        architect_payload = dict(architect_artifact_plan.get("payload") or {})
        architect_next_action = deps.architect_plan_next_action(architect_payload)
        architect_contract = deps.architect_packet_candidates_to_contract(architect_payload)

        # Check if planner is required based on architect decision
        architect_requires_planner = deps.should_run_planner(
            run_planner=None,  # Don't pass user override here, we already have it in state
            planner_contract=None,
            architect_plan=architect_payload,
        )
        state.planner_required = state.should_run_planner or architect_requires_planner or architect_next_action == "requires_planner"

        # Log planner bypass decision
        complexity = architect_payload.get("complexity", "unknown")
        requires_planner_field = architect_payload.get("requires_planner")
        if not state.planner_required:
            logger.info(
                f"Planner bypassed for {runtime.feature_id}: "
                f"complexity={complexity}, requires_planner={requires_planner_field}, "
                f"next_action={architect_next_action}"
            )
        else:
            logger.info(
                f"Planner required for {runtime.feature_id}: "
                f"complexity={complexity}, requires_planner={requires_planner_field}, "
                f"next_action={architect_next_action}, user_override={state.should_run_planner}"
            )

        if architect_next_action == "requires_user_decision":
            return _architect_user_decision(runtime, deps, state, architect_payload)

        planner_run = _run_planner(runtime, deps, state)
        state.packet_results["planner"] = planner_run
        if state.planner_required and planner_run.get("returncode") != 0:
            final_status = deps.final_failure(
                feature_id=runtime.feature_id,
                category="environment_blocked",
                next_action="inspect-failed-planner",
            )
            deps.publish_feature_artifacts_task(
                state.seeded["feature"],
                state.packet_results,
                None,
                state.review_route,
                None,
                final_status,
            )
            return _bootstrap_return(state, final_status)
        _mark_planner_status(deps, state)

        planner_contract_result = _resolve_materialize_and_validate(
            runtime,
            deps,
            state,
            planner_run,
            architect_contract,
        )
        if isinstance(planner_contract_result, dict) and planner_contract_result.get("final_status"):
            return _bootstrap_return(state, planner_contract_result["final_status"])

        return _prepare_wave_progression(runtime, deps, state)


def _architect_user_decision(
    runtime: PipelineRuntime,
    deps: PipelineDeps,
    state: PipelineState,
    architect_payload: dict,
) -> dict:
    reasons = list(architect_payload.get("open_decisions") or [])
    feature_record = deps.mark_feature_status(runtime.feature_id, FeatureStatus.ARCHITECT_READY)
    final_status = {
        "feature": feature_record,
        "has_failures": False,
        "final_outcome": "awaiting_architect",
        "user_facing_status": FeatureStatus.ARCHITECT_READY.value,
        "user_summary": deps.final_user_summary(
            outcome="awaiting_architect",
            status=FeatureStatus.ARCHITECT_READY.value,
            summary=str(feature_record.get("summary") or runtime.summary),
            next_action="architect-user-decision-required",
            reasons=reasons,
        ),
        "next_action": "architect-user-decision-required",
        "reasons": reasons,
    }
    deps.publish_feature_artifacts_task(
        state.seeded["feature"],
        state.packet_results,
        None,
        state.review_route,
        None,
        final_status,
    )
    return _bootstrap_return(state, final_status)


def _run_planner(runtime: PipelineRuntime, deps: PipelineDeps, state: PipelineState) -> dict:
    if state.planner_required and state.planner_packet_id:
        with deps.tags("wave:W00", "role:planner"):
            return deps.run_packet_task(state.planner_packet_id, runtime.dry_run, runtime.timeout_seconds)
    return {
        "packet_id": state.planner_packet_id,
        "returncode": 0,
        "launcher": "skipped",
        "stdout_path": "",
        "stderr_path": "",
        "last_message_path": "",
    }


def _mark_planner_status(deps: PipelineDeps, state: PipelineState) -> None:
    if state.planner_required and state.planner_packet_id:
        with deps.tags("wave:W00", "role:planner"):
            deps.mark_packet_status_task(state.planner_packet_id, PacketStatus.ACCEPTED.value)
    elif state.planner_packet_id:
        try:
            deps.update_record(
                "packets",
                "packets",
                "packet_id",
                state.planner_packet_id,
                {"status": PacketStatus.DRAFT.value},
            )
        except KeyError:
            pass


def _resolve_materialize_and_validate(
    runtime: PipelineRuntime,
    deps: PipelineDeps,
    state: PipelineState,
    planner_run: dict,
    architect_contract: dict | None,
) -> dict | None:
    planner_contract_result = deps.resolve_planner_contract_task(
        planner_run,
        planner_packet_id=state.planner_packet_id,
        architect_packet_id=state.architect_packet_id,
        feature_id=runtime.feature_id,
        implementation_title=runtime.implementation_title,
        implementation_summary=runtime.implementation_summary,
        verifier_backend_profile=runtime.verifier_backend_profile,
        verifier_frontend_profile=runtime.verifier_frontend_profile,
        verifier_frontend_commands=runtime.verifier_frontend_commands,
        verifier_observability_profile=runtime.verifier_observability_profile,
        verifier_observability_commands=runtime.verifier_observability_commands,
        verifier_artifact_globs=runtime.verifier_artifact_globs,
        verifier_touches_frontend=runtime.verifier_touches_frontend,
        verifier_requires_frontend_visual=runtime.verifier_requires_frontend_visual,
        verifier_include_day_live_canary=runtime.verifier_include_day_live_canary,
        planner_contract_override=runtime.planner_contract if state.planner_required else (architect_contract or runtime.planner_contract),
        prefer_agent_output=runtime.prefer_agent_output and state.planner_required,
    )
    state.packet_results["planner_contract"] = planner_contract_result
    if state.planner_required and runtime.prefer_agent_output and planner_contract_result.get("parser_error") and planner_contract_result.get("source") != "agent_output":
        final_status = deps.final_failure(
            feature_id=runtime.feature_id,
            category="pipeline_invalid",
            next_action="fix-planner-agent-output",
            reasons=[str(planner_contract_result["parser_error"])],
        )
        deps.publish_feature_artifacts_task(state.seeded["feature"], state.packet_results, None, state.review_route, None, final_status)
        return {"final_status": final_status}

    state.materialized_contract = deps.materialize_planner_contract_task(
        runtime.feature_id,
        state.planner_packet_id,
        state.architect_packet_id,
        planner_contract_result,
        runtime.agent_workdir,
        runtime.agent_sandbox,
        runtime.verifier_backend_profile,
        runtime.verifier_frontend_profile,
        runtime.verifier_frontend_commands,
        runtime.verifier_observability_profile,
        runtime.verifier_observability_commands,
        runtime.verifier_artifact_globs,
        runtime.verifier_touches_frontend,
        runtime.verifier_requires_frontend_visual,
        runtime.verifier_include_day_live_canary,
    )
    state.packet_results["planner_materialized"] = state.materialized_contract
    deps.sync_architect_manifest_packets(
        feature_id=runtime.feature_id,
        generated_packets=list(state.materialized_contract.get("packets") or []),
        architect_packet_id=state.architect_packet_id,
    )
    planner_validation = deps.validate_planner_contract_task(runtime.feature_id, state.materialized_contract)
    state.packet_results["planner_validation"] = planner_validation
    deps.publish_feature_artifacts_task(state.seeded["feature"], state.packet_results, None, state.review_route, None, None)
    if not planner_validation["valid"]:
        final_status = deps.final_failure(
            feature_id=runtime.feature_id,
            category="pipeline_invalid",
            next_action="fix-packet-graph-contract",
            reasons=list(planner_validation.get("issues") or []),
        )
        deps.publish_feature_artifacts_task(state.seeded["feature"], state.packet_results, None, state.review_route, None, final_status)
        return {"final_status": final_status}
    return None


def _prepare_wave_progression(runtime: PipelineRuntime, deps: PipelineDeps, state: PipelineState) -> dict | None:
    state.generated_packets = list(state.materialized_contract["packets"])
    state.packets_by_id = deps.packet_map(state.generated_packets)
    state.wave_packets_by_id = deps.wave_packets_by_wave_id(state.generated_packets)
    architect_manifest = deps.load_architect_manifest(runtime.feature_id)
    state.wave_progression = deps.build_wave_progression(
        architect_manifest=architect_manifest,
        planner_waves=list(state.materialized_contract.get("waves") or []),
        generated_packets=state.generated_packets,
    )
    state.packet_results["wave_progression"] = [dict(item) for item in state.wave_progression]
    deps.persist_wave_progression(runtime.feature_id, state.wave_progression)
    wave_progression_issues = deps.required_wave_progression_issues(state.wave_progression)
    if not wave_progression_issues:
        return None

    for issue in wave_progression_issues:
        issue_wave_id = deps.wave_id_from_issue(issue)
        if issue_wave_id:
            deps.set_wave_progression_status(
                feature_id=runtime.feature_id,
                wave_progression=state.wave_progression,
                wave_id=issue_wave_id,
                status="blocked",
                reasons=[issue],
            )
    state.packet_results["wave_progression"] = [dict(item) for item in state.wave_progression]
    final_status = deps.final_failure(
        feature_id=runtime.feature_id,
        category="pipeline_invalid",
        next_action="fix-wave-plan-continuation",
        reasons=wave_progression_issues,
        next_wave_id=deps.wave_id_from_issue(wave_progression_issues[0])
        or deps.next_required_wave_id(state.wave_progression),
    )
    deps.persist_wave_progression(runtime.feature_id, state.wave_progression)
    deps.publish_feature_artifacts_task(state.seeded["feature"], state.packet_results, None, state.review_route, None, final_status)
    return _bootstrap_return(state, final_status)
