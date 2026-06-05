# ############################################################################
# AI_HEADER: self_evolution_router
# ROLE: FastAPI router for /api/self/ — self-evolution session management.
#       W11: no subprocess spawns. Creates session → ready for packet pipeline.
# ############################################################################

# START_MODULE_CONTRACT
# purpose: CRUD for self-evolution sessions. Never spawns worker processes;
#          always returns a session_id for the pipeline to pick up.
# inputs: HTTP request bodies (create_session, list, get, cancel).
# returns: JSON responses with session data.
# side_effects: DB writes (sessions), no subprocess.
# emitted_logs: session_created, context_collected, session_cancelled.
# error_behavior: 404 for missing sessions, 400 for invalid state.
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
from grace_control.db import get_db
from grace_control.db.schema import SelfEvolutionSession
from grace_control.services.self_evolution_service import (
    SelfEvolutionService,
    SessionCreateRequest,
)

router = APIRouter()
_log = GraceLogger("self_evolution")
_svc = SelfEvolutionService()


# START_FUNCTION_CONTRACT
# name: create_session_endpoint
# purpose: Create a self-evolution session. Returns session_id immediately.
#          No subprocess spawn — pipeline picks up from the DB.
# inputs: request (dict — title, description, constraints, prompt, base_branch).
# returns: dict(session_id, status, risk_class, requires_approval, message).
# side_effects: Writes SelfEvolutionSession to DB.
# emitted_logs: session_created.
# error_behavior: 400 for missing title; never spawns processes.
# END_FUNCTION_CONTRACT
@router.post("/evolve")
def create_session_endpoint(request: dict) -> dict:
    title = request.get("title", "")
    description = request.get("description", "")
    constraints = request.get("constraints", {})
    base_branch = request.get("base_branch", "main")
    prompt = request.get("prompt", "")

    if not title:
        raise HTTPException(status_code=400, detail="title is required")

    req = SessionCreateRequest(
        title=title,
        description=description,
        constraints=constraints,
        base_branch=base_branch,
        prompt=prompt,
    )
    resp = _svc.create_session(req, project_root=Path("."))
    _log.info("session_created", session_id=resp.session_id,
        risk=resp.risk_class, requires_approval=resp.requires_approval)
    return {
        "session_id": resp.session_id,
        "status": resp.status,
        "risk_class": resp.risk_class,
        "requires_approval": resp.requires_approval,
        "message": resp.message,
    }


# START_FUNCTION_CONTRACT
# name: list_sessions
# purpose: List all self-evolution sessions.
# inputs: limit (int, default 50), offset (int, default 0).
# returns: dict(data=[{id, title, status, risk_class, created_at, requires_approval}, ...]).
# side_effects: None.
# emitted_logs: None.
# error_behavior: Never raises.
# END_FUNCTION_CONTRACT
@router.get("/sessions")
def list_sessions(limit: int = 50, offset: int = 0) -> dict:
    with get_db() as db:
        sessions = (db.query(SelfEvolutionSession)
                     .order_by(SelfEvolutionSession.created_at.desc())
                     .offset(offset).limit(limit)
                     .all())
        return {"data": [
            {
                "id": s.id,
                "title": s.title,
                "status": s.status,
                "risk_class": s.risk_class or "",
                "requires_approval": s.requires_approval,
                "created_at": s.created_at.isoformat() + "Z" if s.created_at else "",
            }
            for s in sessions
        ]}


# START_FUNCTION_CONTRACT
# name: get_session
# purpose: Return detailed session including rollback plan.
# inputs: session_id (path param).
# returns: dict with full session data.
# side_effects: None.
# emitted_logs: None.
# error_behavior: 404 if session not found.
# END_FUNCTION_CONTRACT
@router.get("/sessions/{session_id}")
def get_session(session_id: str) -> dict:
    with get_db() as db:
        s = db.query(SelfEvolutionSession).filter_by(id=session_id).first()
        if not s:
            raise HTTPException(status_code=404, detail="session not found")
        return {
            "data": {
                "id": s.id,
                "title": s.title,
                "description": s.description,
                "status": s.status,
                "risk_class": s.risk_class or "",
                "requires_approval": s.requires_approval,
                "base_branch": s.base_branch or "main",
                "constraints": s.constraints_json or {},
                "rollback_plan": s.rollback_plan or {},
                "created_at": s.created_at.isoformat() + "Z" if s.created_at else "",
            }
        }


# START_FUNCTION_CONTRACT
# name: cancel_session
# purpose: Cancel a pending self-evolution session.
# inputs: session_id (path param).
# returns: dict(cancelled=True).
# side_effects: Sets session.status to "cancelled".
# emitted_logs: session_cancelled.
# error_behavior: 404 if session not found; 400 if already merged.
# END_FUNCTION_CONTRACT
@router.post("/sessions/{session_id}/cancel")
def cancel_session(session_id: str) -> dict:
    with get_db() as db:
        s = db.query(SelfEvolutionSession).filter_by(id=session_id).first()
        if not s:
            raise HTTPException(status_code=404, detail="session not found")
        if s.status == "merged":
            raise HTTPException(status_code=400, detail="cannot cancel merged session")
        s.status = "cancelled"
    _log.info("session_cancelled", session_id=session_id)
    return {"cancelled": True}
