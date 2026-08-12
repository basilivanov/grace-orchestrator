# ############################################################################
# AI_HEADER: worker_read_service — lifecycle worker snapshot projection
# ROLE: Owns the Worker ORM read used by lifecycle health and status views.
#      The database context factory is injectable so the projection is testable
#      without coupling the HTTP router to SQLAlchemy.
# ############################################################################

# START_MODULE_CONTRACT
# purpose: Read and serialize registered Worker rows for lifecycle snapshots.
# inputs: Optional DB context factory returning a context manager with a query
#          method; defaults to the canonical grace_control.db.get_db boundary.
# returns: List of worker dictionaries with the historical lifecycle keys.
# side_effects: Reads the workers table; does not mutate database state.
# emitted_logs: None.
# error_behavior: Database/context errors propagate to the lifecycle caller.
# END_MODULE_CONTRACT

# START_MODULE_MAP
# mapping:
#   - class: WorkerReadService
#     methods:
#       - __init__
#       - snapshot
# END_MODULE_MAP

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from grace_control.core.structured_logger import GraceLogger
from grace_control.db import get_db
from grace_control.db.schema import Worker

_log = GraceLogger("worker_read_service")


# START_BLOCK_WORKER_READ_SERVICE
class WorkerReadService:
    # START_FUNCTION_CONTRACT
    # name: __init__
    # purpose: Bind the worker projection to an explicit database context
    #          factory.
    # inputs: db_context_factory — callable returning a DB context manager.
    # returns: None.
    # side_effects: None.
    # error_behavior: Uses canonical get_db when no factory is provided.
    # END_FUNCTION_CONTRACT
    def __init__(self, db_context_factory: Callable[[], Any] = get_db) -> None:
        self._db_context_factory = db_context_factory

    # START_FUNCTION_CONTRACT
    # name: snapshot
    # purpose: Project registered Worker rows into the lifecycle response shape.
    # inputs: None.
    # returns: Worker dictionaries with ids, status, packet, heartbeat, and
    #          started timestamps.
    # side_effects: Reads Worker rows from the configured DB context.
    # emitted_logs: None.
    # error_behavior: Database errors propagate unchanged.
    # END_FUNCTION_CONTRACT
    def snapshot(self) -> list[dict[str, Any]]:
        with self._db_context_factory() as db:
            rows = db.query(Worker).all()
            return [
                {
                    "worker_id": worker.id,
                    "status": worker.status,
                    "current_packet_id": worker.current_packet_id,
                    "last_heartbeat": _timestamp(worker.last_heartbeat),
                    "started_at": _timestamp(worker.started_at),
                }
                for worker in rows
            ]


# START_FUNCTION_CONTRACT
# name: _timestamp
# purpose: Preserve the lifecycle router's historical timestamp/null encoding.
# inputs: value — datetime-like value or None.
# returns: ISO timestamp with a trailing Z, or None.
# side_effects: None.
# emitted_logs: None.
# error_behavior: Assumes a datetime-like value exposes isoformat().
# END_FUNCTION_CONTRACT
def _timestamp(value: Any) -> str | None:
    return value.isoformat() + "Z" if value else None


# END_BLOCK_WORKER_READ_SERVICE
