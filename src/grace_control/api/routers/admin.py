# ############################################################################
# AI_HEADER: api_routers_admin
# ROLE: Admin v2 router — /api/admin/* read endpoints and packet controls.
#       Powers the vanilla SPA at /admin. All read endpoints compose
#       AdminAggregationService. Packet controls delegate to the domain service
#       and return validation/state errors instead of fabricating success.
# ############################################################################

# START_MODULE_CONTRACT
# purpose: Serve the admin SPA's JSON API. Read-only v1. Endpoints are designed
#          per docs/TZ_ADMIN_PANEL.md. Forward-compatible with TZ_SESSION_RESUME
#          and TZ_FRONTEND_ACCEPTANCE (graceful when tables/stages are absent).
# inputs: HTTP GET (read) / POST (packet control) with path and query params.
# returns: Plain dicts (no `data` envelope) for direct SPA consumption.
# side_effects: Read endpoints are side-effect free; confirmed legacy mutation
#               aliases delegate to the canonical project-local control/audit
#               service, while destructive unsupported aliases stay unavailable.
# emitted_logs: None.
# error_behavior: 404 on missing entities; 400 on invalid controls; 403 on
#                 path-traversal.
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
#       - GET  /api/admin/packet/{packet_id}/runs/{run_id}/artifacts/preview
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

from typing import Any

from fastapi import APIRouter, Body, HTTPException, Query, Request
from fastapi.responses import JSONResponse, Response

from grace_control.api.routers.admin_controls import legacy_admin_action
from grace_control.config.settings import settings
from grace_control.core.structured_logger import GraceLogger
from grace_control.db import get_db
from grace_control.services.admin_aggregation_service import AdminAggregationService
from grace_control.services.safe_filesystem_service import FilesystemReadError, SafeFilesystemService

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


# START_FUNCTION_CONTRACT
# name: packet_run_artifact_preview
# purpose: Return a bounded JSON-safe artifact preview for the Stage 05
#          explorer without streaming unbounded project bytes.
# inputs: packet_id, run_id, relative path and max_bytes cap.
# returns: Safe preview metadata/content DTO.
# side_effects: Reads only the selected run's evidence root through the
#                aggregation service's safe filesystem boundary.
# emitted_logs: None.
# error_behavior: 404 with a typed safe error when the run/path is unavailable.
# END_FUNCTION_CONTRACT
@router.get("/api/admin/packet/{packet_id}/runs/{run_id}/artifacts/preview")
def packet_run_artifact_preview(
    packet_id: str,
    run_id: str,
    path: str = Query("", description="Relative path inside the evidence dir"),
    max_bytes: int = Query(512 * 1024, ge=1, le=512 * 1024),
) -> dict:
    with get_db() as db:
        result = _svc.get_artifact_preview(db, packet_id, run_id, path, max_bytes=max_bytes)
    if result is None:
        return JSONResponse(
            {"error": {"code": "ARTIFACT_NOT_FOUND_OR_FORBIDDEN", "message": "artifact is unavailable"}},
            status_code=404,
        )
    return {**result, "source": "API"}

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


# START_FUNCTION_CONTRACT
# name: system_logs
# purpose: Return a bounded tail from the current project's configured logs
#          root without reading a process-global temporary directory.
# inputs: tail — requested line count, bounded to 10..5000.
# returns: JSON lines, bounded row count, source-relative path, byte count and
#          truncation metadata.
# side_effects: Reads only the server-resolved project logs root.
# emitted_logs: filesystem_read_rejected, filesystem_read_done.
# error_behavior: Missing/unavailable project logs become an empty safe result.
# END_FUNCTION_CONTRACT
@router.get("/api/admin/system/logs")
def system_logs(tail: int = Query(100, ge=10, le=5000)) -> dict:
    """Return recent lines from the current project's configured log root."""
    try:
        reader = SafeFilesystemService.from_runtime(settings_obj=settings)
        entries = reader.list_entries("logs")["entries"]
        files = [entry for entry in entries if entry.get("kind") == "file"]
        if not files:
            return {"lines": [], "total": 0, "source": "", "truncated": False}
        selected = max(files, key=lambda entry: float(entry.get("mtime") or 0))
        payload = reader.tail_file("logs", str(selected["relative_path"]), lines=tail)
        lines = str(payload.get("content") or "").splitlines()
        return {
            "lines": lines,
            "total": len(lines),
            "total_bytes": int(payload.get("size") or 0),
            "source": str(selected["relative_path"]),
            "truncated": bool(payload.get("truncated")),
        }
    except (FilesystemReadError, OSError, ValueError):
        return {"lines": [], "total": 0, "source": "", "truncated": False}


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
# returns: Canonical control JSON response with project-local audit identity.
# side_effects: Delegates the selected feature mutation through the canonical
#               project-local control service and audit gate.
# emitted_logs: None.
# error_behavior: 401/403 for unsafe credentials/origin; 400/404 for domain or
#                 confirmation failures.
# END_FUNCTION_CONTRACT
@router.post("/api/admin/feature/{feature_id}/archive")
async def archive_feature(
    request: Request,
    feature_id: str,
    body: dict[str, Any] = Body(default_factory=dict),
) -> JSONResponse:
    return await legacy_admin_action(
        request,
        action="archive",
        entity_type="feature",
        entity_id=feature_id,
        body=body,
    )


# START_FUNCTION_CONTRACT
# name: unarchive_feature
# purpose: Restore an archived feature to NOT_STARTED.
# inputs: feature_id (str) — path parameter.
# returns: Canonical control JSON response with project-local audit identity.
# side_effects: Delegates the selected feature mutation through the canonical
#               project-local control service and audit gate.
# emitted_logs: None.
# error_behavior: 401/403 for unsafe credentials/origin; 400/404 for domain or
#                 confirmation failures.
# END_FUNCTION_CONTRACT
@router.post("/api/admin/feature/{feature_id}/unarchive")
async def unarchive_feature(
    request: Request,
    feature_id: str,
    body: dict[str, Any] = Body(default_factory=dict),
) -> JSONResponse:
    return await legacy_admin_action(
        request,
        action="unarchive",
        entity_type="feature",
        entity_id=feature_id,
        body=body,
    )

# END_BLOCK_FEATURE_SEARCH_SYSTEM

# START_BLOCK_PACKET_CONTROLS


@router.post("/api/admin/packet/{packet_id}/resume")
async def packet_resume(
    request: Request,
    packet_id: str,
    body: dict[str, Any] = Body(default_factory=dict),
) -> JSONResponse:
    """Legacy alias for the canonical confirmed packet retry action."""
    return await legacy_admin_action(
        request,
        action="retry",
        entity_type="packet",
        entity_id=packet_id,
        body=body,
        parameters={"reason": "manual_retry"},
    )


@router.post("/api/admin/packet/{packet_id}/delete")
async def packet_delete(
    request: Request,
    packet_id: str,
    body: dict[str, Any] = Body(default_factory=dict),
) -> JSONResponse:
    """Keep the destructive legacy alias unavailable behind the audit gate."""
    return await legacy_admin_action(
        request,
        action="delete",
        entity_type="packet",
        entity_id=packet_id,
        body=body,
    )


@router.post("/api/admin/packet/{packet_id}/stop")
async def packet_stop(
    request: Request,
    packet_id: str,
    body: dict[str, Any] = Body(default_factory=dict),
) -> JSONResponse:
    """Legacy alias for the canonical confirmed packet cancel action."""
    return await legacy_admin_action(
        request,
        action="cancel",
        entity_type="packet",
        entity_id=packet_id,
        body=body,
        parameters={"reason": "manual_cancel"},
    )

# END_BLOCK_PACKET_CONTROLS
