# ############################################################################
# AI_HEADER: pipeline_phases.wave_execution_phase
# ROLE: Wave queue execution runner for feature_pipeline.
# ############################################################################

# START_MODULE_CONTRACT
# purpose: Execute validated feature waves, retry dependency-blocked packets, dispatch role handlers, and enforce wave gates.
# inputs: Pipeline runtime, mutable planning state, and facade-bound dependencies.
# returns: Optional final result dictionary for execution-time blocking branches.
# side_effects: Delegates to Prefect tasks and role handlers that run packets, update state, and publish artifacts.
# emitted_logs: Delegated Prefect task logs.
# error_behavior: Preserves dependency deadlock, packet failure, and missing wave gate envelopes.
# END_MODULE_CONTRACT

# START_MODULE_MAP
# mapping:
#   - function: run_wave_execution_phase
# END_MODULE_MAP

from __future__ import annotations

from prefect import get_run_logger
from prefect_grace.flows.pipeline_phases.context import (
    PipelineDeps,
    PipelineRuntime,
    PipelineState,
    pipeline_return,
)
from prefect_grace.flows.pipeline_phases.wave_role_handlers import (
    handle_architect_packet,
    handle_coder_packet,
    handle_reviewer_packet,
    handle_verifier_packet,
)


def _last_verification(state: PipelineState) -> dict[str, object] | None:
    """Get the most recent verification record from pipeline state.

    Args:
        state: Pipeline state containing verification records

    Returns:
        Last verification record or None if no records exist
    """
    return state.verification_records[-1] if state.verification_records else None


def _last_review(state: PipelineState) -> dict[str, object] | None:
    """Get the most recent review route from pipeline state.

    Args:
        state: Pipeline state containing review routes

    Returns:
        Last review route or None if no routes exist
    """
    return state.review_routes[-1] if state.review_routes else None


def _last_wave(state: PipelineState) -> dict[str, object] | None:
    """Get the most recent wave route from pipeline state.

    Args:
        state: Pipeline state containing wave routes

    Returns:
        Last wave route or None if no routes exist
    """
    return state.wave_routes[-1] if state.wave_routes else None


# START_FUNCTION_CONTRACT
# name: run_wave_execution_phase
# purpose: Execute wave queues and dispatch each packet role to bounded handlers.
# inputs:
#   runtime: Feature pipeline parameters.
#   deps: Facade-bound task and helper dependencies.
#   state: Planning phase state to mutate.
# returns: Optional final result dictionary when execution cannot continue.
# side_effects: Runs packet tasks, mutates wave queues, updates progression, and publishes artifacts through handlers.
# emitted_logs: Delegated Prefect task logs.
# error_behavior: Returns existing final envelopes for deadlocks, packet failures, and missing architect gates.
# END_FUNCTION_CONTRACT
def run_wave_execution_phase(runtime: PipelineRuntime, deps: PipelineDeps, state: PipelineState) -> dict[str, object] | None:
    from datetime import datetime, timezone
    logger = get_run_logger()

    with deps.tags(f"feature:{runtime.feature_id}", "flow:feature-pipeline"):
        _initialize_wave_execution_state(state)
        for wave_entry in state.wave_progression:
            wave_id = str(wave_entry.get("wave_id") or "")
            wave_packets = list(state.wave_packets_by_id.get(wave_id) or [])
            if not wave_packets:
                continue

            logger.info("WAVE_START", extra={
                "wave_id": wave_id,
                "feature_id": runtime.feature_id,
                "packet_count": len(wave_packets),
                "timestamp": datetime.now(timezone.utc).isoformat()
            })

            deps.set_wave_progression_status(
                feature_id=runtime.feature_id,
                wave_progression=state.wave_progression,
                wave_id=wave_id,
                status="running",
            )
            state.packet_results["wave_progression"] = [dict(item) for item in state.wave_progression]
            result = _run_single_wave(runtime, deps, state, wave_id, wave_packets)

            logger.info("WAVE_END", extra={
                "wave_id": wave_id,
                "feature_id": runtime.feature_id,
                "result_type": "blocked" if result is not None else "completed",
                "timestamp": datetime.now(timezone.utc).isoformat()
            })

            if result is not None:
                return result
        return None


def _initialize_wave_execution_state(state: PipelineState) -> None:
    """Initialize wave execution state before processing wave queues.

    Args:
        state: Pipeline state to initialize for wave execution
    """
    state.verification_records = []
    state.review_routes = []
    state.wave_routes = []
    state.wave_packet_sets = {
        wave_id: {str(packet["packet_id"]) for packet in packets}
        for wave_id, packets in state.wave_packets_by_id.items()
    }
    state.completed_packet_ids = {state.architect_packet_id}
    if state.planner_required and state.planner_packet_id:
        state.completed_packet_ids.add(state.planner_packet_id)
    state.reviewer_decision_index = 0
    state.wave_decision_index = 0


def _run_single_wave(
    runtime: PipelineRuntime,
    deps: PipelineDeps,
    state: PipelineState,
    wave_id: str,
    wave_packets: list[dict[str, object]],
) -> dict[str, object] | None:
    """Execute a single wave's packet queue with dependency resolution.

    Args:
        runtime: Pipeline runtime configuration
        deps: Pipeline dependencies facade
        state: Mutable pipeline state
        wave_id: Wave identifier to execute
        wave_packets: List of packets in this wave

    Returns:
        Final result dictionary if wave is blocked, None if completed successfully
    """
    from datetime import datetime, timezone
    logger = get_run_logger()

    ordered_packets = deps.order_packets_for_wave(wave_packets)
    queue_packets = list(ordered_packets)
    queue_ids = {str(packet["packet_id"]) for packet in queue_packets}
    state.review_route = None
    wave_route_seen = False
    idle_steps = 0

    logger.info("WAVE_QUEUE_INITIALIZED", extra={
        "wave_id": wave_id,
        "feature_id": runtime.feature_id,
        "queue_size": len(queue_packets),
        "packet_ids": list(queue_ids),
        "timestamp": datetime.now(timezone.utc).isoformat()
    })

    while queue_packets:
        packet = queue_packets.pop(0)
        packet_id = str(packet["packet_id"])
        role = str(packet.get("role") or "")
        queue_ids.discard(packet_id)

        logger.info("PACKET_START", extra={
            "packet_id": packet_id,
            "wave_id": wave_id,
            "role": role,
            "feature_id": runtime.feature_id,
            "remaining_queue": len(queue_packets),
            "timestamp": datetime.now(timezone.utc).isoformat()
        })

        dependency_result = _handle_missing_dependencies(
            runtime,
            deps,
            state,
            packet,
            packet_id,
            queue_packets,
            queue_ids,
            idle_steps,
        )
        if isinstance(dependency_result, dict):
            return dependency_result
        if dependency_result == "retry":
            idle_steps += 1
            logger.info("PACKET_RETRY", extra={
                "packet_id": packet_id,
                "wave_id": wave_id,
                "idle_steps": idle_steps,
                "timestamp": datetime.now(timezone.utc).isoformat()
            })
            continue
        idle_steps = 0

        packet_run = None
        if role in {"coder", "planner", "architect", "reviewer"}:
            packet_run = _run_role_packet(runtime, deps, state, packet_id, role, wave_id)
            if isinstance(packet_run, dict) and packet_run.get("final_result"):
                return packet_run["final_result"]
            packet_run = packet_run or {}

        result = _dispatch_role(
            runtime,
            deps,
            state,
            packet,
            packet_id,
            role,
            wave_id,
            wave_packets,
            packet_run,
            queue_packets,
            queue_ids,
        )

        logger.info("PACKET_END", extra={
            "packet_id": packet_id,
            "wave_id": wave_id,
            "role": role,
            "feature_id": runtime.feature_id,
            "result_type": "blocked" if result is not None else "completed",
            "timestamp": datetime.now(timezone.utc).isoformat()
        })

        if result is not None:
            return result
        if role == "architect":
            wave_route_seen = True

    if wave_route_seen:
        return None
    return _missing_wave_gate(runtime, deps, state, wave_id)


def _handle_missing_dependencies(
    runtime: PipelineRuntime,
    deps: PipelineDeps,
    state: PipelineState,
    packet: dict[str, object],
    packet_id: str,
    queue_packets: list[dict[str, object]],
    queue_ids: set[str],
    idle_steps: int,
) -> dict[str, object] | str | None:
    """Handle packets with missing dependencies by retrying or failing.

    Args:
        runtime: Pipeline runtime configuration
        deps: Pipeline dependencies facade
        state: Mutable pipeline state
        packet: Current packet being processed
        packet_id: Packet identifier
        queue_packets: Remaining packet queue
        queue_ids: Set of packet IDs in queue
        idle_steps: Number of consecutive retry steps

    Returns:
        Final result dict if deadlock detected, "retry" string to retry, None if no missing deps
    """
    missing_dependencies = deps.missing_internal_dependencies(
        packet,
        known_packet_ids=set(state.packets_by_id),
        completed_packet_ids=state.completed_packet_ids,
    )
    if not missing_dependencies:
        return None
    deps.append_unique_packet(queue_packets, packet)
    queue_ids.add(packet_id)
    if idle_steps + 1 <= max(len(queue_packets), 1) + 1:
        return "retry"

    final_status = deps.final_failure(
        feature_id=runtime.feature_id,
        category="pipeline_invalid",
        next_action=f"dependency-deadlock:{packet_id}",
        reasons=list(missing_dependencies),
    )
    state.packet_results[deps.packet_result_key("dependency_error", packet_id)] = {
        "packet_id": packet_id,
        "missing_dependencies": missing_dependencies,
    }
    deps.publish_feature_artifacts_task(
        state.seeded["feature"],
        state.packet_results,
        _last_verification(state),
        _last_review(state),
        _last_wave(state),
        final_status,
    )
    return pipeline_return(state, final_status)


def _run_role_packet(
    runtime: PipelineRuntime,
    deps: PipelineDeps,
    state: PipelineState,
    packet_id: str,
    role: str,
    wave_id: str,
) -> dict[str, object]:
    """Execute a packet and handle execution failures.

    Args:
        runtime: Pipeline runtime configuration
        deps: Pipeline dependencies facade
        state: Mutable pipeline state
        packet_id: Packet identifier to execute
        role: Packet role
        wave_id: Wave identifier

    Returns:
        Packet run result, or dict with final_result key if execution failed
    """
    with deps.tags(f"wave:{wave_id}", f"role:{role}"):
        packet_run = deps.run_packet_task(packet_id, runtime.dry_run, runtime.timeout_seconds)
    state.packet_results[deps.packet_result_key("run", packet_id)] = packet_run
    if packet_run.get("returncode") == 0:
        return packet_run
    final_status = deps.final_failure(
        feature_id=runtime.feature_id,
        category="environment_blocked",
        next_action=f"inspect-failed-packet:{packet_id}",
    )
    deps.publish_feature_artifacts_task(
        state.seeded["feature"],
        state.packet_results,
        _last_verification(state),
        _last_review(state),
        _last_wave(state),
        final_status,
    )
    return {"final_result": pipeline_return(state, final_status)}


def _dispatch_role(
    runtime: PipelineRuntime,
    deps: PipelineDeps,
    state: PipelineState,
    packet: dict[str, object],
    packet_id: str,
    role: str,
    wave_id: str,
    wave_packets: list[dict[str, object]],
    packet_run: dict[str, object],
    queue_packets: list[dict[str, object]],
    queue_ids: set[str],
) -> dict[str, object] | None:
    """Dispatch packet to appropriate role handler.

    Args:
        runtime: Pipeline runtime configuration
        deps: Pipeline dependencies facade
        state: Mutable pipeline state
        packet: Current packet
        packet_id: Packet identifier
        role: Packet role (coder, verifier, reviewer, architect)
        wave_id: Wave identifier
        wave_packets: All packets in current wave
        packet_run: Packet execution result
        queue_packets: Remaining packet queue
        queue_ids: Set of packet IDs in queue

    Returns:
        Final result dict if role handler blocks, None if completed successfully
    """
    if role == "coder":
        handle_coder_packet(
            runtime,
            deps,
            state,
            packet=packet,
            packet_id=packet_id,
            wave_id=wave_id,
            wave_packets=wave_packets,
        )
        return None
    if role == "verifier":
        return handle_verifier_packet(runtime, deps, state, packet_id=packet_id, wave_id=wave_id, queue_packets=queue_packets, queue_ids=queue_ids)
    if role == "reviewer":
        return handle_reviewer_packet(
            runtime,
            deps,
            state,
            packet=packet,
            packet_id=packet_id,
            packet_run=packet_run,
            wave_id=wave_id,
            queue_packets=queue_packets,
            queue_ids=queue_ids,
        )
    if role == "architect":
        return handle_architect_packet(
            runtime,
            deps,
            state,
            packet_id=packet_id,
            packet_run=packet_run,
            wave_id=wave_id,
        )
    return None


def _missing_wave_gate(
    runtime: PipelineRuntime,
    deps: PipelineDeps,
    state: PipelineState,
    wave_id: str,
) -> dict[str, object]:
    """Handle missing architect wave gate for a wave.

    Args:
        runtime: Pipeline runtime configuration
        deps: Pipeline dependencies facade
        state: Mutable pipeline state
        wave_id: Wave identifier missing gate

    Returns:
        Final failure result dictionary
    """
    deps.set_wave_progression_status(
        feature_id=runtime.feature_id,
        wave_progression=state.wave_progression,
        wave_id=wave_id,
        status="blocked",
        reasons=[f"Missing architect wave gate for {wave_id}"],
    )
    state.packet_results["wave_progression"] = [dict(item) for item in state.wave_progression]
    final_status = deps.final_failure(
        feature_id=runtime.feature_id,
        category="pipeline_invalid",
        next_action=f"missing-architect-wave-gate:{wave_id}",
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
