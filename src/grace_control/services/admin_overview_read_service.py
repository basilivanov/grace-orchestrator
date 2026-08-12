# ############################################################################
# AI_HEADER: admin_overview_read_service — overview and runtime health reads
# ROLE: Owns the aggregate overview, worker listing and system-health reads
#       used by the admin facade. It only composes read-only ORM and runtime
#       metadata and keeps the existing overview DTOs stable.
# ############################################################################

# START_MODULE_CONTRACT
# purpose: Build overview, worker and system-health DTOs for the admin UI.
# inputs: SQLAlchemy Session for database reads and local runtime environment.
# returns: Plain dictionaries with the existing admin overview shapes.
# side_effects: Reads database rows, an optional supervisor JSON file and git
#               metadata; never mutates project state.
# emitted_logs: None.
# error_behavior: Overview falls back to an empty safe DTO; health metadata
#                 silently falls back to its default values.
# END_MODULE_CONTRACT

# START_MODULE_MAP
# mapping:
#   - class: AdminOverviewReadService
#     methods:
#       - get_overview
#       - get_system_health
#       - get_workers
# END_MODULE_MAP

from __future__ import annotations

import json
from datetime import UTC, datetime
from os import environ
from pathlib import Path
from typing import Any

from sqlalchemy.orm import Session

from grace_control.core.structured_logger import GraceLogger
from grace_control.db.schema import Event, Feature, Packet, Wave, Worker
from grace_control.services.admin_read_models import ProjectHealthSnapshot, WorkerSnapshot
from grace_control.services.git_service import GitService

_log = GraceLogger("admin_overview_read")


# START_BLOCK_CONSTANTS
_PACKET_STATES = [
    "draft", "ready", "running", "accepted", "merged",
    "rejected", "failed", "blocked", "blocked_recoverable", "blocked_final",
    "cancelled",
]
# END_BLOCK_CONSTANTS


# START_BLOCK_HELPERS
def _iso(dt: datetime | None) -> str | None:
    if dt is None:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=UTC)
    return dt.isoformat().replace("+00:00", "Z")


def _now() -> datetime:
    return datetime.now(UTC)


def _elapsed_seconds(started_at: datetime | None, finished_at: datetime | None) -> int | None:
    if started_at is None:
        return None
    end = finished_at or _now()
    if started_at.tzinfo is None:
        started_at = started_at.replace(tzinfo=UTC)
    if end.tzinfo is None:
        end = end.replace(tzinfo=UTC)
    return max(0, int((end - started_at).total_seconds()))


def _is_running(
    status: str | None,
    started_at: datetime | None,
    finished_at: datetime | None,
) -> bool:
    if status and status not in (
        "completed", "accepted", "merged", "rejected", "failed", "blocked", "cancelled",
    ):
        return True
    if started_at is not None and finished_at is None and status in (None, "running", ""):
        return True
    return False


def _packet_state(packet: Any) -> str:
    return str(packet.state)


# END_BLOCK_HELPERS


# START_BLOCK_SERVICE
class AdminOverviewReadService:
    """Read-only owner for the admin overview and runtime health DTOs."""

    # START_FUNCTION_CONTRACT
    # name: __init__
    # purpose: Configure the stateless overview reader.
    # inputs: None.
    # returns: None.
    # side_effects: None.
    # emitted_logs: None.
    # error_behavior: Never raises.
    # END_FUNCTION_CONTRACT
    def __init__(self) -> None:
        pass

    # START_FUNCTION_CONTRACT
    # name: get_overview
    # purpose: Return packet/feature/wave counts, recent events, blocked
    #          packets, workers and runtime health for the admin overview.
    # inputs: db — active SQLAlchemy Session.
    # returns: Existing overview DTO dictionary.
    # side_effects: Reads ORM rows only.
    # emitted_logs: None.
    # error_behavior: Returns a safe empty overview if a read fails.
    # END_FUNCTION_CONTRACT
    def get_overview(self, db: Session) -> dict[str, Any]:
        try:
            state_counts: dict[str, int] = dict.fromkeys(_PACKET_STATES, 0)
            for row in db.query(Packet.state, Packet.id).all():
                state = row.state or "draft"
                state_counts[state] = state_counts.get(state, 0) + 1

            total_features = db.query(Feature).count()
            total_waves = db.query(Wave).count()
            total_packets = db.query(Packet).count()
            recent_events_rows = (
                db.query(Event)
                .order_by(Event.timestamp.desc())
                .limit(20)
                .all()
            )
            recent_events = [
                {
                    "id": event.id,
                    "timestamp": _iso(event.timestamp),
                    "event_type": event.event_type,
                    "entity_type": event.entity_type,
                    "entity_id": event.entity_id,
                    "reason": (event.payload_json or {}).get("reason", ""),
                    "trace_id": event.trace_id or "",
                }
                for event in recent_events_rows
            ]
            blocked_rows = (
                db.query(Packet)
                .filter(Packet.state.in_(["blocked", "blocked_recoverable", "blocked_final"]))
                .limit(50)
                .all()
            )
            blocked = [
                {
                    "id": packet.id,
                    "title": packet.title,
                    "state": _packet_state(packet),
                    "attempt_count": packet.attempt_count,
                    "max_attempts": packet.max_attempts,
                    "updated_at": _iso(packet.updated_at),
                }
                for packet in blocked_rows
            ]
            workers = [self._worker_to_dict(worker) for worker in db.query(Worker).all()]
            return {
                "stats": {
                    "features": total_features,
                    "waves": total_waves,
                    "packets": total_packets,
                    "by_state": state_counts,
                    "workers": len([worker for worker in workers if worker["status"] == "active"]),
                },
                "health": self.get_system_health(),
                "recent_events": recent_events,
                "blocked": blocked,
                "workers": workers,
                "fetched_at": _iso(_now()),
            }
        except Exception:
            return {
                "stats": {"by_state": dict.fromkeys(_PACKET_STATES, 0), "workers": 0},
                "health": self.get_system_health(),
                "recent_events": [],
                "blocked": [],
                "workers": [],
                "fetched_at": _iso(_now()),
            }

    # START_FUNCTION_CONTRACT
    # name: get_system_health
    # purpose: Read supervisor liveness, worker count and current code SHA.
    # inputs: None; reads the configured GRACE_TARGET_DIR when present.
    # returns: Existing system-health DTO dictionary.
    # side_effects: Reads supervisor.json and invokes git read-only metadata.
    # emitted_logs: None.
    # error_behavior: Missing/unreadable metadata leaves safe defaults intact.
    # END_FUNCTION_CONTRACT
    def get_system_health(self) -> dict[str, Any]:
        supervisor_alive = False
        workers_alive = 0
        code_sha = ""
        target = environ.get("GRACE_TARGET_DIR", "")
        if target:
            state_path = Path(target) / "supervisor.json"
            if state_path.exists():
                try:
                    state = json.loads(state_path.read_text())
                    supervisor_alive = True
                    workers_alive = (
                        len(state.get("workers", []))
                        if isinstance(state.get("workers"), list)
                        else 0
                    )
                except Exception:
                    pass
        try:
            result = GitService()._run(
                ["rev-parse", "--short", "HEAD"],
                Path.cwd(),
                timeout=2,
            )
            if result.success:
                code_sha = result.stdout.strip()
        except Exception:
            pass
        return ProjectHealthSnapshot(
            supervisor_alive=supervisor_alive,
            api_alive=True,
            workers_alive=workers_alive,
            db_ok=True,
            code_sha=code_sha,
            version="0.1.0",
        ).to_dict()

    # START_FUNCTION_CONTRACT
    # name: get_workers
    # purpose: Return the current worker rows in the admin worker-list DTO.
    # inputs: db — active SQLAlchemy Session.
    # returns: Dictionary with a workers list.
    # side_effects: Reads Worker rows only.
    # emitted_logs: None.
    # error_behavior: Propagates no service-level errors beyond SQLAlchemy.
    # END_FUNCTION_CONTRACT
    def get_workers(self, db: Session) -> dict[str, Any]:
        return {"workers": [self._worker_to_dict(worker) for worker in db.query(Worker).all()]}

    # START_FUNCTION_CONTRACT
    # name: _worker_to_dict
    # purpose: Serialize one Worker row with the legacy elapsed-time fields.
    # inputs: worker — Worker ORM row.
    # returns: Worker DTO dictionary.
    # side_effects: None.
    # emitted_logs: None.
    # error_behavior: Never raises for a mapped row.
    # END_FUNCTION_CONTRACT
    @staticmethod
    def _worker_to_dict(worker: Worker) -> dict[str, Any]:
        return WorkerSnapshot(
            id=worker.id,
            status=worker.status,
            current_packet_id=worker.current_packet_id,
            last_heartbeat=_iso(worker.last_heartbeat),
            started_at=_iso(worker.started_at),
            current_elapsed=_elapsed_seconds(worker.last_heartbeat, None),
        ).to_dict()


# END_BLOCK_SERVICE
