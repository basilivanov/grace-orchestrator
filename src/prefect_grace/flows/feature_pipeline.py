# ############################################################################
# AI_HEADER: feature_pipeline
# ROLE: Facade flow for GRACE feature orchestration with extracted helpers and tasks.
# ############################################################################

# START_MODULE_CONTRACT
# purpose: Expose the GRACE feature pipeline and review router flows while preserving compatibility imports.
# inputs: Feature metadata, packet execution options, verifier/reviewer fallbacks, planner contracts, and review router values.
# returns: Feature pipeline result dictionaries and review router result dictionaries.
# side_effects: Delegates to extracted Prefect tasks that update state, write artifacts, notify, and optionally launch agents.
# emitted_logs: Prefect flow and task logs.
# error_behavior: Preserves existing fail-closed status/result behavior for pipeline validation and task failures.
# END_MODULE_CONTRACT

# START_MODULE_MAP
# mapping:
#   - flow: feature_pipeline
#   - flow: review_router_flow
# END_MODULE_MAP

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from prefect_grace.models import (
    FeatureStatus,
    FrontendVisualVerdict,
    ObservabilityVerdict,
    PacketStatus,
    ReasoningProfile,
    ReviewVerdict,
    TestVerdict,
    WaveVerdict,
)
from prefect_grace.prefect_compat import flow, get_run_logger, tags
from prefect_grace.flows.pipeline_tasks.architect_tasks import (
    resolve_architect_artifact_plan_task,
    write_architect_artifacts_task,
)
from prefect_grace.flows.pipeline_tasks.artifact_tasks import (
    publish_feature_artifacts_task,
    publish_packet_review_artifacts_task,
    record_verifier_result_task,
    resolve_verifier_result_task,
)
from prefect_grace.flows.pipeline_tasks.bootstrap_tasks import (
    bootstrap_task,
    seed_feature_packets_task,
)
from prefect_grace.flows.pipeline_tasks.canon_tasks import record_canon_digest_task
from prefect_grace.flows.pipeline_tasks.execution_tasks import (
    mark_feature_in_progress_task,
    mark_packet_status_task,
    run_packet_task,
    run_verifier_packet_task,
)
from prefect_grace.flows.pipeline_tasks.planner_tasks import (
    architect_packet_candidates_to_contract as _architect_packet_candidates_to_contract,
    architect_plan_next_action as _architect_plan_next_action,
    architect_wave_contract as _architect_wave_contract,
    load_architect_manifest as _load_architect_manifest,
    materialize_planner_contract_task,
    resolve_planner_contract_task,
    should_run_planner as _should_run_planner,
    validate_planner_contract_task,
)
from prefect_grace.flows.pipeline_tasks.review_tasks import (
    resolve_reviewer_decision_task,
    review_task,
    route_reviewer_verdict_task,
)
from prefect_grace.flows.pipeline_tasks.wave_tasks import (
    resolve_wave_decision_task,
    route_architect_wave_verdict_task,
)
from prefect_grace.flows.pipeline_phases.bootstrap_phase import run_bootstrap_phase
from prefect_grace.flows.pipeline_phases.context import PipelineDeps, PipelineRuntime
from prefect_grace.flows.pipeline_phases.finalization_phase import run_finalization_phase
from prefect_grace.flows.pipeline_phases.planning_phase import run_planning_phase
from prefect_grace.flows.pipeline_phases.wave_execution_phase import run_wave_execution_phase
from prefect_grace.flows.pipeline_helpers.evidence_collector import (
    append_evidence_path as _append_evidence_path,
    artifact_glob_matches as _artifact_glob_matches,
    candidate_file_path as _candidate_file_path,
    collect_candidate_commit_files as _collect_candidate_commit_files,
    collect_candidate_commit_files_from_payload as _collect_candidate_commit_files_from_payload,
    collect_verifier_supplemental_evidence as _collect_verifier_supplemental_evidence,
    enrich_verifier_evidence_paths as _enrich_verifier_evidence_paths,
    existing_file_path as _existing_file_path,
    feature_line_records as _feature_line_records,
    find_commit_marker as _find_commit_marker,
    normalize_commit_marker as _normalize_commit_marker,
    normalize_evidence_path as _normalize_evidence_path,
    path_candidates_from_text as _path_candidates_from_text,
    verifier_packet_for_run as _verifier_packet_for_run,
)
from prefect_grace.flows.pipeline_helpers.normalizers import (
    normalize_observability_scope as _normalize_observability_scope,
)
from prefect_grace.flows.pipeline_helpers.rework_routing import (
    REWORK_MODE_BOUNDED_FRESH,
    REWORK_MODE_DECISION_REQUIRED,
    REWORK_MODE_LIGHT_RESUME,
    REWORK_ROUTE_REQUIRES_PLANNER,
    REWORK_ROUTE_REQUIRES_USER_DECISION,
    REWORK_ROUTE_SELF_RESOLVABLE,
    REWORK_ROUTING_ARCHITECT_FIRST,
    REWORK_ROUTING_AUTO_BUNDLE,
    classify_rework_mode as _classify_rework_mode,
    classify_rework_route as _classify_rework_route,
    classify_rework_route_from_reasons as _classify_rework_route_from_reasons,
    escalate_repeated_observability_rework_for_pipeline as _escalate_repeated_observability_rework_for_pipeline,
    normalize_reviewer_decision_for_pipeline as _normalize_reviewer_decision_for_pipeline,
    normalize_rework_mode as _normalize_rework_mode,
    normalize_rework_route_classification as _normalize_rework_route_classification,
    packet_execution_contract as _packet_execution_contract,
    string_command_list as _string_command_list,
    uses_today_week_observability as _uses_today_week_observability,
)
from prefect_grace.flows.pipeline_helpers.status_formatter import (
    failure_status_for_category as _failure_status_for_category,
    final_user_summary as _final_user_summary,
    short_reason as _short_reason,
    status_label_ru as _status_label_ru,
)
from prefect_grace.flows.pipeline_helpers.wave_progression import (
    all_required_waves_accepted as _all_required_waves_accepted,
    architect_wave_gate_packet_id_for_wave as _architect_wave_gate_packet_id_for_wave,
    build_wave_progression as _build_wave_progression,
    is_execution_wave_id as _is_execution_wave_id,
    next_required_wave_id as _next_required_wave_id,
    normalize_wave_progression_entry as _normalize_wave_progression_entry,
    plan_wave_sequence as _plan_wave_sequence,
    required_wave_progression_issues as _required_wave_progression_issues,
    wave_id_from_issue as _wave_id_from_issue,
    wave_packets_by_wave_id as _wave_packets_by_wave_id,
    wave_required as _wave_required,
)
from prefect_grace.tasks.agent_output_parser import (
    parse_architect_artifact_plan_message,
    parse_direct_rework_packet_message,
    parse_planner_wave_plan_message,
    read_agent_message,
    resolve_reviewer_decision,
    resolve_verifier_result,
    resolve_wave_decision,
)
from prefect_grace.tasks.architect_artifacts import default_architect_artifact_plan, write_architect_artifacts
from prefect_grace.tasks.codex_launcher import launch_codex_for_packet
from prefect_grace.tasks.feature_bootstrap import bootstrap_feature, create_packet, mark_feature_status, seed_test_feature, sync_packet_file, STATE_ROOT
from prefect_grace.tasks.planner_contract import (
    default_wave_plan_contract,
    find_architect_wave_gate_packet_id,
    find_first_packet_id,
    materialize_planner_contract,
    normalize_wave_plan_contract,
)
from prefect_grace.tasks.prefect_artifacts import publish_feature_artifacts, publish_packet_task_artifacts
from prefect_grace.tasks.review_router import (
    create_architect_decision_from_review,
    create_architect_rework_packet_from_review,
    create_direct_rework_from_architect,
    create_rework_bundle_from_review,
    create_rework_from_review,
    record_review,
    record_wave_review,
)
from prefect_grace.tasks.state_store import find_record, load_state, update_record
from prefect_grace.tasks.telegram_notify import notify_feature_event, notify_packet_event
from prefect_grace.tasks.verification_router import record_verification
from prefect_grace.tasks.wave_executor import (
    append_unique_packet,
    missing_internal_dependencies,
    order_packets_for_wave,
    packet_has_downstream_reviewer,
    packet_map,
    packet_result_key,
    reviewer_target_packet_id,
)
def _final_failure(
    *,
    feature_id: str,
    category: str,
    next_action: str,
    reasons: list[str] | None = None,
    next_wave_id: str | None = None,
) -> dict[str, Any]:
    feature = mark_feature_status(
        feature_id,
        _failure_status_for_category(category),
        blocker_reasons=list(reasons or []),
        state_root=STATE_ROOT,
    )
    failure_updates: dict[str, object] = {}
    if next_wave_id is not None:
        failure_updates["next_wave_id"] = str(next_wave_id)
    if failure_updates:
        feature = update_record("features", "features", "feature_id", feature_id, failure_updates, state_root=STATE_ROOT)
    return {
        "feature": feature,
        "has_failures": True,
        "final_outcome": "blocked",
        "user_facing_status": str(feature.get("status") or _failure_status_for_category(category).value),
        "user_summary": _final_user_summary(
            outcome="blocked",
            status=str(feature.get("status") or _failure_status_for_category(category).value),
            summary=str(feature.get("summary") or ""),
            next_action=next_action,
            reasons=list(reasons or []),
        ),
        "next_action": next_action,
        "failure_category": category,
        "reasons": list(reasons or []),
        "wave_progression": [dict(item) for item in list(feature.get("wave_progression") or [])],
        "next_wave_id": str(feature.get("next_wave_id") or ""),
        "all_required_waves_accepted": bool(feature.get("all_required_waves_accepted")),
    }


POST_ACCEPTANCE_NEXT_ACTION = "commit-feature-changes"


def _post_acceptance_final_status(
    *,
    feature_id: str,
    accepted_feature: dict[str, Any],
    summary: str,
    packet_results: dict[str, Any],
    verification_records: list[dict[str, Any]],
    review_routes: list[dict[str, Any]],
    wave_routes: list[dict[str, Any]],
    commit_hash: str | None,
    wave_progression: list[dict[str, object]] | None = None,
) -> dict[str, Any]:
    detected_commit = _normalize_commit_marker(commit_hash) or _find_commit_marker(accepted_feature) or _find_commit_marker(packet_results)
    candidate_commit_files = _collect_candidate_commit_files(
        feature_id=feature_id,
        feature=accepted_feature,
        packet_results=packet_results,
        verification_records=verification_records,
        review_routes=review_routes,
        wave_routes=wave_routes,
    )
    if detected_commit:
        resolved_wave_progression = [dict(item) for item in wave_progression or accepted_feature.get("wave_progression") or []]
        feature_updates = {
            "commit_status": "committed",
            "commit_hash": detected_commit,
            "candidate_commit_files": candidate_commit_files,
            "wave_progression": resolved_wave_progression,
            "next_wave_id": "",
            "all_required_waves_accepted": True,
        }
        committed_feature = update_record("features", "features", "feature_id", feature_id, feature_updates, state_root=STATE_ROOT)
        return {
            "feature": committed_feature,
            "has_failures": False,
            "final_outcome": "accepted",
            "user_facing_status": FeatureStatus.ACCEPTED.value,
            "user_summary": _final_user_summary(
                outcome="accepted",
                status=FeatureStatus.ACCEPTED.value,
                summary=str(committed_feature.get("summary") or summary),
                next_action="feature-complete",
                reasons=[],
            ),
            "next_action": "feature-complete",
            "commit_status": "committed",
            "commit_hash": detected_commit,
            "candidate_commit_files": candidate_commit_files,
            "wave_progression": resolved_wave_progression,
            "next_wave_id": "",
            "all_required_waves_accepted": True,
            "reasons": [],
        }

    awaiting_feature = mark_feature_status(feature_id, FeatureStatus.AWAITING_COMMIT, state_root=STATE_ROOT)
    resolved_wave_progression = [dict(item) for item in wave_progression or awaiting_feature.get("wave_progression") or []]
    awaiting_feature = update_record(
        "features",
        "features",
        "feature_id",
        feature_id,
        {
            "commit_status": "awaiting_commit",
            "candidate_commit_files": candidate_commit_files,
            "wave_progression": resolved_wave_progression,
            "next_wave_id": "",
            "all_required_waves_accepted": True,
        },
        state_root=STATE_ROOT,
    )
    return {
        "feature": awaiting_feature,
        "has_failures": False,
        "final_outcome": "awaiting_commit",
        "user_facing_status": FeatureStatus.AWAITING_COMMIT.value,
        "user_summary": _final_user_summary(
            outcome="awaiting_commit",
            status=FeatureStatus.AWAITING_COMMIT.value,
            summary=str(awaiting_feature.get("summary") or summary),
            next_action=POST_ACCEPTANCE_NEXT_ACTION,
            reasons=[],
        ),
        "next_action": POST_ACCEPTANCE_NEXT_ACTION,
        "commit_status": "awaiting_commit",
        "commit_hash": "",
        "candidate_commit_files": candidate_commit_files,
        "wave_progression": resolved_wave_progression,
        "next_wave_id": "",
        "all_required_waves_accepted": True,
        "reasons": [],
    }


def _load_architect_manifest(feature_id: str) -> dict[str, Any]:
    from datetime import datetime, timezone
    logger = get_run_logger()
    try:
        feature = find_record("features", "features", "feature_id", feature_id, state_root=STATE_ROOT)
    except KeyError as e:
        logger.error("MANIFEST_KEY_ERROR", extra={
            "error": str(e),
            "feature_id": feature_id,
            "expected_key": "features",
            "timestamp": datetime.now(timezone.utc).isoformat()
        })
        return {}
    manifest_path = str(feature.get("architect_manifest_path") or "").strip()
    if not manifest_path:
        logger.warning("MANIFEST_PATH_MISSING", extra={
            "feature_id": feature_id,
            "feature_keys": list(feature.keys()),
            "timestamp": datetime.now(timezone.utc).isoformat()
        })
        return {}
    path = Path(manifest_path)
    if not path.exists():
        logger.warning("MANIFEST_FILE_NOT_FOUND", extra={
            "feature_id": feature_id,
            "manifest_path": manifest_path,
            "timestamp": datetime.now(timezone.utc).isoformat()
        })
        return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as e:
        logger.error("MANIFEST_LOAD_ERROR", extra={
            "error": str(e),
            "error_type": type(e).__name__,
            "feature_id": feature_id,
            "manifest_path": manifest_path,
            "timestamp": datetime.now(timezone.utc).isoformat()
        })
        return
    return payload if isinstance(payload, dict) else {}


def _architect_wave_contract(architect_manifest: dict[str, Any], wave_id: str) -> dict[str, Any]:
    target_wave_id = str(wave_id or "").strip().upper()
    for wave in architect_manifest.get("waves") or []:
        if not isinstance(wave, dict):
            continue
        if str(wave.get("wave_id") or "").strip().upper() == target_wave_id:
            return dict(wave)
    return {}


def _persist_wave_progression(feature_id: str, wave_progression: list[dict[str, object]]) -> dict[str, Any]:
    return update_record(
        "features",
        "features",
        "feature_id",
        feature_id,
        {
            "wave_progression": [dict(item) for item in wave_progression],
            "next_wave_id": _next_required_wave_id(wave_progression),
            "all_required_waves_accepted": _all_required_waves_accepted(wave_progression),
        },
        state_root=STATE_ROOT,
    )


def _set_wave_progression_status(
    *,
    feature_id: str,
    wave_progression: list[dict[str, object]],
    wave_id: str,
    status: str,
    reasons: list[str] | None = None,
) -> dict[str, object]:
    updated_wave: dict[str, object] | None = None
    for item in wave_progression:
        if str(item.get("wave_id") or "") != str(wave_id):
            continue
        item["status"] = status
        if reasons is not None:
            item["reasons"] = [str(reason).strip() for reason in reasons if str(reason).strip()]
        elif status in {"running", "accepted"}:
            item["reasons"] = []
        updated_wave = dict(item)
        break
    _persist_wave_progression(feature_id, wave_progression)
    return updated_wave or {}


def _build_direct_rework_followup_packets(
    *,
    source_reviewer_packet: dict[str, Any],
    direct_rework_packet: dict[str, Any],
    target_packet_id: str,
    packets_by_id: dict[str, dict[str, Any]],
) -> tuple[list[dict[str, Any]], str]:
    rework_packets = [direct_rework_packet]
    rework_reviewer_packet_id = ""
    verifier_source_packet_id = next(
        (
            dependency
            for dependency in source_reviewer_packet.get("dependencies") or []
            if str(packets_by_id.get(str(dependency), {}).get("role") or "") == "verifier"
        ),
        "",
    )
    origin_reviewer_packet_id = str(direct_rework_packet.get("origin_reviewer_packet_id") or source_reviewer_packet["packet_id"])
    verifier_source_packet = dict(packets_by_id.get(verifier_source_packet_id) or {})
    verifier_hints = dict(direct_rework_packet.get("execution_hints") or {})
    verifier_profile = {}
    if verifier_source_packet_id:
        verifier_hints = {**verifier_hints, **dict(verifier_source_packet.get("execution_hints") or {})}
        verifier_profile = dict(verifier_source_packet.get("verification_profile") or {})

    direct_verifier_packet = create_packet(
        feature_id=direct_rework_packet["feature_id"],
        wave_id=direct_rework_packet["wave_id"],
        title=f"Verifier Rework {direct_rework_packet['title']}",
        role="verifier",
        reasoning=ReasoningProfile.MEDIUM,
        summary=f"Validate the architect-bounded direct rework for `{target_packet_id}` and capture fresh evidence.",
        write_scope=["Verification notes and evidence references only."],
        inputs=[direct_rework_packet["packet_id"], origin_reviewer_packet_id],
        acceptance_criteria=[
            "Commands run are recorded for the direct rework packet.",
            "Evidence paths are refreshed for the reworked scope.",
            "Observability verdict is explicit for the direct rework.",
        ],
        verification_profile=verifier_profile
        or {
            "backend": "rerun minimally sufficient backend checks for the reworked scope",
            "frontend": "rerun targeted frontend checks if UI changed",
            "observability": "repeat post-test digest, trace, and replay review",
        },
        reviewer_gate=[
            "Evidence must correspond to the direct rework packet, not the original attempt.",
            "Missing visual proof remains a blocker for UI work.",
        ],
        dependencies=[direct_rework_packet["packet_id"]],
        packet_type="rework",
        notes=["This verifier packet was created for architect-bounded direct rework."],
        parent_packet_id=target_packet_id,
        execution_hints=verifier_hints,
        status=PacketStatus.READY,
    )
    direct_reviewer_packet = create_packet(
        feature_id=direct_rework_packet["feature_id"],
        wave_id=direct_rework_packet["wave_id"],
        title=f"Reviewer Rework {direct_rework_packet['title']}",
        role="reviewer",
        reasoning=ReasoningProfile.XHIGH,
        summary=f"Review whether the architect-bounded direct rework for `{target_packet_id}` addressed the reviewer blockers.",
        write_scope=["Review verdict and blocker notes only."],
        inputs=[direct_rework_packet["packet_id"], direct_verifier_packet["packet_id"]],
        acceptance_criteria=[
            "Exactly one verdict is returned.",
            "The original blockers are either resolved or explicitly remain.",
            "No unrelated scope expansion is accepted.",
        ],
        verification_profile={
            "backend": "consume verifier evidence",
            "frontend": "consume verifier evidence",
            "observability": "consume verifier evidence",
        },
        reviewer_gate=[
            "Assess only the original blocker scope.",
            "Escalate only if blockers imply decomposition or business changes.",
        ],
        dependencies=[direct_rework_packet["packet_id"], direct_verifier_packet["packet_id"]],
        packet_type="gate_decision",
        notes=["This reviewer packet was created for architect-bounded direct rework."],
        parent_packet_id=target_packet_id,
        status=PacketStatus.READY,
    )
    direct_reviewer_packet = update_record(
        "packets",
        "packets",
        "packet_id",
        direct_reviewer_packet["packet_id"],
        {
            "review_target_packet_id": direct_rework_packet["packet_id"],
            "execution_hints": dict(direct_rework_packet.get("execution_hints") or {}),
        },
        state_root=STATE_ROOT,
    )
    direct_reviewer_packet = sync_packet_file(direct_reviewer_packet)
    rework_packets.extend([direct_verifier_packet, direct_reviewer_packet])
    rework_reviewer_packet_id = str(direct_reviewer_packet.get("packet_id") or "")
    return rework_packets, rework_reviewer_packet_id


def _should_run_planner(*, run_planner: bool | None, planner_contract: dict[str, Any] | None) -> bool:
    if run_planner is not None:
        return bool(run_planner)
    return False


def _architect_plan_next_action(payload: dict[str, Any] | None) -> str:
    action = str((payload or {}).get("next_action") or "materialize_packets").strip().lower().replace("-", "_")
    if action in {"materialize_packets", "requires_planner", "requires_user_decision"}:
        return action
    return "materialize_packets"


def _architect_packet_candidates_to_contract(payload: dict[str, Any] | None) -> dict[str, Any] | None:
    from datetime import datetime, timezone
    logger = get_run_logger()
    if not isinstance(payload, dict):
        logger.warning("ARCHITECT_CONTRACT_INVALID_PAYLOAD", extra={
            "payload_type": type(payload).__name__,
            "timestamp": datetime.now(timezone.utc).isoformat()
        })
        return None
    raw_packets = payload.get("packet_candidates")
    if not isinstance(raw_packets, list) or not raw_packets:
        logger.warning("ARCHITECT_CONTRACT_NO_PACKETS", extra={
            "has_packet_candidates": "packet_candidates" in payload,
            "packet_candidates_type": type(raw_packets).__name__ if raw_packets is not None else "None",
            "timestamp": datetime.now(timezone.utc).isoformat()
        })
        return None
    packets = [dict(packet) for packet in raw_packets if isinstance(packet, dict)]
    if not packets:
        logger.warning("ARCHITECT_CONTRACT_NO_VALID_PACKETS", extra={
            "raw_packet_count": len(raw_packets),
            "timestamp": datetime.now(timezone.utc).isoformat()
        })
        return None
    raw_waves = payload.get("waves")
    waves = [dict(wave) for wave in raw_waves if isinstance(wave, dict)] if isinstance(raw_waves, list) else []
    logger.info("ARCHITECT_CONTRACT_PARSED", extra={
        "packet_count": len(packets),
        "wave_count": len(waves),
        "timestamp": datetime.now(timezone.utc).isoformat()
    })
    return {"waves": waves, "packets": packets}


def _sync_architect_manifest_packets(
    *,
    feature_id: str,
    generated_packets: list[dict[str, Any]],
    architect_packet_id: str,
) -> None:
    from datetime import datetime, timezone
    logger = get_run_logger()
    try:
        feature = find_record("features", "features", "feature_id", feature_id, state_root=STATE_ROOT)
    except KeyError as e:
        logger.error("MANIFEST_SYNC_FEATURE_NOT_FOUND", extra={
            "error": str(e),
            "feature_id": feature_id,
            "timestamp": datetime.now(timezone.utc).isoformat()
        })
        return
    manifest_path = Path(str(feature.get("architect_manifest_path") or "").strip())
    if not manifest_path.is_file():
        logger.warning("MANIFEST_SYNC_FILE_NOT_FOUND", extra={
            "feature_id": feature_id,
            "manifest_path": str(manifest_path),
            "timestamp": datetime.now(timezone.utc).isoformat()
        })
        return
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as e:
        logger.error("MANIFEST_SYNC_LOAD_ERROR", extra={
            "error": str(e),
            "error_type": type(e).__name__,
            "feature_id": feature_id,
            "manifest_path": str(manifest_path),
            "timestamp": datetime.now(timezone.utc).isoformat()
        })
        return
    if not isinstance(manifest, dict):
        logger.error("MANIFEST_SYNC_INVALID_TYPE", extra={
            "feature_id": feature_id,
            "manifest_type": type(manifest).__name__,
            "manifest_path": str(manifest_path),
            "timestamp": datetime.now(timezone.utc).isoformat()
        })
        return
    manifest["packet_candidates"] = [
        {
            "key": str(packet.get("packet_id") or ""),
            "wave_id": str(packet.get("wave_id") or ""),
            "title": str(packet.get("title") or ""),
            "role": str(packet.get("role") or ""),
            "reasoning": str(packet.get("reasoning") or ""),
            "packet_type": str(packet.get("packet_type") or ""),
            "summary": str(packet.get("summary") or ""),
            "write_scope": list(packet.get("write_scope") or []),
            "inputs": list(packet.get("inputs") or []),
            "acceptance_criteria": list(packet.get("acceptance_criteria") or []),
            "verification_profile": dict(packet.get("verification_profile") or {}),
            "reviewer_gate": list(packet.get("reviewer_gate") or []),
            "dependencies": [
                "architect formalization" if str(dependency) == architect_packet_id else str(dependency)
                for dependency in list(packet.get("dependencies") or [])
            ],
            "notes": list(packet.get("notes") or []),
            "review_target_key": str(packet.get("review_target_packet_id") or ""),
        }
        for packet in generated_packets
    ]
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")


def _architect_direct_rework_packet_spec_from_run(architect_run: dict[str, Any]) -> dict[str, Any] | None:
    try:
        return parse_direct_rework_packet_message(
            read_agent_message(architect_run.get("last_message_path"), architect_run.get("stdout_path"))
        )
    except ValueError:
        return None


def _build_architect_direct_rework(
    *,
    coder_packet_id: str,
    reviewer_packet_id: str,
    reasons: list[str],
    architect_run: dict[str, Any] | None,
    route_classification: str,
    rework_mode: str,
) -> dict[str, Any]:
    packet_spec = _architect_direct_rework_packet_spec_from_run(architect_run or {}) if architect_run else None
    if packet_spec and packet_spec.get("route_classification") != route_classification:
        raise ValueError("Architect direct rework packet classification does not match reviewer route")
    if route_classification != REWORK_ROUTE_SELF_RESOLVABLE:
        raise ValueError("Architect direct rework builder only supports self-resolvable routing")
    title = str(packet_spec.get("title") or "").strip() if packet_spec else ""
    summary = str(packet_spec.get("summary") or "").strip() if packet_spec else ""
    resolved_rework_mode = _normalize_rework_mode(packet_spec.get("rework_mode") if packet_spec else rework_mode)
    return create_direct_rework_from_architect(
        coder_packet_id,
        reasons,
        reviewer_packet_id=reviewer_packet_id,
        rework_mode=resolved_rework_mode,
        title=title or None,
        summary=summary or None,
        write_scope=list(packet_spec.get("write_scope") or []) or None if packet_spec else None,
        inputs=list(packet_spec.get("inputs") or []) or None if packet_spec else None,
        acceptance_criteria=list(packet_spec.get("acceptance_criteria") or []) or None if packet_spec else None,
        verification_profile=dict(packet_spec.get("verification_profile") or {}) or None if packet_spec else None,
        reviewer_gate=list(packet_spec.get("reviewer_gate") or []) or None if packet_spec else None,
        notes=list(packet_spec.get("notes") or []) or None if packet_spec else None,
    )


def _build_light_resume_followup(
    *,
    source_reviewer_packet: dict[str, Any],
    resumed_packet: dict[str, Any],
    reasons: list[str],
    reviewer_packet_id: str,
    packets_by_id: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    rework_packet = update_record(
        "packets",
        "packets",
        "packet_id",
        str(resumed_packet["packet_id"]),
        {
            "review_target_packet_id": str(resumed_packet["packet_id"]),
            "origin_reviewer_packet_id": str(reviewer_packet_id),
            "route_classification": REWORK_ROUTE_SELF_RESOLVABLE,
            "requested_rework_mode": REWORK_MODE_LIGHT_RESUME,
            "rework_mode": REWORK_MODE_LIGHT_RESUME,
            "status": PacketStatus.READY.value,
            "light_resume_stage": True,
            "light_resume_source_packet_id": str(resumed_packet["packet_id"]),
            "light_resume_attempt": int(resumed_packet.get("light_resume_attempt") or 0) + 1,
            "light_resume_max_attempts": 1,
        },
        state_root=STATE_ROOT,
    )
    rework_packet["execution_hints"] = {
        **dict(rework_packet.get("execution_hints") or {}),
        "resume_strategy": "packet_parent",
        "resume_parent_packet_id": str(resumed_packet["packet_id"]),
        "rework_mode": REWORK_MODE_LIGHT_RESUME,
        "light_resume_stage": True,
        "light_resume_scope": "packet_local",
        "light_resume_source_packet_id": str(resumed_packet["packet_id"]),
        "light_resume_attempt": rework_packet["light_resume_attempt"],
        "light_resume_max_attempts": 1,
        "light_resume_reviewer_packet_id": str(reviewer_packet_id),
        "light_resume_reasons": [str(reason).strip() for reason in reasons if str(reason).strip()],
    }
    rework_packet = update_record(
        "packets",
        "packets",
        "packet_id",
        str(resumed_packet["packet_id"]),
        {"execution_hints": rework_packet["execution_hints"]},
        state_root=STATE_ROOT,
    )
    rework_packets, rework_reviewer_packet_id = _build_direct_rework_followup_packets(
        source_reviewer_packet=source_reviewer_packet,
        direct_rework_packet=rework_packet,
        target_packet_id=str(resumed_packet["packet_id"]),
        packets_by_id=packets_by_id,
    )
    return {
        "packet_id": rework_packet["packet_id"],
        "rework": rework_packet,
        "packets": rework_packets,
        "reviewer_packet_id": rework_reviewer_packet_id,
        "rework_mode": REWORK_MODE_LIGHT_RESUME,
        "light_resume_stage": True,
    }


def _build_pipeline_deps() -> PipelineDeps:
    # Wrapper functions that use default STATE_ROOT from feature_bootstrap module
    def _update_record_wrapper(name: str, key: str, id_field: str, id_value: str, updates: dict) -> dict:
        from prefect_grace.tasks.feature_bootstrap import STATE_ROOT
        return update_record(name, key, id_field, id_value, updates, state_root=STATE_ROOT)

    def _mark_feature_status_wrapper(feature_id: str, status, *, blocker_reasons: list[str] | None = None) -> dict:
        from prefect_grace.tasks.feature_bootstrap import STATE_ROOT
        return mark_feature_status(feature_id, status, blocker_reasons=blocker_reasons, state_root=STATE_ROOT)

    return PipelineDeps(
        tags=tags,
        seed_feature_packets_task=seed_feature_packets_task,
        mark_feature_in_progress_task=mark_feature_in_progress_task,
        record_canon_digest_task=record_canon_digest_task,
        run_packet_task=run_packet_task,
        run_verifier_packet_task=run_verifier_packet_task,
        mark_packet_status_task=mark_packet_status_task,
        resolve_architect_artifact_plan_task=resolve_architect_artifact_plan_task,
        write_architect_artifacts_task=write_architect_artifacts_task,
        publish_feature_artifacts_task=publish_feature_artifacts_task,
        resolve_planner_contract_task=resolve_planner_contract_task,
        materialize_planner_contract_task=materialize_planner_contract_task,
        validate_planner_contract_task=validate_planner_contract_task,
        resolve_verifier_result_task=resolve_verifier_result_task,
        record_verifier_result_task=record_verifier_result_task,
        resolve_reviewer_decision_task=resolve_reviewer_decision_task,
        route_reviewer_verdict_task=route_reviewer_verdict_task,
        publish_packet_review_artifacts_task=publish_packet_review_artifacts_task,
        resolve_wave_decision_task=resolve_wave_decision_task,
        route_architect_wave_verdict_task=route_architect_wave_verdict_task,
        final_failure=_final_failure,
        post_acceptance_final_status=_post_acceptance_final_status,
        final_user_summary=_final_user_summary,
        should_run_planner=_should_run_planner,
        architect_plan_next_action=_architect_plan_next_action,
        architect_packet_candidates_to_contract=_architect_packet_candidates_to_contract,
        sync_architect_manifest_packets=_sync_architect_manifest_packets,
        load_architect_manifest=_load_architect_manifest,
        build_wave_progression=_build_wave_progression,
        persist_wave_progression=_persist_wave_progression,
        set_wave_progression_status=_set_wave_progression_status,
        required_wave_progression_issues=_required_wave_progression_issues,
        wave_id_from_issue=_wave_id_from_issue,
        next_required_wave_id=_next_required_wave_id,
        all_required_waves_accepted=_all_required_waves_accepted,
        wave_packets_by_wave_id=_wave_packets_by_wave_id,
        packet_map=packet_map,
        order_packets_for_wave=order_packets_for_wave,
        missing_internal_dependencies=missing_internal_dependencies,
        append_unique_packet=append_unique_packet,
        packet_result_key=packet_result_key,
        packet_has_downstream_reviewer=packet_has_downstream_reviewer,
        reviewer_target_packet_id=reviewer_target_packet_id,
        normalize_reviewer_decision_for_pipeline=_normalize_reviewer_decision_for_pipeline,
        escalate_repeated_observability_rework_for_pipeline=_escalate_repeated_observability_rework_for_pipeline,
        classify_rework_route=_classify_rework_route,
        classify_rework_mode=_classify_rework_mode,
        create_architect_rework_packet_from_review=create_architect_rework_packet_from_review,
        build_architect_direct_rework=_build_architect_direct_rework,
        build_light_resume_followup=_build_light_resume_followup,
        build_direct_rework_followup_packets=_build_direct_rework_followup_packets,
        update_record=_update_record_wrapper,
        mark_feature_status=_mark_feature_status_wrapper,
        notify_feature_event=notify_feature_event,
    )


# START_FUNCTION_CONTRACT
# name: feature_pipeline
# purpose: Run the GRACE feature orchestration pipeline across bootstrap, planning, execution, verification, review, wave gates, and final status.
# inputs: Feature identifiers, summaries, verifier settings, planner options, fallback decisions, dry-run flag, and agent execution options.
# returns: Feature pipeline result dictionary containing feature, seeded packets, runs, verification records, review routes, wave routes, and final status.
# side_effects: Calls extracted Prefect tasks that write state, artifacts, notifications, and optionally launch agents when dry_run is false.
# emitted_logs: Prefect flow and task logs.
# error_behavior: Returns structured blocked/failure final_status for expected pipeline validation and review failures; propagates unexpected task errors.
# END_FUNCTION_CONTRACT
@flow(name="prefect-grace-feature-pipeline", flow_run_name="feature:{feature_id}")
def feature_pipeline(
    feature_id: str,
    title: str,
    summary: str,
    implementation_title: str = "Test Implementation Packet",
    implementation_summary: str = "Run a bounded end-to-end test feature through architect, planner, coder, verifier, and reviewer packets.",
    dry_run: bool = True,
    timeout_seconds: int = 3600,
    verifier_backend_profile: str | None = "backend_quick",
    verifier_frontend_profile: str | None = None,
    verifier_frontend_commands: list[str] | None = None,
    verifier_observability_profile: str | None = None,
    verifier_observability_commands: list[str] | None = None,
    verifier_artifact_globs: list[str] | None = None,
    verifier_touches_frontend: bool = False,
    verifier_requires_frontend_visual: bool = False,
    verifier_include_day_live_canary: bool = False,
    agent_workdir: str | None = None,
    agent_sandbox: str | None = None,
    business_context: dict | None = None,
    planner_contract: dict | None = None,
    reviewer_verdict: str | None = ReviewVerdict.ACCEPTED.value,
    review_reasons: list[str] | None = None,
    verifier_test_verdict: str | None = TestVerdict.PASSED.value,
    verifier_observability_verdict: str | None = ObservabilityVerdict.CLEAN.value,
    verifier_frontend_visual_verdict: str | None = FrontendVisualVerdict.NOT_APPLICABLE.value,
    verifier_commands_run: list[str] | None = None,
    verifier_evidence_paths: list[str] | None = None,
    verifier_blocking_issues: list[str] | None = None,
    wave_verdict: str | None = WaveVerdict.ACCEPTED.value,
    wave_reasons: list[str] | None = None,
    create_rework: bool = True,
    prefer_agent_output: bool = False,
    run_architect: bool = True,
    run_planner: bool | None = None,
    commit_hash: str | None = None,
    rework_routing_policy: str = REWORK_ROUTING_ARCHITECT_FIRST,
    reviewer_verdict_script: list[str] | None = None,
    review_reasons_script: list[list[str]] | None = None,
    wave_verdict_script: list[str] | None = None,
    wave_reasons_script: list[list[str]] | None = None,
):
    from datetime import datetime, timezone
    logger = get_run_logger()

    logger.info("PHASE_START", extra={
        "phase": "bootstrap",
        "feature_id": feature_id,
        "timestamp": datetime.now(timezone.utc).isoformat()
    })

    runtime = PipelineRuntime(
        feature_id=feature_id,
        title=title,
        summary=summary,
        implementation_title=implementation_title,
        implementation_summary=implementation_summary,
        dry_run=dry_run,
        timeout_seconds=timeout_seconds,
        verifier_backend_profile=verifier_backend_profile,
        verifier_frontend_profile=verifier_frontend_profile,
        verifier_frontend_commands=verifier_frontend_commands,
        verifier_observability_profile=verifier_observability_profile,
        verifier_observability_commands=verifier_observability_commands,
        verifier_artifact_globs=verifier_artifact_globs,
        verifier_touches_frontend=verifier_touches_frontend,
        verifier_requires_frontend_visual=verifier_requires_frontend_visual,
        verifier_include_day_live_canary=verifier_include_day_live_canary,
        agent_workdir=agent_workdir,
        agent_sandbox=agent_sandbox,
        business_context=business_context,
        planner_contract=planner_contract,
        reviewer_verdict=reviewer_verdict,
        review_reasons=review_reasons,
        verifier_test_verdict=verifier_test_verdict,
        verifier_observability_verdict=verifier_observability_verdict,
        verifier_frontend_visual_verdict=verifier_frontend_visual_verdict,
        verifier_commands_run=verifier_commands_run,
        verifier_evidence_paths=verifier_evidence_paths,
        verifier_blocking_issues=verifier_blocking_issues,
        wave_verdict=wave_verdict,
        wave_reasons=wave_reasons,
        create_rework=create_rework,
        prefer_agent_output=prefer_agent_output,
        run_architect=run_architect,
        run_planner=run_planner,
        commit_hash=commit_hash,
        rework_routing_policy=rework_routing_policy,
        reviewer_verdict_script=reviewer_verdict_script,
        review_reasons_script=review_reasons_script,
        wave_verdict_script=wave_verdict_script,
        wave_reasons_script=wave_reasons_script,
    )
    deps = _build_pipeline_deps()
    state, final_result = run_bootstrap_phase(runtime, deps)
    logger.info("PHASE_END", extra={
        "phase": "bootstrap",
        "feature_id": feature_id,
        "timestamp": datetime.now(timezone.utc).isoformat()
    })
    if final_result is not None:
        return final_result

    logger.info("PHASE_START", extra={
        "phase": "planning",
        "feature_id": feature_id,
        "timestamp": datetime.now(timezone.utc).isoformat()
    })
    final_result = run_planning_phase(runtime, deps, state)
    logger.info("PHASE_END", extra={
        "phase": "planning",
        "feature_id": feature_id,
        "timestamp": datetime.now(timezone.utc).isoformat()
    })
    if final_result is not None:
        return final_result

    logger.info("PHASE_START", extra={
        "phase": "execution",
        "feature_id": feature_id,
        "timestamp": datetime.now(timezone.utc).isoformat()
    })
    final_result = run_wave_execution_phase(runtime, deps, state)
    logger.info("PHASE_END", extra={
        "phase": "execution",
        "feature_id": feature_id,
        "timestamp": datetime.now(timezone.utc).isoformat()
    })
    if final_result is not None:
        return final_result

    logger.info("PHASE_START", extra={
        "phase": "finalization",
        "feature_id": feature_id,
        "timestamp": datetime.now(timezone.utc).isoformat()
    })
    result = run_finalization_phase(runtime, deps, state)
    logger.info("PHASE_END", extra={
        "phase": "finalization",
        "feature_id": feature_id,
        "timestamp": datetime.now(timezone.utc).isoformat()
    })
    return result


# START_FUNCTION_CONTRACT
# name: review_router_flow
# purpose: Run the standalone review router flow for one packet verdict.
# inputs: Packet id, review verdict, optional reasons, and create_rework flag.
# returns: Review task result dictionary with review and optional rework.
# side_effects: Calls review_task, which records review state and may create rework.
# emitted_logs: Prefect flow/task logs.
# error_behavior: Propagates review_task errors.
# END_FUNCTION_CONTRACT
@flow(name="prefect-grace-review-router", flow_run_name="review:{packet_id}:{verdict}")
def review_router_flow(
    packet_id: str,
    verdict: str,
    reasons: list[str] | None = None,
    create_rework: bool = True,
):
    return review_task(
        packet_id=packet_id,
        verdict=verdict,
        reasons=reasons or [],
        create_rework=create_rework,
    )


if __name__ == "__main__":
    feature_pipeline(
        feature_id="FEAT-PREFECT-GRACE-SCAFFOLD",
        title="Prefect Grace Scaffold",
        summary="Bootstrap file-backed Prefect orchestration for strict GRACE workflows.",
        dry_run=True,
    )
