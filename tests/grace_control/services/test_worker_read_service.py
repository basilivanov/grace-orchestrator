# ############################################################################
# AI_HEADER: test_worker_read_service — Worker projection acceptance tests
# ROLE: Locks the lifecycle worker DTO keys and historical timestamp/null
#      representation behind an injected database context.
# ############################################################################

# START_MODULE_CONTRACT
# purpose: Verify WorkerReadService projects one fake Worker query exactly as
#          the former lifecycle router helper did.
# inputs: In-memory fake DB context and simple worker records.
# returns: Pytest assertions.
# side_effects: No real database access.
# emitted_logs: None.
# error_behavior: Fails when projection keys or timestamp encoding change.
# END_MODULE_CONTRACT

# START_MODULE_MAP
# mapping:
#   - function: test_worker_projection_and_timestamps
# END_MODULE_MAP

from __future__ import annotations

from contextlib import contextmanager
from datetime import datetime
from typing import Any

from grace_control.core.structured_logger import GraceLogger
from grace_control.services.worker_read_service import WorkerReadService

_log = GraceLogger("test_worker_read_service")


# START_BLOCK_WORKER_READ_SERVICE_TESTS
# START_FUNCTION_CONTRACT
# name: test_worker_projection_and_timestamps
# purpose: Verify exact worker projection keys and timestamp/null behavior.
# inputs: None; uses an injected fake context factory.
# returns: None.
# side_effects: Reads only fake in-memory records.
# emitted_logs: None.
# error_behavior: AssertionError when the lifecycle projection drifts.
# END_FUNCTION_CONTRACT
def test_worker_projection_and_timestamps() -> None:
    row = type(
        "WorkerRow",
        (),
        {
            "id": "worker-1",
            "status": "active",
            "current_packet_id": None,
            "last_heartbeat": datetime(2026, 1, 2, 3, 4, 5),
            "started_at": None,
        },
    )()

    class FakeDB:
        def query(self, model: Any) -> FakeDB:
            assert model.__name__ == "Worker"
            return self

        def all(self) -> list[Any]:
            return [row]

    @contextmanager
    def context_factory():
        yield FakeDB()

    assert WorkerReadService(context_factory).snapshot() == [
        {
            "worker_id": "worker-1",
            "status": "active",
            "current_packet_id": None,
            "last_heartbeat": "2026-01-02T03:04:05Z",
            "started_at": None,
        }
    ]


# END_BLOCK_WORKER_READ_SERVICE_TESTS
