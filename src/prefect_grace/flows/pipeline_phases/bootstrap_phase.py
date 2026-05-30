# ############################################################################
# AI_HEADER: pipeline_phases.bootstrap_phase
# ROLE: Bootstrap and canon-digest phase runner for feature_pipeline.
# ############################################################################

# START_MODULE_CONTRACT
# purpose: Seed feature packets, mark the feature in progress, initialize phase state, and run canon digest preflight.
# inputs: Pipeline runtime parameters and facade-bound dependencies.
# returns: PipelineState plus an optional early final result on canon digest failure.
# side_effects: Delegates to Prefect tasks that update state, run packets, and publish artifacts.
# emitted_logs: Prefect task logs through delegated tasks.
# error_behavior: Preserves feature_pipeline canon digest failure envelope.
# END_MODULE_CONTRACT

# START_MODULE_MAP
# mapping:
#   - function: run_bootstrap_phase
# END_MODULE_MAP

from __future__ import annotations

from prefect_grace.models import PacketStatus

from prefect_grace.flows.pipeline_phases.context import PipelineDeps, PipelineRuntime, PipelineState


# START_FUNCTION_CONTRACT
# name: run_bootstrap_phase
# purpose: Execute feature seeding, in-progress marking, and optional canon digest preflight.
# inputs:
#   runtime: Feature pipeline parameters.
#   deps: Facade-bound task and helper dependencies.
# returns: Tuple-like pair of PipelineState and optional final result dictionary.
# side_effects: Writes seeded state and may publish final artifacts when canon digest fails.
# emitted_logs: Delegated Prefect task logs.
# error_behavior: Returns environment_blocked final result for failed canon digest.
# END_FUNCTION_CONTRACT
def run_bootstrap_phase(runtime: PipelineRuntime, deps: PipelineDeps) -> tuple[PipelineState, dict | None]:
    with deps.tags(f"feature:{runtime.feature_id}", "flow:feature-pipeline"):
        seeded = deps.seed_feature_packets_task(
            feature_id=runtime.feature_id,
            title=runtime.title,
            summary=runtime.summary,
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
            agent_workdir=runtime.agent_workdir,
            agent_sandbox=runtime.agent_sandbox,
            business_context=runtime.business_context,
            planner_contract=runtime.planner_contract,
            include_planner_packet=bool(runtime.run_planner),
            materialize_execution_packets=False,
        )
        deps.mark_feature_in_progress_task(runtime.feature_id)
        state = PipelineState(seeded=seeded)
        state.canon_digest_packet_id = str((seeded["packets"].get("canon_digest") or {}).get("packet_id") or "")
        state.architect_packet_id = seeded["packets"]["architect"]["packet_id"]
        state.should_run_planner = deps.should_run_planner(
            run_planner=runtime.run_planner,
            planner_contract=runtime.planner_contract,
        )
        state.planner_packet = seeded["packets"].get("planner")
        state.planner_packet_id = str((state.planner_packet or {}).get("packet_id") or "")

        if not state.canon_digest_packet_id:
            return state, None

        with deps.tags("wave:W00", "role:canon_digest"):
            canon_digest_run = deps.run_packet_task(
                state.canon_digest_packet_id,
                runtime.dry_run,
                runtime.timeout_seconds,
            )
        state.packet_results["canon_digest"] = canon_digest_run
        if canon_digest_run.get("returncode") == 0:
            deps.record_canon_digest_task(runtime.feature_id, canon_digest_run)
            deps.mark_packet_status_task(state.canon_digest_packet_id, PacketStatus.ACCEPTED.value)
            return state, None

        deps.mark_packet_status_task(state.canon_digest_packet_id, PacketStatus.BLOCKED.value)
        final_status = deps.final_failure(
            feature_id=runtime.feature_id,
            category="environment_blocked",
            next_action="inspect-failed-canon-digest",
            reasons=["canon_digest preflight failed before architect formalization"],
        )
        deps.publish_feature_artifacts_task(
            seeded["feature"],
            state.packet_results,
            None,
            state.review_route,
            None,
            final_status,
        )
        return state, {
            "feature": seeded["feature"],
            "seeded": seeded,
            "runs": state.packet_results,
            "review_route": state.review_route,
            "final_status": final_status,
        }
