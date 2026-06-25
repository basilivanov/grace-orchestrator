# ############################################################################
# AI_HEADER: api_routers_admin
# ROLE: Admin v2 router — /api/admin/* read endpoints + planned control stubs.
#       Powers the vanilla SPA at /admin. All read endpoints compose
#       AdminAggregationService. Control endpoints (resume/delete/stop) return
#       501 with `planned: "v2"` until TZ_SESSION_RESUME is implemented.
# ############################################################################

# START_MODULE_CONTRACT
# purpose: Serve the admin SPA's JSON API. Read-only v1. Endpoints are designed
#          per docs/TZ_ADMIN_PANEL.md. Forward-compatible with TZ_SESSION_RESUME
#          and TZ_FRONTEND_ACCEPTANCE (graceful when tables/stages are absent).
# inputs: HTTP GET (read) / POST (planned stubs) with path and query params.
# returns: Plain dicts (no `data` envelope) for direct SPA consumption.
# side_effects: None.
# emitted_logs: None.
# error_behavior: 404 on missing entities; 403 on path-traversal; 501 on stubs.
# END_MODULE_CONTRACT

# START_MODULE_MAP
# mapping:
#   - router: APIRouter
#   routes:
#       - GET  /api/admin/overview
#       - GET  /api/admin/features
#       - GET  /api/admin/packet/{packet_id}/detail
#       - GET  /api/admin/packet/{packet_id}/blocking_decision
#       - GET  /api/admin/packet/{packet_id}/timeline
#       - GET  /api/admin/packet/{packet_id}/runs
#       - GET  /api/admin/packet/{packet_id}/runs/{run_id}
#       - GET  /api/admin/packet/{packet_id}/runs/{run_id}/evidence
#       - GET  /api/admin/packet/{packet_id}/sessions
#       - GET  /api/admin/packet/{packet_id}/runs/{run_id}/artifacts
#       - GET  /api/admin/packet/{packet_id}/runs/{run_id}/artifacts/file
#       - GET  /api/admin/packet/{packet_id}/runs/{run_id}/logs
#       - GET  /api/admin/feature/{feature_id}/summary
#       - GET  /api/admin/search
#       - GET  /api/admin/system/health
#       - GET  /api/admin/system/workers
#       - POST /api/admin/packet/{packet_id}/resume
#       - POST /api/admin/packet/{packet_id}/delete
#       - POST /api/admin/packet/{packet_id}/stop
# END_MODULE_MAP

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import JSONResponse, Response

from grace_control.core.structured_logger import GraceLogger
from grace_control.db import get_db
from grace_control.db.schema import Feature
from grace_control.services.admin_aggregation_service import AdminAggregationService

router = APIRouter()
_log = GraceLogger("admin")
_svc = AdminAggregationService()


# START_BLOCK_OVERVIEW

# START_FUNCTION_CONTRACT
# name: overview
# purpose: Return the admin overview dashboard data.
# inputs: None.
# returns: dict with overview stats.
# side_effects: None.
# emitted_logs: None.
# error_behavior: Never raises.
# END_FUNCTION_CONTRACT
@router.get("/api/admin/overview")
def overview() -> dict:
    _log.info("admin_overview_requested")
    with get_db() as db:
        return _svc.get_overview(db)


# START_FUNCTION_CONTRACT
# name: features_tree
# purpose: Return all features with nested waves and packets for the overview tree.
# inputs: include_archived (bool, default False).
# returns: dict with feature tree.
# side_effects: None.
# emitted_logs: None.
# error_behavior: Never raises.
# END_FUNCTION_CONTRACT
@router.get("/api/admin/features")
def features_tree(include_archived: bool = Query(False)) -> dict:
    """All features with nested waves → packets. Powers the main Overview."""
    with get_db() as db:
        return _svc.get_features_tree(db, include_archived=include_archived)

# END_BLOCK_OVERVIEW

# START_BLOCK_PACKET_DETAIL


# START_FUNCTION_CONTRACT
# name: packet_detail
# purpose: Return details for a single packet.
# inputs: packet_id (str) — path parameter.
# returns: dict with packet detail.
# side_effects: None.
# emitted_logs: None.
# error_behavior: 404 if packet not found.
# END_FUNCTION_CONTRACT
@router.get("/api/admin/packet/{packet_id}/detail")
def packet_detail(packet_id: str) -> dict:
    with get_db() as db:
        detail = _svc.get_packet_detail(db, packet_id)
    if detail is None:
        raise HTTPException(status_code=404, detail="packet not found")
    return detail


# START_FUNCTION_CONTRACT
# name: packet_blocking_decision
# purpose: Return the blocking decision for a packet, if any.
# inputs: packet_id (str).
# returns: dict with has_blocking, state, decided_by, action, reason, at, last_failure.
# side_effects: None.
# emitted_logs: None.
# error_behavior: Never raises — returns default null structure.
# END_FUNCTION_CONTRACT
@router.get("/api/admin/packet/{packet_id}/blocking_decision")
def packet_blocking_decision(packet_id: str) -> dict:
    with get_db() as db:
        decision = _svc.get_packet_blocking_decision(db, packet_id)
    if decision is None:
        return {"has_blocking": False, "state": None, "decided_by": None,
                "action": None, "reason": None, "at": None, "last_failure": None}
    return decision


# START_FUNCTION_CONTRACT
# name: packet_timeline
# purpose: Return the execution timeline for a packet.
# inputs: packet_id (str), limit (int, 1-1000, default 200), offset (int, default 0).
# returns: dict with timeline entries.
# side_effects: None.
# emitted_logs: None.
# error_behavior: Never raises.
# END_FUNCTION_CONTRACT
@router.get("/api/admin/packet/{packet_id}/timeline")
def packet_timeline(
    packet_id: str,
    limit: int = Query(200, ge=1, le=1000),
    offset: int = Query(0, ge=0),
) -> dict:
    with get_db() as db:
        return _svc.get_packet_timeline(db, packet_id, limit=limit, offset=offset)

# END_BLOCK_PACKET_DETAIL

# START_BLOCK_RUNS


# START_FUNCTION_CONTRACT
# name: packet_runs
# purpose: Return all runs for a packet.
# inputs: packet_id (str).
# returns: dict with list of runs.
# side_effects: None.
# emitted_logs: None.
# error_behavior: Never raises.
# END_FUNCTION_CONTRACT
@router.get("/api/admin/packet/{packet_id}/runs")
def packet_runs(packet_id: str) -> dict:
    with get_db() as db:
        return _svc.get_packet_runs(db, packet_id)


# START_FUNCTION_CONTRACT
# name: packet_run
# purpose: Return a single run by ID for a packet.
# inputs: packet_id (str), run_id (str).
# returns: dict with run details.
# side_effects: None.
# emitted_logs: None.
# error_behavior: 404 if run not found.
# END_FUNCTION_CONTRACT
@router.get("/api/admin/packet/{packet_id}/runs/{run_id}")
def packet_run(packet_id: str, run_id: str) -> dict:
    with get_db() as db:
        out = _svc.get_packet_run(db, packet_id, run_id)
    if out is None:
        raise HTTPException(status_code=404, detail="run not found")
    return out


# START_FUNCTION_CONTRACT
# name: packet_run_evidence
# purpose: Return evidence for a specific run.
# inputs: packet_id (str), run_id (str).
# returns: dict with evidence data.
# side_effects: None.
# emitted_logs: None.
# error_behavior: Never raises.
# END_FUNCTION_CONTRACT
@router.get("/api/admin/packet/{packet_id}/runs/{run_id}/evidence")
def packet_run_evidence(packet_id: str, run_id: str) -> dict:
    with get_db() as db:
        return _svc.get_packet_evidence(db, packet_id, run_id=run_id)

# END_BLOCK_RUNS

# START_BLOCK_SESSIONS


# START_FUNCTION_CONTRACT
# name: packet_sessions
# purpose: Return sessions for a packet (forward-compat with TZ_SESSION_RESUME).
# inputs: packet_id (str).
# returns: dict with session data.
# side_effects: None.
# emitted_logs: None.
# error_behavior: Never raises.
# END_FUNCTION_CONTRACT
@router.get("/api/admin/packet/{packet_id}/sessions")
def packet_sessions(packet_id: str) -> dict:
    with get_db() as db:
        return _svc.get_packet_sessions(db, packet_id)

# END_BLOCK_SESSIONS

# START_BLOCK_ARTIFACTS


# START_FUNCTION_CONTRACT
# name: packet_run_artifacts
# purpose: List artifacts for a given packet run.
# inputs: packet_id (str), run_id (str).
# returns: dict with artifact listing.
# side_effects: None.
# emitted_logs: None.
# error_behavior: Never raises.
# END_FUNCTION_CONTRACT
@router.get("/api/admin/packet/{packet_id}/runs/{run_id}/artifacts")
def packet_run_artifacts(packet_id: str, run_id: str) -> dict:
    with get_db() as db:
        return _svc.get_packet_artifacts(db, packet_id, run_id)


# START_FUNCTION_CONTRACT
# name: packet_run_artifact_file
# purpose: Read a specific artifact file, with optional tail (last N lines).
# inputs: packet_id (str), run_id (str), path (str), tail (int, 0-100000).
# returns: Response with file content, or 403 error.
# side_effects: Reads file from evidence dir.
# emitted_logs: None.
# error_behavior: 403 on forbidden or missing paths.
# END_FUNCTION_CONTRACT
@router.get("/api/admin/packet/{packet_id}/runs/{run_id}/artifacts/file")
def packet_run_artifact_file(
    packet_id: str, run_id: str,
    path: str = Query("", description="Relative path inside the evidence dir"),
    tail: int = Query(0, ge=0, le=100000, description="Last N lines for text files"),
):
    with get_db() as db:
        result = _svc.get_artifact_file(db, packet_id, run_id, path, tail=tail)
    if result is None:
        return JSONResponse({"error": "forbidden or not found"}, status_code=403)
    content, ctype = result
    return Response(content=content, media_type=ctype)

# END_BLOCK_ARTIFACTS

# START_BLOCK_LOGS


# START_FUNCTION_CONTRACT
# name: packet_run_logs
# purpose: Return logs for a specific packet run, with stream/tail/filter options.
# inputs: packet_id (str), run_id (str), stream ("stderr"|"stdout"|"agent"),
#         tail (int, 0-10000), filter (str, optional regex).
# returns: dict with log lines.
# side_effects: None.
# emitted_logs: None.
# error_behavior: Never raises.
# END_FUNCTION_CONTRACT
@router.get("/api/admin/packet/{packet_id}/runs/{run_id}/logs")
def packet_run_logs(
    packet_id: str, run_id: str,
    stream: str = Query("stderr", pattern="^(stderr|stdout|agent)$"),
    tail: int = Query(200, ge=0, le=10000),
    filter: str = Query("", description="Optional regex to filter lines"),
) -> dict:
    with get_db() as db:
        return _svc.get_packet_logs(
            db, packet_id, run_id,
            stream=stream, tail=tail, filter_regex=filter,
        )

# END_BLOCK_LOGS

# START_BLOCK_FEATURE_SEARCH_SYSTEM


# START_FUNCTION_CONTRACT
# name: feature_summary
# purpose: Return summary for a single feature.
# inputs: feature_id (str).
# returns: dict with feature summary.
# side_effects: None.
# emitted_logs: None.
# error_behavior: 404 if feature not found.
# END_FUNCTION_CONTRACT
@router.get("/api/admin/feature/{feature_id}/summary")
def feature_summary(feature_id: str) -> dict:
    with get_db() as db:
        out = _svc.get_feature_summary(db, feature_id)
    if out is None:
        raise HTTPException(status_code=404, detail="feature not found")
    return out


# START_FUNCTION_CONTRACT
# name: search
# purpose: Search packets and features across the system.
# inputs: q (str), limit (int, 1-200, default 50).
# returns: dict with search results.
# side_effects: None.
# emitted_logs: None.
# error_behavior: Never raises.
# END_FUNCTION_CONTRACT
@router.get("/api/admin/search")
def search(
    q: str = Query("", description="Search query"),
    limit: int = Query(50, ge=1, le=200),
) -> dict:
    with get_db() as db:
        return _svc.search(db, q, limit=limit)


# START_FUNCTION_CONTRACT
# name: system_health
# purpose: Return system health status.
# inputs: None.
# returns: dict with health status.
# side_effects: None.
# emitted_logs: None.
# error_behavior: Never raises.
# END_FUNCTION_CONTRACT
@router.get("/api/admin/system/health")
def system_health() -> dict:
    return _svc.get_system_health()


@router.get("/api/admin/system/logs")
def system_logs(tail: int = Query(100, ge=10, le=5000)) -> dict:
    """Return recent lines from the server log file (JSONL + access logs)."""
    from pathlib import Path
    import glob
    # Find the most recent api log file
    candidates = sorted(Path("/tmp").glob("api*.log"), key=lambda p: p.stat().st_mtime, reverse=True)
    if not candidates:
        return {"lines": [], "source": ""}
    log_path = candidates[0]
    lines = log_path.read_text(errors="replace").splitlines()
    return {"lines": lines[-tail:], "total": len(lines), "source": log_path.name}


# START_FUNCTION_CONTRACT
# name: system_workers
# purpose: Return list of workers and their status.
# inputs: None.
# returns: dict with worker data.
# side_effects: None.
# emitted_logs: None.
# error_behavior: Never raises.
# END_FUNCTION_CONTRACT
@router.get("/api/admin/system/workers")
def system_workers() -> dict:
    with get_db() as db:
        return _svc.get_workers(db)


# START_FUNCTION_CONTRACT
# name: archive_feature
# purpose: Mark a feature as ARCHIVED.
# inputs: feature_id (str) — path parameter.
# returns: dict with ok, feature_id, status.
# side_effects: DB update on Feature row.
# emitted_logs: None.
# error_behavior: 404 if feature not found.
# END_FUNCTION_CONTRACT
@router.post("/api/admin/feature/{feature_id}/archive")
def archive_feature(feature_id: str) -> dict:
    """Mark a feature as ARCHIVED."""
    with get_db() as db:
        feat = db.query(Feature).filter_by(id=feature_id).first()
        if not feat:
            raise HTTPException(status_code=404, detail="feature not found")
        feat.status = "ARCHIVED"
        db.commit()
        return {"ok": True, "feature_id": feature_id, "status": "ARCHIVED"}


# START_FUNCTION_CONTRACT
# name: unarchive_feature
# purpose: Restore an archived feature to NOT_STARTED.
# inputs: feature_id (str) — path parameter.
# returns: dict with ok, feature_id, status.
# side_effects: DB update on Feature row.
# emitted_logs: None.
# error_behavior: 404 if feature not found.
# END_FUNCTION_CONTRACT
@router.post("/api/admin/feature/{feature_id}/unarchive")
def unarchive_feature(feature_id: str) -> dict:
    """Restore an archived feature."""
    with get_db() as db:
        feat = db.query(Feature).filter_by(id=feature_id).first()
        if not feat:
            raise HTTPException(status_code=404, detail="feature not found")
        feat.status = "NOT_STARTED"
        db.commit()
        return {"ok": True, "feature_id": feature_id, "status": "NOT_STARTED"}

# END_BLOCK_FEATURE_SEARCH_SYSTEM

# START_BLOCK_PLANNED_CONTROL_STUBS


from grace_control.services.packet_control_service import retry_packet as _retry, cancel_packet as _cancel, delete_packet as _delete


@router.post("/api/admin/packet/{packet_id}/resume")
def packet_resume(packet_id: str) -> dict:
    """Retry a BLOCKED_RECOVERABLE or REJECTED packet."""
    try:
        return _retry(packet_id, actor="admin_ui", reason="manual_retry")
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.post("/api/admin/packet/{packet_id}/delete")
def packet_delete(packet_id: str, body: dict = {}) -> dict:
    """Delete a packet and its runs."""
    confirm = body.get("confirm", "")
    try:
        return _delete(packet_id, confirm=confirm, actor="admin_ui")
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.post("/api/admin/packet/{packet_id}/stop")
def packet_stop(packet_id: str) -> dict:
    """Cancel a running packet."""
    try:
        return _cancel(packet_id, actor="admin_ui", reason="manual_cancel")
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

# END_BLOCK_PLANNED_CONTROL_STUBS
