# ############################################################################
# AI_HEADER: self_evolution_router
# ROLE: FastAPI router for /api/self/ — delegates to SelfEvolutionService.
#       No direct DB queries or mutations (P1-3 from 8dabbaa review).
# ############################################################################

# START_MODULE_CONTRACT
# purpose: CRUD for self-evolution sessions. All DB operations delegated
#          to SelfEvolutionService. No subprocess, no direct DB access.
# inputs: HTTP request bodies.
# returns: JSON responses.
# side_effects: None at router layer.
# error_behavior: 404/400 from service errors, never process spawn.
# END_MODULE_CONTRACT

# START_MODULE_MAP
# mapping:
#   - function: create_session_endpoint
#   - function: list_sessions
#   - function: get_session
#   - function: cancel_session
# END_MODULE_MAP

from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, HTTPException

from grace_control.core.structured_logger import GraceLogger
from grace_control.services.self_evolution_service import (
    SelfEvolutionService,
    SessionCreateRequest,
)

router = APIRouter()
_log = GraceLogger("self_evolution")
_svc = SelfEvolutionService()


@router.post("/evolve")
def create_session_endpoint(request: dict) -> dict:
    title = request.get("title", "")
    if not title:
        raise HTTPException(status_code=400, detail="title is required")
    req = SessionCreateRequest(
        title=title,
        description=request.get("description", ""),
        constraints=request.get("constraints", {}),
        base_branch=request.get("base_branch", "main"),
        prompt=request.get("prompt", ""),
    )
    resp = _svc.create_session(req, project_root=Path("."))
    _log.info("session_created", session_id=resp.session_id, risk=resp.risk_class)
    return {
        "session_id": resp.session_id, "status": resp.status,
        "risk_class": resp.risk_class, "requires_approval": resp.requires_approval,
        "message": resp.message,
    }


@router.get("/sessions")
def list_sessions(limit: int = 50, offset: int = 0) -> dict:
    return {"data": _svc.list_sessions(limit, offset)}


@router.get("/sessions/{session_id}")
def get_session(session_id: str) -> dict:
    data = _svc.get_session(session_id)
    if not data:
        raise HTTPException(status_code=404, detail="session not found")
    return {"data": data}


@router.post("/sessions/{session_id}/cancel")
def cancel_session(session_id: str) -> dict:
    try:
        _svc.cancel_session(session_id)
        return {"cancelled": True}
    except ValueError as e:
        msg = str(e)
        if "not found" in msg:
            raise HTTPException(status_code=404, detail=msg)
        raise HTTPException(status_code=400, detail=msg)
