# ############################################################################
# AI_HEADER: self_evolution_router
# ROLE: FastAPI router for /api/self/ — self-evolution session management.
# ############################################################################

# START_MODULE_CONTRACT
# purpose: CRUD for self-evolution sessions, trigger evolution, view context, cancel.
# inputs: HTTP request bodies (evolve, cancel).
# returns: JSON responses with session data.
# side_effects: DB writes (sessions, features, packets), ContextCollector invocation.
# emitted_logs: session_created, context_collected, session_cancelled.
# error_behavior: 404 for missing sessions, 400 for invalid state transitions.
# END_MODULE_CONTRACT

# START_MODULE_MAP
# mapping:
#   - function: create_evolution
#   - function: list_sessions
#   - function: get_session
#   - function: get_session_context
#   - function: cancel_session
#   - function: guard_check
# END_MODULE_MAP

from __future__ import annotations

import asyncio
import json
import os
import subprocess
import sys
import time
import uuid
from datetime import datetime
from pathlib import Path

import yaml
from fastapi import APIRouter, HTTPException
from fastapi.responses import JSONResponse

from grace_control.core.context_collector import CodebaseContext, ContextCollector
from grace_control.core.self_evolution_guard import SelfEvolutionGuard
from grace_control.core.structured_logger import GraceLogger
from grace_control.api.ws_broadcast import broadcast_event
from grace_control.db import get_db
from grace_control.db.schema import SelfEvolutionSession

router = APIRouter()
_log = GraceLogger("self_evolution")

MAX_SESSIONS = int(os.environ.get("GRACE_SELF_MAX_SESSIONS", "3"))


@router.post("/evolve")
async def create_evolution(request: dict) -> dict:
    title = request.get("title", "")
    description = request.get("description", "")
    constraints = request.get("constraints", {})

    if not title:
        raise HTTPException(status_code=400, detail="title is required")

    with get_db() as db:
        active = db.query(SelfEvolutionSession).filter(
            SelfEvolutionSession.status.in_(
                ["pending", "collecting_context", "planning", "executing", "verifying"]
            )
        ).count()
        if active >= MAX_SESSIONS:
            raise HTTPException(status_code=429, detail=f"Max {MAX_SESSIONS} concurrent sessions")

    session_id = f"ses-{uuid.uuid4().hex[:8]}"

    with get_db() as db:
        session = SelfEvolutionSession(
            id=session_id,
            title=title,
            description=description,
            status="pending",
            constraints_json=constraints,
        )
        db.add(session)
        db.flush()

    _log.info("session_created", session_id=session_id, title=title)

    asyncio.create_task(_run_evolution(session_id, title, description, constraints))

    await broadcast_event("self_evolution_update", {"session_id": session_id, "status": "collecting_context"})

    return {
        "data": {
            "session_id": session_id,
            "status": "collecting_context",
        },
        "timestamp": datetime.utcnow().isoformat() + "Z",
    }


@router.get("/sessions")
async def list_sessions() -> dict:
    with get_db() as db:
        sessions = db.query(SelfEvolutionSession).order_by(
            SelfEvolutionSession.created_at.desc()
        ).limit(20).all()
        data = [_serialize_session(s) for s in sessions]
    return {"data": data, "timestamp": datetime.utcnow().isoformat() + "Z"}


@router.get("/sessions/{session_id}")
async def get_session(session_id: str) -> dict:
    with get_db() as db:
        s = db.query(SelfEvolutionSession).filter_by(id=session_id).first()
        if not s:
            raise HTTPException(status_code=404, detail="Session not found")
        data = _serialize_session(s)
    return {"data": data, "timestamp": datetime.utcnow().isoformat() + "Z"}


@router.get("/sessions/{session_id}/context")
async def get_session_context(session_id: str) -> dict:
    with get_db() as db:
        s = db.query(SelfEvolutionSession).filter_by(id=session_id).first()
        if not s:
            raise HTTPException(status_code=404, detail="Session not found")
        ctx = s.context_json or {}
    return {"data": ctx, "timestamp": datetime.utcnow().isoformat() + "Z"}


@router.post("/sessions/{session_id}/cancel")
async def cancel_session(session_id: str) -> dict:
    with get_db() as db:
        s = db.query(SelfEvolutionSession).filter_by(id=session_id).first()
        if not s:
            raise HTTPException(status_code=404, detail="Session not found")
        if s.status in ("done", "failed", "cancelled"):
            raise HTTPException(status_code=400, detail=f"Cannot cancel terminal session: {s.status}")
        s.status = "cancelled"
        s.finished_at = datetime.utcnow()
        _log.info("session_cancelled", session_id=session_id)

    await broadcast_event("self_evolution_update", {"session_id": session_id, "status": "cancelled"})

    return {
        "data": {"session_id": session_id, "status": "cancelled"},
        "timestamp": datetime.utcnow().isoformat() + "Z",
    }


@router.get("/guard/check")
async def guard_check() -> dict:
    guard = SelfEvolutionGuard()
    project = Path.cwd()
    src = project / "src" / "grace_control"
    files = sorted(src.rglob("*.py")) if src.exists() else []
    result = guard.check(files, session_id="manual-check")
    return {
        "data": {
            "passed": result.passed,
            "checks": [{"name": c.name, "passed": c.passed, "detail": c.detail} for c in result.checks],
            "errors": result.errors,
        },
        "timestamp": datetime.utcnow().isoformat() + "Z",
    }


async def _run_evolution(session_id: str, title: str, description: str, constraints: dict):
    try:
        with get_db() as db:
            s = db.query(SelfEvolutionSession).filter_by(id=session_id).first()
            if s:
                s.status = "collecting_context"

        collector = ContextCollector()
        allowed = constraints.get("allowed_scope", ["src/grace_control/"])
        ctx = await collector.collect(description or title, allowed)

        with get_db() as db:
            s = db.query(SelfEvolutionSession).filter_by(id=session_id).first()
            if s:
                s.status = "planning"
                s.context_json = _context_to_dict(ctx)

        await broadcast_event("self_evolution_update", {"session_id": session_id, "status": "planning",
            "context": _context_to_dict(ctx)})

        from grace_control.api.routers.architect import create_plan

        result = await create_plan({"feature_spec": {
            "title": title,
            "description": description or title,
            "constraints": constraints,
            "origin": "self_evolution",
            "session_id": session_id,
            "self_improvement": True,
        }})

        if not result or "data" not in result:
            raise RuntimeError("Architect plan returned no data")

        feature_id = result["data"]["feature_id"]

        with get_db() as db:
            s = db.query(SelfEvolutionSession).filter_by(id=session_id).first()
            if s:
                s.status = "executing"
                s.feature_id = feature_id

        _log.info("evolution_planned", session_id=session_id, feature_id=feature_id)
        await broadcast_event("self_evolution_update", {"session_id": session_id, "status": "executing",
            "feature_id": feature_id})

        # ── Spawn worker subprocess if none are running ──
        worker_proc = None
        try:
            from grace_control.db import get_db as _gdb2
            from grace_control.db.schema import Worker as _Wkr
            with _gdb2() as db:
                active = db.query(_Wkr).filter_by(status="active").count()
            if active == 0:
                db_url = os.environ.get("GRACE_DB_URL", "")
                state_root = os.environ.get("GRACE_STATE_ROOT", "/tmp/grace-eval")
                worker_env = {**os.environ,
                    "PYTHONDONTWRITEBYTECODE": "1",
                    "PYTHONPATH": f"{Path.cwd()}/src",
                    "GRACE_DB_URL": db_url,
                    "GRACE_TARGET_REPO_ROOT": str(Path.cwd()),
                    "GRACE_STATE_ROOT": state_root,
                    "GRACE_WORKTREE_ROOT": f"{state_root}/worktrees",
                    "GRACE_ALLOW_SANDBOX_BYPASS": "true",
                }
                ctrl_root = str(Path.cwd())
                worker_proc = subprocess.Popen(
                    [sys.executable, "-c", f"""
import os, sys, asyncio
sys.path.insert(0, "{ctrl_root}/src")
os.environ["GRACE_ALLOW_SANDBOX_BYPASS"] = "true"
from grace_control.db import init_db
from grace_control.worker.worker import Worker
init_db()
w = Worker(worker_id="self-w0", api_url="http://localhost:8042")
async def m(): await w.start()
asyncio.run(m())
"""],
                    env=worker_env,
                )
                _log.info("evolution_worker_spawned", session_id=session_id, pid=worker_proc.pid)
        except Exception as e:
            _log.warn("evolution_worker_spawn_failed", session_id=session_id, error=str(e)[:200])

        # ── Wait for execution completion ──
        packet_ids = result["data"].get("packets", [])
        terminal_states = frozenset(("merged", "failed", "rejected", "blocked", "cancelled"))
        deadline = time.time() + 1800  # 30 min max
        all_merged = False

        while time.time() < deadline:
            await asyncio.sleep(5)
            states: dict[str, str] = {}
            try:
                from grace_control.db import get_db as _gdb
                from grace_control.db.schema import Packet as _Pkt
                with _gdb() as db:
                    for pid in packet_ids:
                        p = db.query(_Pkt).filter_by(id=pid).first()
                        if p:
                            states[pid] = p.state
            except Exception:
                continue

            if not states:
                continue

            if all(s in terminal_states for s in states.values()):
                all_merged = all(s == "merged" for s in states.values())
                break

        with get_db() as db:
            s = db.query(SelfEvolutionSession).filter_by(id=session_id).first()
            if s:
                s.status = "completed" if all_merged else "executed"

        if all_merged:
            _log.info("evolution_completed", session_id=session_id, packets=len(packet_ids))
            await broadcast_event("self_evolution_update", {"session_id": session_id, "status": "completed"})

            # ── Hot-reload uvicorn after self-evolution merge ──
            from grace_control.core.self_reload import GraceSelfReloader
            reloader = GraceSelfReloader()
            reload_result = await reloader.reload_after_merge(session_id)
            _log.info("evolution_reload", session_id=session_id,
                success=reload_result.success, message=reload_result.message)
        else:
            _log.warn("evolution_completed_with_failures", session_id=session_id,
                states={pid: s for pid, s in states.items() if s != "merged"})
            await broadcast_event("self_evolution_update", {"session_id": session_id, "status": "executed"})

        # ── Clean up worker subprocess ──
        if worker_proc:
            try:
                worker_proc.terminate()
                worker_proc.wait(timeout=5)
            except Exception:
                try:
                    worker_proc.kill()
                except Exception:
                    pass

    except Exception as e:
        with get_db() as db:
            s = db.query(SelfEvolutionSession).filter_by(id=session_id).first()
            if s:
                s.status = "failed"
                s.error = str(e)[:500]
        _log.error("evolution_failed", session_id=session_id, error=str(e)[:200])
        await broadcast_event("self_evolution_update", {"session_id": session_id, "status": "failed"})


def _build_feature_spec(title: str, desc: str, scope: list[str], profile: str, session_id: str) -> dict:
    packets = []
    for i, filepath in enumerate(scope, 1):
        action = f"modify-{filepath.replace('/', '-').replace('.py', '').replace('_', '-')}"
        packets.append({
            "title": action,
            "scope": [filepath],
            "acceptance_profile": profile,
            "description": f"Self-evolution: {desc[:200]}",
        })

    return {
        "title": title,
        "description": desc,
        "waves": [{
            "title": "Self-Evolution",
            "packets": packets,
        }],
    }


def _context_to_dict(ctx: CodebaseContext) -> dict:
    return {
        "summary": ctx.summary,
        "estimated_scope": ctx.estimated_scope,
        "affected_contracts": ctx.affected_contracts,
        "complexity_score": ctx.complexity_score,
        "file_count": len(ctx.files),
        "files": [{"path": f.path, "size_lines": f.size_lines, "exports": f.exports[:10],
                   "content_preview": f.content_preview, "relevant": f.relevant}
                  for f in ctx.files[:50]],
    }


def _serialize_session(s: SelfEvolutionSession) -> dict:
    return {
        "id": s.id,
        "title": s.title,
        "description": s.description,
        "status": s.status,
        "feature_id": s.feature_id,
        "context": s.context_json,
        "constraints": s.constraints_json,
        "created_at": s.created_at.isoformat() + "Z" if s.created_at else None,
        "updated_at": s.updated_at.isoformat() + "Z" if s.updated_at else None,
        "finished_at": s.finished_at.isoformat() + "Z" if s.finished_at else None,
        "error": s.error,
    }
