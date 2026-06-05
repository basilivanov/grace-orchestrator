"""Trace API — /api/trace/{packets,features,runs,search}.

Replaces the `grace trace --packet/--feature/--wave` CLI from W2.
"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query

from grace_control.db import get_db
from grace_control.services.trace_service import TraceService

router = APIRouter()
_svc = TraceService()


@router.get("/packets/{packet_id}")
def get_packet_trace(packet_id: str) -> dict:
    with get_db() as db:
        trace = _svc.get_packet_trace(db, packet_id)
    if trace is None:
        raise HTTPException(status_code=404, detail=f"Packet {packet_id} not found")
    return {"data": trace, "timestamp": _now()}


@router.get("/features/{feature_id}")
def get_feature_trace(feature_id: str) -> dict:
    with get_db() as db:
        trace = _svc.get_feature_trace(db, feature_id)
    if trace is None:
        raise HTTPException(status_code=404, detail=f"Feature {feature_id} not found")
    return {"data": trace, "timestamp": _now()}


@router.get("/runs/{run_id}")
def get_run_trace(run_id: str) -> dict:
    with get_db() as db:
        trace = _svc.get_run_trace(db, run_id)
    if trace is None:
        raise HTTPException(status_code=404, detail=f"Run {run_id} not found")
    return {"data": trace, "timestamp": _now()}


@router.get("/search")
def search_trace(
    q: str = Query("", description="Substring to search for"),
    limit: int = Query(25, ge=1, le=200),
) -> dict:
    with get_db() as db:
        results = _svc.search(db, q=q, limit=limit)
    return {"data": {"q": q, "results": results}, "timestamp": _now()}


def _now() -> str:
    from datetime import datetime
    return datetime.utcnow().isoformat() + "Z"
