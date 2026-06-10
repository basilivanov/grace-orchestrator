# ############################################################################
# AI_HEADER: diagnostics_service
# ROLE: System-state snapshot for /api/diagnostics/state. Aggregates packet
#       state counts, lease freshness, worker status, and feature progress.
# ############################################################################

# START_MODULE_CONTRACT
# purpose: Single place that computes the diagnostics snapshot. Routers do
#          not run their own count loops; new counters land here.
# inputs: Session.
# returns: dict — see `get_state` for the exact shape.
# side_effects: None.
# emitted_logs: None.
# error_behavior: Never raises.
# END_MODULE_CONTRACT

# START_MODULE_MAP
# mapping:
#   - class: DiagnosticsService
#     methods:
#       - get_state
# END_MODULE_MAP

from __future__ import annotations

from datetime import UTC, datetime
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

    # START_FUNCTION_CONTRACT
    # name: get_state
    # purpose: Build a compact system-state snapshot used by both the API
    #          and admin UIs.
    # inputs: db (Session).
    # returns: dict with keys:
    #   packets_by_state: {state_value: count} for every PacketState value
    #   active_leases: int — leases whose expires_at is in the future
    #   workers: {total, idle, busy}
    #   runs_total: int
    #   features_by_status: {status: count}
    # side_effects: None.
    # emitted_logs: None.
    # error_behavior: Never raises.
    # END_FUNCTION_CONTRACT
    def get_state(self, db: Session) -> dict[str, Any]:
        by_state: dict[str, int] = {}
        for state in PacketState:
            by_state[state.value] = (
                db.query(Packet).filter(Packet.state == state.value).count()
            )
        # Leases are exclusive claim rows; "active" means expires_at in
        # the future. Released leases are deleted in the current schema, so
        # all rows here are by definition active.
        active_leases = (
            db.query(Lease)
            .filter(Lease.expires_at > datetime.now(UTC))
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
