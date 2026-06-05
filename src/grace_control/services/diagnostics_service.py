"""DiagnosticsService — system-state snapshot for /api/diagnostics/state."""

from __future__ import annotations

from typing import Any

from sqlalchemy.orm import Session

from grace_control.db.schema import (
    Feature,
    Lease,
    Packet,
    PacketRun,
    PacketState,
    Worker,
)


class DiagnosticsService:
    """Aggregate counts and live-state snapshots for the diagnostics endpoint."""

    def get_state(self, db: Session) -> dict[str, Any]:
        """Counts by state + active leases + live workers."""
        by_state: dict[str, int] = {}
        for state in PacketState:
            by_state[state.value] = (
                db.query(Packet).filter(Packet.state == state.value).count()
            )
        # Leases are exclusive claim rows; "active" means expires_at in the
        # future. Released leases are deleted in the current schema, so
        # all rows here are by definition active.
        from datetime import datetime
        active_leases = (
            db.query(Lease)
            .filter(Lease.expires_at > datetime.utcnow())
            .count()
        )
        workers_total = db.query(Worker).count()
        workers_idle = db.query(Worker).filter_by(status="idle").count()
        workers_busy = db.query(Worker).filter_by(status="busy").count()
        runs_total = db.query(PacketRun).count()
        features_by_status: dict[str, int] = {}
        for f in db.query(Feature).all():
            features_by_status[f.status] = features_by_status.get(f.status, 0) + 1
        return {
            "packets_by_state": by_state,
            "active_leases": active_leases,
            "workers": {
                "total": workers_total,
                "idle": workers_idle,
                "busy": workers_busy,
            },
            "runs_total": runs_total,
            "features_by_status": features_by_status,
        }
