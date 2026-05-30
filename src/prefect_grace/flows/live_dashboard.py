from __future__ import annotations

from prefect_grace.prefect_compat import flow, get_run_logger, task
from prefect_grace.tasks.grace_dashboard import build_grace_dashboard_snapshot
from prefect_grace.tasks.prefect_artifacts import publish_live_dashboard_artifact, publish_run_mapping_artifact


@task(task_run_name="dashboard:snapshot")
def build_dashboard_snapshot() -> dict[str, object]:
    snapshot = build_grace_dashboard_snapshot()
    return {
        "feature_status_counts": dict(snapshot.get("feature_status_counts") or {}),
        "packet_status_counts": dict(snapshot.get("packet_status_counts") or {}),
        "job_status_counts": dict(snapshot.get("job_status_counts") or {}),
        "blocked_features": [
            f"{item.get('feature_id')}: {item.get('title')} [{item.get('status')}]"
            for item in list(snapshot.get("blocked_features") or [])
        ],
        "blocked_packets": [
            f"{item.get('packet_id')}: role={item.get('role')} status={item.get('status')}"
            for item in list(snapshot.get("packets") or [])
            if str(item.get("status") or "") == "blocked"
        ],
        "pending_packets": [
            f"{item.get('packet_id')}: role={item.get('role')} status={item.get('status')}"
            for item in list(snapshot.get("packets") or [])
            if str(item.get("status") or "") in {"ready", "review", "rework_required", "architect_ready", "coding", "verifying"}
        ][:50],
        "active_jobs": [
            f"{item.get('job_id')}: feature={item.get('feature_id')} status={item.get('status')} flow_run_id={item.get('flow_run_id') or '-'}"
            for item in list(snapshot.get("queued_jobs") or [])
        ][:50],
        "run_mappings": [
            {
                "flow_run_id": item.get("flow_run_id"),
                "feature_id": item.get("feature_id"),
                "wave": item.get("wave"),
                "packet_id": item.get("packet_id"),
                "role": item.get("role"),
                "status": item.get("status"),
                "artifact_paths": list(item.get("artifact_paths") or []),
            }
            for item in list(snapshot.get("run_mappings") or [])
        ][:50],
    }


@task(task_run_name="dashboard:publish")
def publish_dashboard_task(snapshot: dict[str, object]) -> dict[str, object]:
    logger = get_run_logger()
    artifact_id = publish_live_dashboard_artifact(
        feature_status_counts=dict(snapshot.get("feature_status_counts") or {}),
        packet_status_counts=dict(snapshot.get("packet_status_counts") or {}),
        job_status_counts=dict(snapshot.get("job_status_counts") or {}),
        blocked_features=list(snapshot.get("blocked_features") or []),
        blocked_packets=list(snapshot.get("blocked_packets") or []),
        pending_packets=list(snapshot.get("pending_packets") or []),
        active_jobs=list(snapshot.get("active_jobs") or []),
        run_mappings=[
            f"{item.get('flow_run_id') or '-'}: feature={item.get('feature_id')} wave={item.get('wave')} packet={item.get('packet_id')} role={item.get('role')} status={item.get('status')}"
            for item in list(snapshot.get("run_mappings") or [])
        ],
    )
    mapping_artifact_id = publish_run_mapping_artifact(mappings=list(snapshot.get("run_mappings") or []))
    logger.info("Published live dashboard artifact id=%s", artifact_id)
    logger.info("Published run mapping artifact id=%s", mapping_artifact_id)
    return {"artifact_id": artifact_id, "mapping_artifact_id": mapping_artifact_id, **snapshot}


@flow(name="prefect-grace-live-dashboard", flow_run_name="dashboard:grace-live")
def live_dashboard_flow() -> dict[str, object]:
    return publish_dashboard_task(build_dashboard_snapshot())
