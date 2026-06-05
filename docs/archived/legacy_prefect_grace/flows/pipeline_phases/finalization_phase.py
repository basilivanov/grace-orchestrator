# ############################################################################
# AI_HEADER: pipeline_phases.finalization_phase
# ROLE: Final required-wave and acceptance phase runner for feature_pipeline.
# ############################################################################

# START_MODULE_CONTRACT
# purpose: Enforce required wave completion, mark accepted features, publish final artifacts, and return the final pipeline envelope.
# inputs: Pipeline runtime, completed wave execution state, and facade-bound dependencies.
# returns: Feature pipeline result dictionary.
# side_effects: Updates feature status, sends final notifications, and publishes final feature artifacts.
# emitted_logs: Delegated Prefect task logs.
# error_behavior: Preserves incomplete-wave failure and accepted/awaiting-commit final envelopes.
# END_MODULE_CONTRACT

# START_MODULE_MAP
# mapping:
#   - function: run_finalization_phase
# END_MODULE_MAP

from __future__ import annotations

from prefect_grace.flows.pipeline_phases.context import (
    PipelineDeps,
    PipelineRuntime,
    PipelineState,
    pipeline_return,
)
from prefect_grace.models import FeatureStatus


def _last_verification(state: PipelineState) -> dict | None:
    return state.verification_records[-1] if state.verification_records else None


def _last_review(state: PipelineState) -> dict | None:
    return state.review_routes[-1] if state.review_routes else None


def _last_wave(state: PipelineState) -> dict | None:
    return state.wave_routes[-1] if state.wave_routes else None


# START_FUNCTION_CONTRACT
# name: run_finalization_phase
# purpose: Complete the feature pipeline after all execution waves have run.
# inputs:
#   runtime: Feature pipeline parameters.
#   deps: Facade-bound task and helper dependencies.
#   state: Wave execution state to finalize.
# returns: Final feature pipeline result dictionary.
# side_effects: Writes final feature status, notifies observers, and publishes artifacts.
# emitted_logs: Delegated Prefect task logs.
# error_behavior: Returns pipeline_invalid for incomplete required waves, otherwise accepted or awaiting_commit status.
# END_FUNCTION_CONTRACT
def run_finalization_phase(runtime: PipelineRuntime, deps: PipelineDeps, state: PipelineState) -> dict:
    with deps.tags(f"feature:{runtime.feature_id}", "flow:feature-pipeline"):
        if not deps.all_required_waves_accepted(state.wave_progression):
            return _incomplete_required_waves(runtime, deps, state)

        accepted_feature = deps.mark_feature_status(runtime.feature_id, FeatureStatus.ACCEPTED)
        accepted_feature = deps.update_record(
            "features",
            "features",
            "feature_id",
            runtime.feature_id,
            {
                "wave_progression": [dict(item) for item in state.wave_progression],
                "next_wave_id": "",
                "all_required_waves_accepted": True,
            },
        )
        final_status = deps.post_acceptance_final_status(
            feature_id=runtime.feature_id,
            accepted_feature=accepted_feature,
            summary=runtime.summary,
            packet_results=state.packet_results,
            verification_records=state.verification_records,
            review_routes=state.review_routes,
            wave_routes=state.wave_routes,
            commit_hash=runtime.commit_hash,
            wave_progression=state.wave_progression,
        )
        deps.notify_feature_event(
            feature_id=runtime.feature_id,
            title=str(state.seeded["feature"].get("title") or runtime.title),
            status=str(final_status["user_facing_status"]),
            summary=final_status["user_summary"],
            next_action=str(final_status["next_action"]),
        )
        deps.publish_feature_artifacts_task(
            state.seeded["feature"],
            state.packet_results,
            _last_verification(state),
            _last_review(state),
            _last_wave(state),
            final_status,
        )
        result = pipeline_return(state, final_status)
        result["verification"] = _last_verification(state)
        result["review_route"] = _last_review(state)
        result["wave_route"] = _last_wave(state)
        return result


def _incomplete_required_waves(runtime: PipelineRuntime, deps: PipelineDeps, state: PipelineState) -> dict:
    next_wave_id = deps.next_required_wave_id(state.wave_progression)
    reasons = (
        [f"Feature cannot be accepted until required wave {next_wave_id} is accepted."]
        if next_wave_id
        else ["Feature cannot be accepted because not all required waves are accepted."]
    )
    final_status = deps.final_failure(
        feature_id=runtime.feature_id,
        category="pipeline_invalid",
        next_action=f"incomplete-required-waves:{next_wave_id or 'unknown'}",
        reasons=reasons,
    )
    deps.publish_feature_artifacts_task(
        state.seeded["feature"],
        state.packet_results,
        _last_verification(state),
        _last_review(state),
        _last_wave(state),
        final_status,
    )
    return pipeline_return(state, final_status)
