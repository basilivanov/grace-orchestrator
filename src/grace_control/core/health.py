# ############################################################################
# AI_HEADER: health
# ROLE: System health check for GRACE Control Plane.
# ############################################################################

from __future__ import annotations

from datetime import datetime, timedelta

from grace_control.db import get_db
from grace_control.db.schema import Packet, PacketState, Worker


async def check_health() -> dict:
    with get_db() as db:
        workers = db.query(Worker).all()
        worker_data = [
            {"id": w.id, "status": w.status, "packet": w.current_packet_id,
             "heartbeat": w.last_heartbeat.isoformat() + "Z" if w.last_heartbeat else None}
            for w in workers
        ]
        active = [w for w in worker_data if w["status"] == "active"]
        dead = [w for w in worker_data
                if w["heartbeat"] and w["status"] == "active"
                and (datetime.utcnow() - datetime.fromisoformat(w["heartbeat"].rstrip("Z")) > timedelta(minutes=5))]
        ready = db.query(Packet).filter_by(state=PacketState.READY.value).count()
        running = db.query(Packet).filter_by(state=PacketState.RUNNING.value).count()

    status = "healthy"
    if dead:
        status = "degraded"
    if not active:
        status = "unhealthy"

    return {
        "status": status,
        "workers": {"active": len(active), "idle": len([w for w in active if not w["packet"]]), "dead": len(dead)},
        "queue_depth": ready,
        "running": running,
        "timestamp": datetime.utcnow().isoformat() + "Z",
    }
