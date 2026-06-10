# ############################################################################
# AI_HEADER: workers_router
# ROLE: FastAPI router for /api/workers/ endpoints.
# ############################################################################

from __future__ import annotations

from datetime import UTC, datetime

from fastapi import APIRouter, HTTPException

from grace_control.db import get_db
from grace_control.db.schema import Worker

router = APIRouter()


@router.get("/")
async def list_workers() -> dict:
    with get_db() as db:
        workers = db.query(Worker).all()
        return {
            "data": [
                {
                    "id": w.id,
                    "status": w.status,
                    "current_packet_id": w.current_packet_id,
                    "last_heartbeat": w.last_heartbeat.isoformat() + "Z" if w.last_heartbeat else None,
                    "started_at": w.started_at.isoformat() + "Z",
                }
                for w in workers
            ],
            "timestamp": datetime.now(UTC).isoformat() + "Z",
        }


@router.post("/register")
async def register_worker(request: dict) -> dict:
    worker_id = request["worker_id"]
    with get_db() as db:
        existing = db.query(Worker).filter_by(id=worker_id).first()
        if existing:
            existing.status = "active"
            existing.last_heartbeat = datetime.now(UTC)
        else:
            db.add(Worker(id=worker_id, status="active", last_heartbeat=datetime.now(UTC)))
        return {"data": {"worker_id": worker_id, "status": "registered"}, "timestamp": datetime.now(UTC).isoformat() + "Z"}


@router.post("/heartbeat")
async def worker_heartbeat(request: dict) -> dict:
    worker_id = request["worker_id"]
    with get_db() as db:
        w = db.query(Worker).filter_by(id=worker_id).first()
        if not w:
            raise HTTPException(status_code=404, detail="Worker not found")
        w.last_heartbeat = datetime.now(UTC)
        w.status = "active"
        return {"data": {"worker_id": worker_id, "status": "ok", "timestamp": datetime.now(UTC).isoformat() + "Z"}}
