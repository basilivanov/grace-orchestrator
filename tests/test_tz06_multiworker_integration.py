# ############################################################################
# AI_HEADER: test_tz06_multiworker_integration — real multi-worker runtime proof
# ############################################################################

# START_MODULE_CONTRACT
# purpose: Prove the worker-facing API uses atomic safe claims, retains fenced
#          parallel leases through ACCEPTED, exposes runtime diagnostics, and
#          fails closed when multi-worker guards are disabled.
# inputs: File-backed SQLite databases, ASGI API clients, and real Worker loops.
# returns: Pytest acceptance results.
# side_effects: Creates temporary databases, packet rows, and concurrent tasks.
# emitted_logs: None.
# error_behavior: Assertions identify a TZ06 runtime integration regression.
# END_MODULE_CONTRACT

# START_MODULE_MAP
# mapping:
#   - class: SlowWorkerExecutor
#   - function: test_real_workers_overlap_on_disjoint_wave_packets
#   - function: test_parallel_mode_fails_closed_when_scope_guard_disabled
#   - function: test_accepted_packet_renews_parallel_lease
#   - function: test_diagnostics_surface_parallel_runtime_state
#   - function: test_cleanup_reclaims_crashed_accepted_packet
# END_MODULE_MAP

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace

import httpx
import pytest

from grace_control.adapters.packet_executor import ExecutionResult
from grace_control.api.main import app
from grace_control.config.settings import settings
from grace_control.core.structured_logger import GraceLogger
from grace_control.db import get_db
from grace_control.db.schema import Feature, Packet, PacketState, Wave
from grace_control.db.schema import Worker as DBWorker
from grace_control.services.parallel_lease_service import ParallelLeaseService
from grace_control.services.supervisor_cleanup_service import SupervisorCleanupService
from grace_control.worker.api_client import WorkerAPIClient
from grace_control.worker.worker import Worker

_log = GraceLogger("test_tz06_multiworker")


# START_BLOCK_HELPERS

# START_FUNCTION_CONTRACT
# name: _seed_wave
# purpose: Seed one active feature, one wave, workers, and disjoint READY packets.
# inputs: packet_count — number of packets; worker_count — worker rows to add.
# returns: None.
# side_effects: Inserts fixture rows into the active test database.
# emitted_logs: None.
# error_behavior: Propagates database errors.
# END_FUNCTION_CONTRACT
def _seed_wave(packet_count: int, worker_count: int) -> None:
    with get_db() as db:
        db.add(Feature(
            id="tz06-feature",
            slug="tz06-feature",
            title="TZ06 feature",
            spec_json={},
            status="active",
        ))
        db.add(Wave(
            id="tz06-wave",
            feature_id="tz06-feature",
            slug="tz06-wave",
            title="TZ06 wave",
            order=1,
            status="IN_PROGRESS",
        ))
        for index in range(worker_count):
            db.add(DBWorker(id=f"tz06-worker-{index}", status="idle"))
        for index in range(packet_count):
            packet_id = f"tz06-packet-{index}"
            db.add(Packet(
                id=packet_id,
                feature_id="tz06-feature",
                wave_id="tz06-wave",
                slug=packet_id,
                title=packet_id,
                spec_json={
                    "scope": [f"src/tz06/{index}.py"],
                    "conflict_keys": [],
                    "depends_on": [],
                },
                state=PacketState.READY.value,
                attempt_count=0,
                max_attempts=3,
            ))


@dataclass
class SlowWorkerExecutor:
    """Artificially slow coder seam used only to expose execution overlap."""

    delay_seconds: float = 0.08
    intervals: list[tuple[str, float, float]] = field(default_factory=list)

    # START_FUNCTION_CONTRACT
    # name: execute
    # purpose: Hold one claimed packet in execution long enough for peers to
    #          claim and execute independently.
    # inputs: packet_id, worker_id, claim_data.
    # returns: Recoverable blocked result after the slow execution interval.
    # side_effects: Records monotonic start/end timestamps in memory.
    # emitted_logs: None.
    # error_behavior: None for valid claim data.
    # END_FUNCTION_CONTRACT
    async def execute(self, packet_id: str, worker_id: str, claim_data: dict) -> ExecutionResult:
        del claim_data
        started = asyncio.get_running_loop().time()
        await asyncio.sleep(self.delay_seconds)
        finished = asyncio.get_running_loop().time()
        self.intervals.append((worker_id, started, finished))
        return ExecutionResult(
            accepted=False,
            domain_status="blocked",
            reason="tz06_slow_smoke_complete",
            duration_ms=int((finished - started) * 1000),
        )


# START_FUNCTION_CONTRACT
# name: _worker
# purpose: Build a real Worker loop with an ASGI-backed WorkerAPIClient and a
#          slow executor, while keeping one packet per worker task.
# inputs: worker_id, executor — worker identity and execution seam.
# returns: Worker instance ready for one cycle.
# side_effects: Creates an HTTP client bound to the real FastAPI app.
# emitted_logs: None.
# error_behavior: None for valid identifiers.
# END_FUNCTION_CONTRACT
async def _worker(worker_id: str, executor: SlowWorkerExecutor) -> Worker:
    client = WorkerAPIClient("http://tz06.test")
    await client.client.aclose()
    client.client = httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url="http://tz06.test",
    )
    worker = Worker.__new__(Worker)
    worker.worker_id = worker_id
    worker.api = client
    worker.executor = executor
    worker.running = True
    worker.log = _log
    worker._git_context = SimpleNamespace(target_repo_root=Path.cwd())
    worker._active_packet_id = None
    worker._active_lease_id = None
    worker._active_claimed_attempt = None
    worker._active_parallel_lease_id = None
    worker._active_lease_released = False
    worker._active_lease_loss_reason = ""
    return worker


# END_BLOCK_HELPERS


# START_BLOCK_TESTS

# START_FUNCTION_CONTRACT
# name: test_real_workers_overlap_on_disjoint_wave_packets
# purpose: Prove four real Worker cycles claim and execute disjoint same-wave
#          packets concurrently through the file-backed API claim path.
# inputs: api — isolated ASGI client fixture; tmp_path — test database root.
# returns: None.
# side_effects: Runs concurrent worker tasks and writes packet/lease state.
# emitted_logs: None.
# error_behavior: Assertion failure on missing overlap or duplicate claims.
# END_FUNCTION_CONTRACT
@pytest.mark.asyncio
async def test_real_workers_overlap_on_disjoint_wave_packets(api, tmp_path: Path, monkeypatch):
    del api, tmp_path
    monkeypatch.setenv("GRACE_MAX_CONCURRENCY", "4")
    _seed_wave(packet_count=4, worker_count=4)
    executor = SlowWorkerExecutor()
    workers = [
        await _worker(f"tz06-worker-{index}", executor)
        for index in range(4)
    ]
    try:
        await asyncio.gather(*(worker._run_one_cycle(1) for worker in workers))
    finally:
        await asyncio.gather(*(worker.api.close() for worker in workers))

    assert len(executor.intervals) == 4
    ordered = sorted(executor.intervals, key=lambda item: item[1])
    assert any(
        left[1] < right[1] < left[2]
        for left, right in zip(ordered, ordered[1:], strict=True)
    )
    with get_db() as db:
        assert db.query(Packet).filter_by(state=PacketState.BLOCKED_RECOVERABLE.value).count() == 4


# START_FUNCTION_CONTRACT
# name: test_parallel_mode_fails_closed_when_scope_guard_disabled
# purpose: Prove max concurrency cannot silently select the legacy unsafe claim
#          path when the required scope guard is disabled.
# inputs: api — isolated ASGI client fixture; monkeypatch — runtime overrides.
# returns: None.
# side_effects: Performs one rejected API claim request.
# emitted_logs: None.
# error_behavior: Assertion failure if unsafe mode is accepted.
# END_FUNCTION_CONTRACT
@pytest.mark.asyncio
async def test_parallel_mode_fails_closed_when_scope_guard_disabled(api, monkeypatch):
    monkeypatch.setenv("GRACE_MAX_CONCURRENCY", "4")
    monkeypatch.setattr(settings, "parallel_scope_guard_enabled", False)
    response = await api.post("/api/packets/claim", json={"worker_id": "tz06-unsafe"})
    assert response.status_code == 503
    assert response.json()["detail"].startswith("parallel_safety_disabled:")


# START_FUNCTION_CONTRACT
# name: test_accepted_packet_renews_parallel_lease
# purpose: Prove the worker-facing API retains and renews the parallel lease
#          after ordinary RUNNING ownership is released as ACCEPTED.
# inputs: api — isolated ASGI client fixture; monkeypatch — concurrency setting.
# returns: None.
# side_effects: Claims, accepts, and renews one packet lease.
# emitted_logs: None.
# error_behavior: Assertion failure on missing retained lease renewal.
# END_FUNCTION_CONTRACT
@pytest.mark.asyncio
async def test_accepted_packet_renews_parallel_lease(api, monkeypatch):
    monkeypatch.setenv("GRACE_MAX_CONCURRENCY", "4")
    _seed_wave(packet_count=1, worker_count=1)
    claim_response = await api.post(
        "/api/packets/claim",
        json={"worker_id": "tz06-worker-0"},
    )
    assert claim_response.status_code == 200
    claim = claim_response.json()["data"]
    release_response = await api.post(
        f"/api/packets/{claim['packet_id']}/release",
        json={
            "worker_id": "tz06-worker-0",
            "lease_id": claim["lease_id"],
            "claimed_attempt": claim["claimed_attempt"],
            "status": "accepted",
            "result": {"accepted": True},
        },
    )
    assert release_response.status_code == 200
    renew_response = await api.post(
        f"/api/packets/{claim['packet_id']}/renew-parallel-lease",
        json={
            "worker_id": "tz06-worker-0",
            "parallel_lease_id": claim["parallel_lease_id"],
            "claimed_attempt": claim["claimed_attempt"],
        },
    )
    assert renew_response.status_code == 200
    assert renew_response.json()["data"]["renewed"] is True


# START_FUNCTION_CONTRACT
# name: test_diagnostics_surface_parallel_runtime_state
# purpose: Prove the diagnostics API exposes effective concurrency, active
#          workers/parallel leases, and packet base/recheck read models.
# inputs: api — isolated ASGI client fixture; monkeypatch — concurrency setting.
# returns: None.
# side_effects: Claims one packet and reads the diagnostics endpoint.
# emitted_logs: None.
# error_behavior: Assertion failure on missing operational fields.
# END_FUNCTION_CONTRACT
@pytest.mark.asyncio
async def test_diagnostics_surface_parallel_runtime_state(api, monkeypatch):
    monkeypatch.setenv("GRACE_MAX_CONCURRENCY", "4")
    _seed_wave(packet_count=1, worker_count=1)
    claim_response = await api.post(
        "/api/packets/claim",
        json={"worker_id": "tz06-worker-0"},
    )
    assert claim_response.status_code == 200
    diagnostics = await api.get("/api/diagnostics/state")
    assert diagnostics.status_code == 200
    data = diagnostics.json()["data"]
    assert data["effective_max_concurrency"] == 4
    assert data["active_workers"] == 1
    assert data["active_parallel_lease_count"] == 1
    assert data["active_parallel_leases"][0]["packet_id"] == "tz06-packet-0"


# START_FUNCTION_CONTRACT
# name: test_cleanup_reclaims_crashed_accepted_packet
# purpose: Prove stale cleanup fences an ACCEPTED packet whose worker died
#          after ordinary release and before serialized merge.
# inputs: api — isolated file-backed database; tmp_path — cleanup roots.
# returns: None on success.
# side_effects: Inserts an expired parallel lease and runs cleanup recovery.
# emitted_logs: None.
# error_behavior: Assertion failure if stale accepted ownership survives.
# END_FUNCTION_CONTRACT
def test_cleanup_reclaims_crashed_accepted_packet(api, tmp_path: Path):
    del api
    packet_id = "tz06-crashed-accepted"
    with get_db() as db:
        db.add(Packet(
            id=packet_id,
            feature_id="tz06-feature",
            wave_id="tz06-wave",
            slug=packet_id,
            title=packet_id,
            spec_json={"scope": ["src/tz06/crashed.py"], "conflict_keys": []},
            state=PacketState.ACCEPTED.value,
            attempt_count=1,
            max_attempts=3,
        ))
        db.add(DBWorker(
            id="tz06-crashed-worker",
            status="active",
            current_packet_id=packet_id,
        ))
        lease = ParallelLeaseService(ttl_seconds=30).acquire(
            db,
            packet_id=packet_id,
            feature_id="tz06-feature",
            wave_id="tz06-wave",
            worker_id="tz06-crashed-worker",
            claimed_attempt=1,
            scope=["src/tz06/crashed.py"],
            conflict_keys=[],
            base_sha="a" * 40,
            now=datetime.now(UTC) - timedelta(minutes=2),
        )
        lease.expires_at = datetime.now(UTC) - timedelta(minutes=1)

    target = tmp_path / "cleanup-target"
    source = tmp_path / "cleanup-source"
    target.mkdir()
    source.mkdir()
    report = SupervisorCleanupService(target, source).run(
        worktrees=False,
        state_files=False,
        stale_lease_minutes=1,
    )

    with get_db() as db:
        packet = db.query(Packet).filter_by(id=packet_id).one()
        assert packet.state == PacketState.BLOCKED_RECOVERABLE.value
        assert db.query(DBWorker).filter_by(id="tz06-crashed-worker").one().current_packet_id is None
    assert report.stale_leases_released == 1


# END_BLOCK_TESTS
