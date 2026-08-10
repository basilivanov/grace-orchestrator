# ############################################################################
# AI_HEADER: test_tz03_safe_atomic_claim — TZ03 parallel claim acceptance tests
# ############################################################################

# START_MODULE_CONTRACT
# purpose: Verify Alembic-backed parallel leases, conservative conflict policy,
#          fenced lifecycle, atomic capacity/dependency selection, and real
#          concurrent SQLite claims.
# inputs: Temporary file-backed SQLite databases and GRACE concurrency settings.
# returns: Pytest acceptance results.
# side_effects: Creates temporary databases and packet/lease rows.
# emitted_logs: None.
# error_behavior: Test failures identify a violated TZ03 invariant.
# END_MODULE_CONTRACT

# START_MODULE_MAP
# mapping:
#   - function: test_parallel_conflict_service_covers_scope_and_key_rules
#   - function: test_four_disjoint_packets_claim_and_fifth_waits_capacity
#   - function: test_dependency_waits_until_merged
#   - function: test_overlap_and_same_key_are_serialized
#   - function: test_merge_release_allows_conflicting_packet
#   - function: test_expired_parallel_lease_is_fenced
#   - function: test_concurrent_sqlite_claims_cannot_take_conflicting_packets
#   - function: test_concurrency_one_keeps_legacy_queue_behavior
# END_MODULE_MAP

from __future__ import annotations

import asyncio
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from grace_control.core.lease_manager import check_expired_leases
from grace_control.core.structured_logger import GraceLogger
from grace_control.db import get_db, init_db
from grace_control.db.schema import Feature, Lease, Packet, PacketState, ParallelLease, Wave, Worker
from grace_control.services.packet_service import PacketService
from grace_control.services.parallel_conflict_service import ParallelConflictService
from grace_control.services.parallel_lease_service import (
    ParallelLeaseFencedError,
    ParallelLeaseService,
)
from grace_control.services.safe_queue_claim_service import SafeQueueClaimService

_log = GraceLogger("test_tz03_safe_atomic_claim")


# START_BLOCK_TESTS

# START_FUNCTION_CONTRACT
# name: _database
# purpose: Initialize one isolated file-backed SQLite database for a test.
# inputs: tmp_path — pytest temporary directory.
# returns: Database path.
# side_effects: Creates a SQLite file and runs Alembic head.
# emitted_logs: None.
# error_behavior: Propagates migration/database failures.
# END_FUNCTION_CONTRACT
def _database(tmp_path: Path) -> Path:
    path = tmp_path / "tz03.db"
    init_db(f"sqlite:///{path}")
    return path


# START_FUNCTION_CONTRACT
# name: _seed
# purpose: Seed one active feature, ordered waves, workers, and READY packets.
# inputs: packet_specs — (packet id, wave id, scope, keys, dependencies) tuples;
#         waves — ordered wave IDs; tmp_path — isolated DB location.
# returns: Database path.
# side_effects: Inserts test rows into SQLite.
# emitted_logs: None.
# error_behavior: Propagates database failures.
# END_FUNCTION_CONTRACT
def _seed(
    tmp_path: Path,
    packet_specs: list[tuple[str, str, list[str], list[str], list[str]]],
    waves: list[str] | None = None,
) -> Path:
    path = _database(tmp_path)
    wave_ids = waves or sorted({item[1] for item in packet_specs})
    with get_db() as db:
        db.add(Feature(id="feature-1", slug="feature-1", title="Feature 1", spec_json={}, status="active"))
        for order, wave_id in enumerate(wave_ids, start=1):
            db.add(Wave(
                id=wave_id,
                feature_id="feature-1",
                slug=wave_id,
                title=wave_id,
                order=order,
                status="IN_PROGRESS",
            ))
        worker_ids = {f"worker-{index}" for index in range(len(packet_specs) + 4)}
        for worker_id in worker_ids:
            db.add(Worker(id=worker_id, status="idle"))
        for packet_id, wave_id, scope, keys, dependencies in packet_specs:
            db.add(Packet(
                id=packet_id,
                feature_id="feature-1",
                wave_id=wave_id,
                slug=packet_id,
                title=packet_id,
                spec_json={
                    "scope": scope,
                    "conflict_keys": keys,
                    "depends_on": dependencies,
                },
                state=PacketState.READY.value,
            ))
    return path


# START_FUNCTION_CONTRACT
# name: test_parallel_conflict_service_covers_scope_and_key_rules
# purpose: Verify path normalization, parent/child overlap, glob conservatism,
#          disjoint safety, and conflict-key intersection.
# inputs: None.
# returns: None on success.
# side_effects: None.
# emitted_logs: None.
# error_behavior: Pytest assertion failure on policy regression.
# END_FUNCTION_CONTRACT
def test_parallel_conflict_service_covers_scope_and_key_rules():
    service = ParallelConflictService()
    assert service.scopes_overlap(["src\\service\\"], ["src/service/user.py"])
    assert service.scopes_overlap(["src/service/a"], ["src/service/b"] ) is False
    assert service.scopes_overlap(["src/service/"], ["src/service/user.py"])
    assert service.scopes_overlap(["src/*.py"], ["src/unknown.txt"]) is False
    assert service.scopes_overlap(["src/**/generated/*"], ["src/generated/x.py"])
    assert not service.scopes_overlap(["src/a.py"], ["docs/b.py"])
    assert service.conflict_keys_overlap(["db:users"], [" db:users "])
    assert not service.conflict_keys_overlap(["db:users"], ["db:orders"])


# START_FUNCTION_CONTRACT
# name: test_four_disjoint_packets_claim_and_fifth_waits_capacity
# purpose: Verify four same-wave disjoint claims and the fifth capacity wait.
# inputs: tmp_path — pytest temporary directory; monkeypatch — env isolation.
# returns: None on success.
# side_effects: Creates a file-backed SQLite database and leases.
# emitted_logs: None.
# error_behavior: Pytest assertion failure on capacity or claim regression.
# END_FUNCTION_CONTRACT
def test_four_disjoint_packets_claim_and_fifth_waits_capacity(tmp_path, monkeypatch):
    monkeypatch.setenv("GRACE_MAX_CONCURRENCY", "4")
    _seed(
        tmp_path,
        [(f"p-{index}", "wave-1", [f"src/{index}.py"], [], []) for index in range(5)],
        ["wave-1"],
    )
    service = SafeQueueClaimService()
    claims = [service.claim_next_atomic(f"worker-{index}")[0] for index in range(4)]
    fifth, reason = service.claim_next_atomic("worker-5")
    assert {claim.packet_id for claim in claims if claim} == {f"p-{index}" for index in range(4)}
    assert fifth is None
    assert reason == "capacity"
    with get_db() as db:
        assert db.query(ParallelLease).count() == 4


# START_FUNCTION_CONTRACT
# name: test_dependency_waits_until_merged
# purpose: Verify a dependent packet waits until its producer is MERGED.
# inputs: tmp_path — pytest temporary directory; monkeypatch — env isolation.
# returns: None on success.
# side_effects: Creates and mutates a temporary SQLite database.
# emitted_logs: None.
# error_behavior: Pytest assertion failure on dependency ordering regression.
# END_FUNCTION_CONTRACT
def test_dependency_waits_until_merged(tmp_path, monkeypatch):
    monkeypatch.setenv("GRACE_MAX_CONCURRENCY", "4")
    _seed(
        tmp_path,
        [
            ("producer", "wave-1", ["src/producer.py"], [], []),
            ("consumer", "wave-2", ["src/consumer.py"], [], ["producer"]),
        ],
        ["wave-1", "wave-2"],
    )
    service = SafeQueueClaimService()
    producer, reason = service.claim_next_atomic("worker-0")
    assert producer is not None and reason == "ok"
    consumer, reason = service.claim_next_atomic("worker-1")
    assert consumer is None
    assert reason == "waiting_for_wave_completion"

    with get_db() as db:
        packet = db.query(Packet).filter_by(id="producer").one()
        packet.state = PacketState.MERGED.value
        ParallelLeaseService().release_for_terminal_state(db, "producer", PacketState.MERGED.value)

    consumer, reason = service.claim_next_atomic("worker-1")
    assert consumer is not None and consumer.packet_id == "consumer"
    assert reason == "ok"


# START_FUNCTION_CONTRACT
# name: test_overlap_and_same_key_are_serialized
# purpose: Verify scope overlap and semantic conflict keys both wait without
#          turning the READY packet into a failure.
# inputs: tmp_path — pytest temporary directory; monkeypatch — env isolation.
# returns: None on success.
# side_effects: Creates a temporary SQLite database and one active lease.
# emitted_logs: None.
# error_behavior: Pytest assertion failure on conflict policy regression.
# END_FUNCTION_CONTRACT
def test_overlap_and_same_key_are_serialized(tmp_path, monkeypatch):
    monkeypatch.setenv("GRACE_MAX_CONCURRENCY", "4")
    _seed(
        tmp_path,
        [
            ("scope-a", "wave-1", ["src/service"], [], []),
            ("scope-b", "wave-1", ["src/service/user.py"], [], []),
            ("key-a", "wave-1", ["src/a.py"], ["db:users"], []),
            ("key-b", "wave-1", ["src/b.py"], ["db:users"], []),
        ],
        ["wave-1"],
    )
    service = SafeQueueClaimService()
    first, reason = service.claim_next_atomic("worker-0")
    assert first is not None and reason == "ok"
    second, reason = service.claim_next_atomic("worker-1")
    assert second is not None and second.packet_id == "key-a"
    third, reason = service.claim_next_atomic("worker-2")
    assert third is None
    assert reason == "waiting_for_conflict"
    with get_db() as db:
        assert db.query(Packet).filter_by(id="scope-b").one().state == PacketState.READY.value
        assert db.query(Packet).filter_by(id="key-b").one().state == PacketState.READY.value


# START_FUNCTION_CONTRACT
# name: test_merge_release_allows_conflicting_packet
# purpose: Verify ACCEPTED retains the parallel lease and MERGED releases it,
#          after which a conflicting READY packet can claim.
# inputs: tmp_path — pytest temporary directory; monkeypatch — env isolation.
# returns: None on success.
# side_effects: Creates and mutates a temporary SQLite database.
# emitted_logs: None.
# error_behavior: Pytest assertion failure on lifecycle regression.
# END_FUNCTION_CONTRACT
def test_merge_release_allows_conflicting_packet(tmp_path, monkeypatch):
    monkeypatch.setenv("GRACE_MAX_CONCURRENCY", "4")
    _seed(
        tmp_path,
        [
            ("first", "wave-1", ["src/shared.py"], [], []),
            ("second", "wave-1", ["src/shared.py"], [], []),
        ],
        ["wave-1"],
    )
    service = SafeQueueClaimService()
    first, _reason = service.claim_next_atomic("worker-0")
    assert first is not None

    async def accept_first():
        await PacketService().release(
            "first",
            "accepted",
            {"accepted": True},
            worker_id="worker-0",
            lease_id=first.lease_id,
            claimed_attempt=first.claimed_attempt,
        )

    asyncio.run(accept_first())
    with get_db() as db:
        assert db.query(ParallelLease).filter_by(packet_id="first").one() is not None
        db.query(ParallelLease).filter_by(packet_id="first").one().expires_at = (
            datetime.now(UTC) - timedelta(seconds=1)
        )

    second, reason = service.claim_next_atomic("worker-1")
    assert second is None
    assert reason == "waiting_for_conflict"
    with get_db() as db:
        assert db.query(Packet).filter_by(id="second").one().state == PacketState.READY.value

    asyncio.run(
        PacketService().transition(
            "first",
            PacketState.MERGED,
            reason="test_merge",
        )
    )

    second, reason = service.claim_next_atomic("worker-1")
    assert second is not None and second.packet_id == "second"
    assert reason == "ok"


# START_FUNCTION_CONTRACT
# name: test_expired_running_parallel_lease_blocks_until_ordinary_recovery
# purpose: Verify an expired parallel reservation remains active while its
#          packet is RUNNING, then is removed after ordinary lease recovery.
# inputs: tmp_path — pytest temporary directory; monkeypatch — env isolation.
# returns: None on success.
# side_effects: Creates a temporary database and runs lease recovery.
# emitted_logs: None.
# error_behavior: Pytest assertion failure on stale-running safety regression.
# END_FUNCTION_CONTRACT
def test_expired_running_parallel_lease_blocks_until_ordinary_recovery(tmp_path, monkeypatch):
    monkeypatch.setenv("GRACE_MAX_CONCURRENCY", "4")
    _seed(
        tmp_path,
        [
            ("first", "wave-1", ["src/shared.py"], [], []),
            ("second", "wave-1", ["src/shared.py"], [], []),
        ],
        ["wave-1"],
    )
    service = SafeQueueClaimService()
    first, _reason = service.claim_next_atomic("worker-0")
    assert first is not None and first.parallel_lease_id is not None

    expired_at = datetime.now(UTC) - timedelta(minutes=2)
    with get_db() as db:
        first_packet = db.query(Packet).filter_by(id="first").one()
        second_packet = db.query(Packet).filter_by(id="second").one()
        second_packet.created_at = first_packet.created_at - timedelta(seconds=1)
        db.query(ParallelLease).filter_by(packet_id="first").one().expires_at = expired_at
        db.query(Lease).filter_by(packet_id="first").one().expires_at = expired_at

    second, reason = service.claim_next_atomic("worker-1")
    assert second is None
    assert reason == "waiting_for_conflict"
    with get_db() as db:
        assert db.query(Packet).filter_by(id="first").one().state == PacketState.RUNNING.value
        assert db.query(Packet).filter_by(id="second").one().state == PacketState.READY.value

    assert check_expired_leases() == 2
    with get_db() as db:
        assert db.query(Packet).filter_by(id="first").one().state == PacketState.READY.value
        assert db.query(ParallelLease).filter_by(packet_id="first").one_or_none() is None

    second, reason = service.claim_next_atomic("worker-1")
    assert second is not None and second.packet_id == "second"
    assert reason == "ok"


# START_FUNCTION_CONTRACT
# name: test_expired_parallel_lease_is_fenced
# purpose: Verify expiry reclaim removes the stale token and rejects its later release.
# inputs: tmp_path — pytest temporary directory; monkeypatch — env isolation.
# returns: None on success.
# side_effects: Creates and mutates a temporary SQLite database.
# emitted_logs: None.
# error_behavior: Pytest assertion failure on fencing regression.
# END_FUNCTION_CONTRACT
def test_expired_parallel_lease_is_fenced(tmp_path, monkeypatch):
    monkeypatch.setenv("GRACE_MAX_CONCURRENCY", "4")
    _seed(tmp_path, [("packet", "wave-1", ["src/packet.py"], [], [])], ["wave-1"])
    claim, _reason = SafeQueueClaimService().claim_next_atomic("worker-0")
    assert claim is not None and claim.parallel_lease_id is not None

    with get_db() as db:
        lease = db.query(ParallelLease).filter_by(packet_id="packet").one()
        db.query(Packet).filter_by(id="packet").one().state = PacketState.READY.value
        lease.expires_at = datetime.now(UTC) - timedelta(seconds=1)
        expired = ParallelLeaseService().expire(db)
        assert expired == 1
        replacement = ParallelLeaseService().acquire(
            db,
            packet_id="packet",
            feature_id="feature-1",
            wave_id="wave-1",
            worker_id="worker-1",
            claimed_attempt=claim.claimed_attempt,
            scope=["src/packet.py"],
            conflict_keys=[],
        )
        with pytest.raises(ParallelLeaseFencedError):
            ParallelLeaseService().release(
                db,
                packet_id="packet",
                worker_id="worker-0",
                lease_id=claim.parallel_lease_id,
                claimed_attempt=claim.claimed_attempt,
            )
        ParallelLeaseService().release(
            db,
            packet_id="packet",
            worker_id="worker-1",
            lease_id=replacement.id,
            claimed_attempt=claim.claimed_attempt,
        )


# START_FUNCTION_CONTRACT
# name: test_concurrent_sqlite_claims_cannot_take_conflicting_packets
# purpose: Exercise real concurrent BEGIN IMMEDIATE claims against a file DB.
# inputs: tmp_path — pytest temporary directory; monkeypatch — env isolation.
# returns: None on success.
# side_effects: Creates a file-backed DB and runs concurrent worker threads.
# emitted_logs: None.
# error_behavior: Pytest assertion failure on race safety regression.
# END_FUNCTION_CONTRACT
def test_concurrent_sqlite_claims_cannot_take_conflicting_packets(tmp_path, monkeypatch):
    monkeypatch.setenv("GRACE_MAX_CONCURRENCY", "4")
    _seed(
        tmp_path,
        [
            ("conflict-a", "wave-1", ["src/shared.py"], [], []),
            ("conflict-b", "wave-1", ["src/shared.py"], [], []),
        ],
        ["wave-1"],
    )

    def claim(worker_index: int):
        return SafeQueueClaimService().claim_next_atomic(f"worker-{worker_index}")

    with ThreadPoolExecutor(max_workers=2) as executor:
        results = list(executor.map(claim, range(2)))
    claimed = [result[0] for result in results if result[0] is not None]
    assert len(claimed) == 1
    assert {claimed[0].packet_id} <= {"conflict-a", "conflict-b"}
    assert sorted(result[1] for result in results if result[0] is None) == ["waiting_for_conflict"]


# START_FUNCTION_CONTRACT
# name: test_concurrency_one_keeps_legacy_queue_behavior
# purpose: Verify the existing QueueService path still enforces one running packet.
# inputs: tmp_path — pytest temporary directory; monkeypatch — env isolation.
# returns: None on success.
# side_effects: Creates a temporary SQLite database and ordinary queue state.
# emitted_logs: None.
# error_behavior: Pytest assertion failure on backward-compatible mode regression.
# END_FUNCTION_CONTRACT
def test_concurrency_one_keeps_legacy_queue_behavior(tmp_path, monkeypatch):
    monkeypatch.setenv("GRACE_MAX_CONCURRENCY", "1")
    _seed(
        tmp_path,
        [
            ("legacy-a", "wave-1", ["src/a.py"], [], []),
            ("legacy-b", "wave-1", ["src/b.py"], [], []),
        ],
        ["wave-1"],
    )
    from grace_control.services.queue_service import claim_next

    first, reason = claim_next("worker-0")
    assert first == "legacy-a" and reason == "ok"
    with get_db() as db:
        db.query(Packet).filter_by(id="legacy-a").one().state = PacketState.RUNNING.value
    second, reason = claim_next("worker-1")
    assert second is None
    assert reason == "running_packet_exists"


# END_BLOCK_TESTS
