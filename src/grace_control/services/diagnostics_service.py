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

from grace_control.config.settings import get_parallel_runtime_config
from grace_control.db.schema import (
    Event,
    Feature,
    Lease,
    MergeLease,
    Packet,
    PacketRun,
    PacketState,
    Worker,
)
from grace_control.services.parallel_lease_service import ParallelLeaseService


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
        active_workers = db.query(Worker).filter(Worker.status.in_(["active", "busy"])).count()
        workers_idle = db.query(Worker).filter_by(status="idle").count()
        workers_busy = db.query(Worker).filter_by(status="busy").count()
        runs_total = db.query(PacketRun).count()
        features_by_status: dict[str, int] = {}
        for f in db.query(Feature).all():
            features_by_status[f.status] = features_by_status.get(f.status, 0) + 1
        now = datetime.now(UTC)
        parallel_leases = ParallelLeaseService().active_leases(db, now=now)
        active_parallel_leases = [
            {
                "lease_id": lease.id,
                "packet_id": lease.packet_id,
                "feature_id": lease.feature_id,
                "wave_id": lease.wave_id,
                "worker_id": lease.worker_id,
                "claimed_attempt": lease.claimed_attempt,
                "base_sha": lease.base_sha,
                "expires_at": lease.expires_at.isoformat() if lease.expires_at else None,
                "heartbeat_at": lease.heartbeat_at.isoformat() if lease.heartbeat_at else None,
            }
            for lease in parallel_leases
        ]
        merge_leases = (
            db.query(MergeLease)
            .filter(MergeLease.expires_at > now)
            .order_by(MergeLease.target_repo_key.asc())
            .all()
        )
        active_merge_leases = [
            {
                "target_repo_key": lease.target_repo_key,
                "packet_id": lease.packet_id,
                "worker_id": lease.worker_id,
                "expires_at": lease.expires_at.isoformat() if lease.expires_at else None,
                "heartbeat_at": lease.heartbeat_at.isoformat() if lease.heartbeat_at else None,
            }
            for lease in merge_leases
        ]
        active_merge_lease_holder = active_merge_leases[0] if active_merge_leases else None
        packet_parallel = []
        for packet in db.query(Packet).filter(
            Packet.state.in_([PacketState.RUNNING.value, PacketState.ACCEPTED.value, PacketState.READY.value])
        ).all():
            run = (
                db.query(PacketRun)
                .filter_by(packet_id=packet.id)
                .order_by(PacketRun.run_number.desc())
                .first()
            )
            result_json = run.result_json if run and isinstance(run.result_json, dict) else {}
            parallel = result_json.get("parallel_execution")
            parallel = parallel if isinstance(parallel, dict) else {}
            wait_reason = None
            if packet.state in {PacketState.READY.value, PacketState.ACCEPTED.value}:
                event = (
                    db.query(Event)
                    .filter(
                        Event.event_type == "packet_wait",
                        Event.entity_type == "packet",
                        Event.entity_id == packet.id,
                    )
                    .order_by(Event.timestamp.desc(), Event.id.desc())
                    .first()
                )
                if event and isinstance(event.payload_json, dict):
                    wait_reason = event.payload_json.get("reason")
            packet_parallel.append({
                "packet_id": packet.id,
                "state": packet.state,
                "base_sha": run.base_sha if run else None,
                "integration_base_sha": run.integration_base_sha if run else None,
                "current_wait_reason": wait_reason,
                "integration_recheck": parallel.get("integration_recheck"),
            })
        runtime_config = get_parallel_runtime_config()
        return {
            "packets_by_state": by_state,
            "active_leases": active_leases,
            "workers": {
                "total": workers_total,
                "idle": workers_idle,
                "busy": workers_busy,
                "active": active_workers,
            },
            "effective_max_concurrency": runtime_config["max_concurrency"],
            "active_workers": active_workers,
            "active_parallel_leases": active_parallel_leases,
            "active_parallel_lease_count": len(active_parallel_leases),
            "active_merge_lease_holder": active_merge_lease_holder,
            "active_merge_leases": active_merge_leases,
            "packet_parallel": packet_parallel,
            "runs_total": runs_total,
            "features_by_status": features_by_status,
        }
