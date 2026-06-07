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

from grace_control.db import get_db
from grace_control.services.admin_aggregation_service import AdminAggregationService

router = APIRouter()
_svc = AdminAggregationService()


# ── Overview ───────────────────────────────────────────────────────────────


@router.get("/api/admin/overview")
def overview() -> dict:
    with get_db() as db:
        return _svc.get_overview(db)


@router.get("/api/admin/features")
def features_tree() -> dict:
    """All features with nested waves → packets. Powers the main Overview."""
    with get_db() as db:
        return _svc.get_features_tree(db)


# ── Packet detail ──────────────────────────────────────────────────────────


@router.get("/api/admin/packet/{packet_id}/detail")
def packet_detail(packet_id: str) -> dict:
    with get_db() as db:
        detail = _svc.get_packet_detail(db, packet_id)
    if detail is None:
        raise HTTPException(status_code=404, detail="packet not found")
    return detail


@router.get("/api/admin/packet/{packet_id}/blocking_decision")
def packet_blocking_decision(packet_id: str) -> dict:
    with get_db() as db:
        decision = _svc.get_packet_blocking_decision(db, packet_id)
    if decision is None:
        return {"has_blocking": False, "state": None, "decided_by": None,
                "action": None, "reason": None, "at": None, "last_failure": None}
    return decision


@router.get("/api/admin/packet/{packet_id}/timeline")
def packet_timeline(
    packet_id: str,
    limit: int = Query(200, ge=1, le=1000),
    offset: int = Query(0, ge=0),
) -> dict:
    with get_db() as db:
        return _svc.get_packet_timeline(db, packet_id, limit=limit, offset=offset)


# ── Runs ───────────────────────────────────────────────────────────────────


@router.get("/api/admin/packet/{packet_id}/runs")
def packet_runs(packet_id: str) -> dict:
    with get_db() as db:
        return _svc.get_packet_runs(db, packet_id)


@router.get("/api/admin/packet/{packet_id}/runs/{run_id}")
def packet_run(packet_id: str, run_id: str) -> dict:
    with get_db() as db:
        out = _svc.get_packet_run(db, packet_id, run_id)
    if out is None:
        raise HTTPException(status_code=404, detail="run not found")
    return out


@router.get("/api/admin/packet/{packet_id}/runs/{run_id}/evidence")
def packet_run_evidence(packet_id: str, run_id: str) -> dict:
    with get_db() as db:
        return _svc.get_packet_evidence(db, packet_id, run_id=run_id)


# ── Sessions (forward-compat) ──────────────────────────────────────────────


@router.get("/api/admin/packet/{packet_id}/sessions")
def packet_sessions(packet_id: str) -> dict:
    with get_db() as db:
        return _svc.get_packet_sessions(db, packet_id)


# ── Artifacts ──────────────────────────────────────────────────────────────


@router.get("/api/admin/packet/{packet_id}/runs/{run_id}/artifacts")
def packet_run_artifacts(packet_id: str, run_id: str) -> dict:
    with get_db() as db:
        return _svc.get_packet_artifacts(db, packet_id, run_id)


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


# ── Logs ───────────────────────────────────────────────────────────────────


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


# ── Feature / Search / System ──────────────────────────────────────────────


@router.get("/api/admin/feature/{feature_id}/summary")
def feature_summary(feature_id: str) -> dict:
    with get_db() as db:
        out = _svc.get_feature_summary(db, feature_id)
    if out is None:
        raise HTTPException(status_code=404, detail="feature not found")
    return out


@router.get("/api/admin/search")
def search(
    q: str = Query("", description="Search query"),
    limit: int = Query(50, ge=1, le=200),
) -> dict:
    with get_db() as db:
        return _svc.search(db, q, limit=limit)


@router.get("/api/admin/system/health")
def system_health() -> dict:
    return _svc.get_system_health()


@router.get("/api/admin/system/workers")
def system_workers() -> dict:
    with get_db() as db:
        return _svc.get_workers(db)


# ── Planned control stubs (v2) ─────────────────────────────────────────────


def _planned(doc: str) -> JSONResponse:
    return JSONResponse(
        status_code=501,
        content={"error": "not_implemented", "planned": "v2", "doc": doc},
    )


@router.post("/api/admin/packet/{packet_id}/resume")
def packet_resume(packet_id: str) -> JSONResponse:
    return _planned("TZ_SESSION_RESUME.md")


@router.post("/api/admin/packet/{packet_id}/delete")
def packet_delete(packet_id: str) -> JSONResponse:
    return _planned("TZ_ADMIN_PANEL.md#planned-control-stubs")


@router.post("/api/admin/packet/{packet_id}/stop")
def packet_stop(packet_id: str) -> JSONResponse:
    return _planned("TZ_ADMIN_PANEL.md#planned-control-stubs")
