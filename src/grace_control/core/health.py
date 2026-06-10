# ############################################################################
# AI_HEADER: health
# ROLE: System health check + dead worker cleanup for GRACE Control Plane.
# ############################################################################

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from grace_control.db import get_db
from grace_control.db.schema import Lease, Packet, PacketState, Worker


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
                and (datetime.now(UTC) - datetime.fromisoformat(w["heartbeat"].rstrip("Z")) > timedelta(minutes=1))]

        # Clean up dead workers: release their packets back to READY
        for dw in dead:
            try:
                pkt_id = dw["packet"]
                if pkt_id:
                    packet = db.query(Packet).filter_by(
                        id=pkt_id, state=PacketState.RUNNING.value
                    ).first()
                    if packet:
                        packet.state = PacketState.READY.value
                    worker = db.query(Worker).filter_by(id=dw["id"]).first()
                    if worker:
                        worker.status = "dead"
                        worker.current_packet_id = None
                    db.query(Lease).filter_by(packet_id=pkt_id).delete()
            except Exception:
                pass
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
        "timestamp": datetime.now(UTC).isoformat() + "Z",
    }
