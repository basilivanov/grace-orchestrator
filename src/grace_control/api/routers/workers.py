# ############################################################################
# AI_HEADER: workers_router
# ROLE: FastAPI router for /api/workers/ endpoints.
# ############################################################################

from __future__ import annotations

from datetime import UTC, datetime

from fastapi import APIRouter, HTTPException

from grace_control.core.structured_logger import GraceLogger
from grace_control.db import get_db
from grace_control.db.schema import Worker

router = APIRouter()
_log = GraceLogger("workers_router")


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
    pid = request.get("pid")
    with get_db() as db:
        existing = db.query(Worker).filter_by(id=worker_id).first()
        if existing:
            existing.status = "active"
            existing.last_heartbeat = datetime.now(UTC)
            if pid:
                existing.pid = pid
        else:
            w = Worker(id=worker_id, status="active", last_heartbeat=datetime.now(UTC))
            if pid:
                w.pid = pid
            db.add(w)
        db.commit()
    _log.info("worker_registered", worker_id=worker_id, pid=pid)
    return {"data": {"worker_id": worker_id, "status": "registered", "pid": pid},
            "timestamp": datetime.now(UTC).isoformat() + "Z"}


@router.post("/heartbeat")
async def worker_heartbeat(request: dict) -> dict:
    worker_id = request["worker_id"]
    with get_db() as db:
        w = db.query(Worker).filter_by(id=worker_id).first()
        if not w:
            raise HTTPException(status_code=404, detail="Worker not found")
        w.last_heartbeat = datetime.now(UTC)
        w.status = "active"
        
        # Resolve lease expiration and current stage
        lease_expires_at = None
        current_stage_key = None
        if w.current_packet_id:
            from grace_control.db.schema import Lease, StageRun
            lease = db.query(Lease).filter_by(packet_id=w.current_packet_id, worker_id=worker_id).first()
            if lease:
                lease_expires_at = lease.expires_at.isoformat() + "Z" if lease.expires_at else None
            
            current_stage = db.query(StageRun).filter_by(
                packet_id=w.current_packet_id, status="running"
            ).order_by(StageRun.started_at.desc()).first()
            if current_stage:
                current_stage_key = current_stage.stage_key

        from grace_control.api.ws_broadcast import broadcast_worker_heartbeat
        import asyncio
        asyncio.create_task(broadcast_worker_heartbeat(
            worker_id=worker_id,
            current_packet_id=w.current_packet_id,
            current_stage_key=current_stage_key,
            last_heartbeat=w.last_heartbeat.isoformat() + "Z",
            lease_expires_at=lease_expires_at,
        ))
        
        return {"data": {"worker_id": worker_id, "status": "ok", "timestamp": datetime.now(UTC).isoformat() + "Z"}}
