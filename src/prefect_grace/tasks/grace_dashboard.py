from __future__ import annotations

from collections import Counter
from typing import Any

from pathlib import Path

from prefect_grace.tasks.prefect_runs import feature_run_status_counts, latest_feature_run_index, list_recent_feature_flow_runs
from prefect_grace.tasks.state_store import load_state

STATE_ROOT = Path(__file__).resolve().parents[1] / "state"


def build_grace_dashboard_snapshot(*, state_root: Path | str | None = None) -> dict[str, Any]:
    resolved_state_root = Path(state_root) if state_root else STATE_ROOT
    features = list((load_state("features", state_root=resolved_state_root).get("features") or []))
    packets = list((load_state("packets", state_root=resolved_state_root).get("packets") or []))
    reviews = list((load_state("reviews", state_root=resolved_state_root).get("reviews") or []))
    verifications = list((load_state("verifications", state_root=resolved_state_root).get("verifications") or []))
    wave_reviews = list((load_state("wave_reviews", state_root=resolved_state_root).get("wave_reviews") or []))
    flow_runs = list_recent_feature_flow_runs(limit=200)
    run_index = latest_feature_run_index(flow_runs)
    packet_index = {str(item.get("packet_id")): item for item in packets}
    verification_index = {str(item.get("packet_id")): item for item in verifications}
    review_index = {str(item.get("packet_id")): item for item in reviews}

    run_mappings: list[dict[str, Any]] = []
    for packet in packets:
        last_run = (
            packet.get("last_execution_run")
            or packet.get("last_verifier_run")
            or packet.get("last_codex_run")
            or {}
        )
        flow_run_id = None
        matching_run = run_index.get(str(packet.get("feature_id") or ""))
        if matching_run:
            flow_run_id = matching_run.get("flow_run_id")
        artifact_paths: list[str] = []
        packet_path = packet.get("packet_path")
        if packet_path:
            artifact_paths.append(str(packet_path))
        if last_run.get("stdout_path"):
            artifact_paths.append(str(last_run.get("stdout_path")))
        if last_run.get("stderr_path"):
            artifact_paths.append(str(last_run.get("stderr_path")))
        if last_run.get("last_message_path"):
            artifact_paths.append(str(last_run.get("last_message_path")))
        verification = verification_index.get(str(packet.get("packet_id")))
        if verification and verification.get("verification_path"):
            artifact_paths.append(str(verification.get("verification_path")))
        review = review_index.get(str(packet.get("packet_id")))
        if review and review.get("review_path"):
            artifact_paths.append(str(review.get("review_path")))

        run_mappings.append(
            {
                "flow_run_id": flow_run_id,
                "feature_id": packet.get("feature_id"),
                "wave": packet.get("wave_id"),
                "packet_id": packet.get("packet_id"),
                "role": packet.get("role"),
                "status": packet.get("status"),
                "artifact_paths": artifact_paths,
            }
        )

    return {
        "feature_status_counts": dict(Counter(str(item.get("status") or "unknown") for item in features)),
        "packet_status_counts": dict(Counter(str(item.get("status") or "unknown") for item in packets)),
        "job_status_counts": feature_run_status_counts(flow_runs),
        "queued_jobs": [
            item
            for item in flow_runs
            if str(item.get("state_type") or "") in {"scheduled", "pending", "running"}
        ],
        "blocked_features": [item for item in features if str(item.get("status")) == "blocked"],
        "run_mappings": run_mappings[-50:],
        "flow_runs": flow_runs[-50:],
        "features": features[-20:],
        "packets": packets[-40:],
        "reviews": reviews[-20:],
        "verifications": verifications[-20:],
        "wave_reviews": wave_reviews[-20:],
    }


def render_grace_dashboard(snapshot: dict[str, Any]) -> str:
    lines: list[str] = []
    lines.append("# GRACE Operator Dashboard")
    lines.append("")
    lines.append("## Job Statuses")
    for key, value in sorted(dict(snapshot.get("job_status_counts") or {}).items()):
        lines.append(f"- {key}: {value}")
    lines.append("")
    lines.append("## Feature Statuses")
    for key, value in sorted(dict(snapshot.get("feature_status_counts") or {}).items()):
        lines.append(f"- {key}: {value}")
    lines.append("")
    lines.append("## Packet Statuses")
    for key, value in sorted(dict(snapshot.get("packet_status_counts") or {}).items()):
        lines.append(f"- {key}: {value}")
    lines.append("")
    lines.append("## Active Jobs")
    queued_jobs = list(snapshot.get("queued_jobs") or [])
    if queued_jobs:
        for job in queued_jobs:
            lines.append(
                f"- {job.get('flow_run_id') or '-'} feature={job.get('feature_id')} status={job.get('status')} name={job.get('name')}"
            )
    else:
        lines.append("- none")
    lines.append("")
    lines.append("## Run Mapping")
    mappings = list(snapshot.get("run_mappings") or [])
    if mappings:
        for item in mappings[-10:]:
            lines.append(
                f"- flow_run={item.get('flow_run_id') or '-'} feature={item.get('feature_id')} wave={item.get('wave')} packet={item.get('packet_id')} role={item.get('role')} status={item.get('status')}"
            )
    else:
        lines.append("- none")
    lines.append("")
    lines.append("## Recent Features")
    for feature in list(snapshot.get("features") or [])[-10:]:
        lines.append(
            f"- {feature.get('feature_id')} status={feature.get('status')} title={feature.get('title')}"
        )
    lines.append("")
    lines.append("## Recent Packets")
    for packet in list(snapshot.get("packets") or [])[-15:]:
        lines.append(
            f"- {packet.get('packet_id')} role={packet.get('role')} wave={packet.get('wave_id')} status={packet.get('status')}"
        )
    lines.append("")
    lines.append("## Recent Reviews")
    reviews = list(snapshot.get("reviews") or [])
    if reviews:
        for review in reviews[-10:]:
            lines.append(
                f"- packet={review.get('packet_id')} verdict={review.get('verdict')} follow_up={review.get('follow_up_action')}"
            )
    else:
        lines.append("- none")
    lines.append("")
    lines.append("## Recent Verifications")
    verifications = list(snapshot.get("verifications") or [])
    if verifications:
        for verification in verifications[-10:]:
            lines.append(
                f"- packet={verification.get('packet_id')} test={verification.get('test_verdict')} obs={verification.get('observability_verdict')} visual={verification.get('frontend_visual_verdict')}"
            )
    else:
        lines.append("- none")
    lines.append("")
    lines.append("## Recent Wave Gates")
    wave_reviews = list(snapshot.get("wave_reviews") or [])
    if wave_reviews:
        for review in wave_reviews[-10:]:
            lines.append(
                f"- feature={review.get('feature_id')} wave={review.get('wave_id')} verdict={review.get('verdict')}"
            )
    else:
        lines.append("- none")
    return "\n".join(lines) + "\n"
