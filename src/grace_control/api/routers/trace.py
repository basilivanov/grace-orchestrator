# ############################################################################
# AI_HEADER: api_routers_trace
# ROLE: Trace API — /api/trace/{packets,features,runs,search}. Replaces the
#       deleted `grace trace --packet/--feature/--wave` CLI from W2 (W4).
# ############################################################################

# START_MODULE_CONTRACT
# purpose: Thin FastAPI bindings to TraceService. No DB queries here.
# inputs: HTTP requests with path/query params.
# returns: JSON {"data": <trace>, "timestamp": <iso>}.
# side_effects: None.
# emitted_logs: None.
# error_behavior: 404 when the entity is not found.
# END_MODULE_CONTRACT

# START_MODULE_MAP
# mapping:
#   - router: APIRouter
#     routes:
#       - GET /packets/{packet_id}
#       - GET /features/{feature_id}
#       - GET /runs/{run_id}
#       - GET /search
# END_MODULE_MAP

from __future__ import annotations

from datetime import UTC, datetime

from fastapi import APIRouter, HTTPException, Query

from grace_control.db import get_db
from grace_control.services.trace_service import TraceService

router = APIRouter()
_svc = TraceService()


# START_FUNCTION_CONTRACT
# name: get_packet_trace
# purpose: HTTP wrapper around TraceService.get_packet_trace.
# inputs: packet_id (str path param).
# returns: dict {"data": <trace>, "timestamp": iso}.
# side_effects: None.
# emitted_logs: None.
# error_behavior: 404 when packet is not found.
# END_FUNCTION_CONTRACT
@router.get("/packets/{packet_id}")
def get_packet_trace(packet_id: str) -> dict:
    with get_db() as db:
        trace = _svc.get_packet_trace(db, packet_id)
    if trace is None:
        raise HTTPException(status_code=404, detail=f"Packet {packet_id} not found")
    return {"data": trace, "timestamp": _now()}


# START_FUNCTION_CONTRACT
# name: get_feature_trace
# purpose: HTTP wrapper around TraceService.get_feature_trace.
# inputs: feature_id (str path param).
# returns: dict {"data": <trace>, "timestamp": iso}.
# side_effects: None.
# emitted_logs: None.
# error_behavior: 404 when feature is not found.
# END_FUNCTION_CONTRACT
@router.get("/features/{feature_id}")
def get_feature_trace(feature_id: str) -> dict:
    with get_db() as db:
        trace = _svc.get_feature_trace(db, feature_id)
    if trace is None:
        raise HTTPException(status_code=404, detail=f"Feature {feature_id} not found")
    return {"data": trace, "timestamp": _now()}


# START_FUNCTION_CONTRACT
# name: get_run_trace
# purpose: HTTP wrapper around TraceService.get_run_trace.
# inputs: run_id (str path param).
# returns: dict {"data": <run>, "timestamp": iso}.
# side_effects: None.
# emitted_logs: None.
# error_behavior: 404 when run is not found.
# END_FUNCTION_CONTRACT
@router.get("/runs/{run_id}")
def get_run_trace(run_id: str) -> dict:
    with get_db() as db:
        trace = _svc.get_run_trace(db, run_id)
    if trace is None:
        raise HTTPException(status_code=404, detail=f"Run {run_id} not found")
    return {"data": trace, "timestamp": _now()}


# START_FUNCTION_CONTRACT
# name: search_trace
# purpose: HTTP wrapper around TraceService.search.
# inputs: q (str, default ""), limit (int, default 25, max 200).
# returns: dict {"data": {"q": q, "results": [...]}, "timestamp": iso}.
# side_effects: None.
# emitted_logs: None.
# error_behavior: Never raises (empty query returns []).
# END_FUNCTION_CONTRACT
@router.get("/search")
def search_trace(
    q: str = Query("", description="Substring to search for"),
    limit: int = Query(25, ge=1, le=200),
) -> dict:
    with get_db() as db:
        results = _svc.search(db, q=q, limit=limit)
    return {"data": {"q": q, "results": results}, "timestamp": _now()}


def _now() -> str:
    return datetime.now(UTC).isoformat() + "Z"
