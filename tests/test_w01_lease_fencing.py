# ############################################################################
# AI_HEADER: test_w01_lease_fencing
# ROLE: W01 regression tests — lease fencing, renewal, and retry semantics.
# ############################################################################

"""W01 Runtime Safety: Lease Fencing, Renewal, and Retry Semantics.

Tests cover:
1. Release requires matching lease_id
2. Stale release does not overwrite new claim
3. Release requires matching claimed_attempt
4. Worker heartbeat renews active lease
5. Expired lease returns RUNNING to READY only when not renewed
6. Timeout releases retryable when attempts remaining
7. Failed remains terminal only for non-retryable or exhausted
8. Core stale worker reclaim scenario (acceptance test)
"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta

import pytest

from grace_control.core.lease_manager import check_expired_leases
from grace_control.core.state_machine import StateTransitionError
from grace_control.db import get_db, init_db
from grace_control.db.schema import Event, Lease, Packet, PacketState, Worker
from grace_control.services.packet_service import (
    ClaimResult,
    MaxRetriesReachedError,
    PacketNotFoundError,
    PacketService,
    StaleLeaseError,
)


@pytest.fixture
def test_db():
    """Fresh in-memory DB for each test."""
    init_db("sqlite:///:memory:")
    yield


def _make_ready_packet(db, packet_id="PKT-001", max_attempts=3):
    """Helper: create a packet in READY state."""
    db.add(Packet(
        id=packet_id,
        feature_id="F1",
        wave_id="W01",
        slug="test",
        title="Test Packet",
        spec_json={},
        state=PacketState.READY.value,
        attempt_count=0,
        max_attempts=max_attempts,
    ))
    db.commit()


def _make_running_packet(db, packet_id="PKT-001", worker_id="w1",
                          attempt_count=1, max_attempts=3):
    """Helper: create a packet in RUNNING state with a lease."""
    db.add(Packet(
        id=packet_id,
        feature_id="F1",
        wave_id="W01",
        slug="test",
        title="Test Packet",
        spec_json={},
        state=PacketState.RUNNING.value,
        attempt_count=attempt_count,
        max_attempts=max_attempts,
    ))
    db.add(Worker(id=worker_id, current_packet_id=packet_id))
    expires = datetime.now(UTC) + timedelta(minutes=5)
    db.add(Lease(
        packet_id=packet_id,
        worker_id=worker_id,
        claimed_attempt=attempt_count,
        expires_at=expires,
    ))
    db.commit()
    # Return lease details for fencing tests
    lease = db.query(Lease).filter_by(packet_id=packet_id).first()
    return lease.id, lease.claimed_attempt, expires


# ─── Test 1: Release requires matching lease_id ────────────────────────────

def test_release_requires_matching_lease_id(test_db):
    """Release with wrong lease_id should be rejected (StaleLeaseError)."""
    with get_db() as db:
        _make_running_packet(db, "PKT-001", "w1", attempt_count=1)

    svc = PacketService()
    with pytest.raises(StaleLeaseError, match="lease_id mismatch"):
        asyncio.get_event_loop().run_until_complete(
            svc.release(
                "PKT-001", "rejected", {"accepted": False},
                worker_id="w1",
                lease_id=99999,  # wrong lease_id
                claimed_attempt=1,
            )
        )

    # Packet should still be RUNNING (not mutated)
    with get_db() as db:
        p = db.query(Packet).filter_by(id="PKT-001").first()
        assert p.state == PacketState.RUNNING.value


# ─── Test 2: Stale release does not overwrite new claim ────────────────────

def test_stale_release_does_not_overwrite_new_claim(test_db):
    """Core scenario: worker A claims, lease expires, worker B claims,
    worker A tries to release with old lease_id — must be rejected."""
    svc = PacketService()

    # Step 1: Worker A claims packet
    with get_db() as db:
        _make_ready_packet(db, "PKT-001", max_attempts=3)

    claim_a = asyncio.get_event_loop().run_until_complete(
        svc.claim("PKT-001", "wA")
    )
    assert claim_a.worker_id == "wA"
    assert claim_a.attempt == 1
    lease_a_id = claim_a.lease_id
    attempt_a = claim_a.claimed_attempt

    # Step 2: Expire lease A (simulate time passing)
    with get_db() as db:
        lease = db.query(Lease).filter_by(packet_id="PKT-001").first()
        lease.expires_at = datetime.now(UTC) - timedelta(minutes=1)
        db.commit()

    # Step 3: Scanner returns packet to READY
    count = check_expired_leases()
    assert count == 1

    with get_db() as db:
        p = db.query(Packet).filter_by(id="PKT-001").first()
        assert p.state == PacketState.READY.value

    # Step 4: Worker B claims packet (attempt 2)
    claim_b = asyncio.get_event_loop().run_until_complete(
        svc.claim("PKT-001", "wB")
    )
    assert claim_b.worker_id == "wB"
    assert claim_b.attempt == 2
    assert claim_b.claimed_attempt == 2
    lease_b_id = claim_b.lease_id

    # Step 5: Worker A tries to release with old lease_id — MUST BE REJECTED
    with pytest.raises(StaleLeaseError):
        asyncio.get_event_loop().run_until_complete(
            svc.release(
                "PKT-001", "accepted", {"accepted": True},
                worker_id="wA",
                lease_id=lease_a_id,
                claimed_attempt=attempt_a,
            )
        )

    # Step 6: Packet should still be RUNNING with worker B's lease
    with get_db() as db:
        p = db.query(Packet).filter_by(id="PKT-001").first()
        assert p.state == PacketState.RUNNING.value
        lease = db.query(Lease).filter_by(packet_id="PKT-001").first()
        assert lease.worker_id == "wB"
        assert lease.claimed_attempt == 2

    # Step 7: Worker B can successfully release
    asyncio.get_event_loop().run_until_complete(
        svc.release(
            "PKT-001", "accepted", {"accepted": True},
            worker_id="wB",
            lease_id=lease_b_id,
            claimed_attempt=2,
        )
    )

    with get_db() as db:
        p = db.query(Packet).filter_by(id="PKT-001").first()
        assert p.state == PacketState.ACCEPTED.value


# ─── Test 3: Release requires matching claimed_attempt ────────────────────

def test_release_requires_matching_attempt_count(test_db):
    """Release with wrong claimed_attempt should be rejected."""
    with get_db() as db:
        _make_running_packet(db, "PKT-001", "w1", attempt_count=2)

    svc = PacketService()
    with get_db() as db:
        lease = db.query(Lease).filter_by(packet_id="PKT-001").first()

    with pytest.raises(StaleLeaseError, match="claimed_attempt mismatch"):
        asyncio.get_event_loop().run_until_complete(
            svc.release(
                "PKT-001", "rejected", {"accepted": False},
                worker_id="w1",
                lease_id=lease.id,
                claimed_attempt=1,  # wrong — should be 2
            )
        )


# ─── Test 4: Worker heartbeat renews active lease ─────────────────────────

def test_worker_heartbeat_renews_active_lease(test_db):
    """renew_lease() should extend expires_at for the matching worker+lease."""
    svc = PacketService()

    with get_db() as db:
        _make_ready_packet(db, "PKT-001")

    claim = asyncio.get_event_loop().run_until_complete(
        svc.claim("PKT-001", "w1")
    )

    # Record original expires_at
    with get_db() as db:
        original_lease = db.query(Lease).filter_by(packet_id="PKT-001").first()
        original_expires = original_lease.expires_at
        if original_expires.tzinfo is None:
            original_expires = original_expires.replace(tzinfo=UTC)

    # Wait a tiny bit and renew
    import time
    time.sleep(0.1)

    new_expires = asyncio.get_event_loop().run_until_complete(
        svc.renew_lease("PKT-001", "w1", claim.lease_id)
    )

    # New expires should be later than original
    assert new_expires > original_expires

    # DB should reflect the new expiry (SQLite strips timezone)
    with get_db() as db:
        lease = db.query(Lease).filter_by(packet_id="PKT-001").first()
        # Compare naive times since SQLite strips timezone info
        db_expires = lease.expires_at
        if db_expires.tzinfo is not None:
            db_expires = db_expires.replace(tzinfo=None)
        new_expires_naive = new_expires.replace(tzinfo=None) if new_expires.tzinfo else new_expires
        assert db_expires == new_expires_naive
        # Lease should still belong to w1
        assert lease.worker_id == "w1"


def test_lease_renewal_rejects_wrong_worker(test_db):
    """Renewal from a different worker should fail."""
    svc = PacketService()

    with get_db() as db:
        _make_ready_packet(db, "PKT-001")

    claim = asyncio.get_event_loop().run_until_complete(
        svc.claim("PKT-001", "w1")
    )

    with pytest.raises(StaleLeaseError, match="Worker mismatch"):
        asyncio.get_event_loop().run_until_complete(
            svc.renew_lease("PKT-001", "w2", claim.lease_id)
        )


def test_lease_renewal_rejects_expired_lease(test_db):
    """Renewal of an already-expired lease should fail."""
    svc = PacketService()

    with get_db() as db:
        _make_ready_packet(db, "PKT-001")

    claim = asyncio.get_event_loop().run_until_complete(
        svc.claim("PKT-001", "w1")
    )

    # Expire the lease
    with get_db() as db:
        lease = db.query(Lease).filter_by(packet_id="PKT-001").first()
        lease.expires_at = datetime.now(UTC) - timedelta(minutes=1)
        db.commit()

    with pytest.raises(StaleLeaseError, match="already expired"):
        asyncio.get_event_loop().run_until_complete(
            svc.renew_lease("PKT-001", "w1", claim.lease_id)
        )


# ─── Test 5: Expired lease returns RUNNING to READY only when not renewed ──

def test_expired_lease_returns_running_to_ready_only_when_not_renewed(test_db):
    """A renewed lease should NOT be reclaimed by the scanner."""
    svc = PacketService()

    with get_db() as db:
        _make_ready_packet(db, "PKT-001")

    claim = asyncio.get_event_loop().run_until_complete(
        svc.claim("PKT-001", "w1")
    )

    # Renew the lease (extends expiry far into the future)
    asyncio.get_event_loop().run_until_complete(
        svc.renew_lease("PKT-001", "w1", claim.lease_id)
    )

    # Scanner should find no expired leases
    count = check_expired_leases()
    assert count == 0

    # Packet should still be RUNNING
    with get_db() as db:
        p = db.query(Packet).filter_by(id="PKT-001").first()
        assert p.state == PacketState.RUNNING.value


# ─── Test 6: Timeout releases retryable when attempts remaining ────────────

def test_timeout_releases_retryable_when_attempts_remaining(test_db):
    """When timeout occurs and attempts remain, release as rejected (retryable)."""
    svc = PacketService()

    with get_db() as db:
        _make_ready_packet(db, "PKT-001", max_attempts=3)

    # Claim the packet (attempt 1)
    claim = asyncio.get_event_loop().run_until_complete(
        svc.claim("PKT-001", "w1")
    )

    # Worker releases as "rejected" with retryable reason (timeout)
    asyncio.get_event_loop().run_until_complete(
        svc.release(
            "PKT-001", "rejected",
            {"accepted": False, "reason": "timeout", "retryable": True},
            worker_id="w1",
            lease_id=claim.lease_id,
            claimed_attempt=claim.claimed_attempt,
        )
    )

    # Packet should be in REJECTED state (retryable), not FAILED
    with get_db() as db:
        p = db.query(Packet).filter_by(id="PKT-001").first()
        assert p.state == PacketState.REJECTED.value
        assert p.attempt_count == 1
        assert p.attempt_count < p.max_attempts  # retries available


# ─── Test 7: Failed remains terminal only for non-retryable or exhausted ──

def test_failed_remains_terminal_only_for_exhausted_attempts(test_db):
    """FAILED should only be used when attempts are exhausted."""
    svc = PacketService()

    with get_db() as db:
        _make_ready_packet(db, "PKT-001", max_attempts=1)

    claim = asyncio.get_event_loop().run_until_complete(
        svc.claim("PKT-001", "w1")
    )

    # Only 1 attempt allowed, now exhausted — release as failed
    asyncio.get_event_loop().run_until_complete(
        svc.release(
            "PKT-001", "failed",
            {"accepted": False, "reason": "exhausted"},
            worker_id="w1",
            lease_id=claim.lease_id,
            claimed_attempt=claim.claimed_attempt,
        )
    )

    with get_db() as db:
        p = db.query(Packet).filter_by(id="PKT-001").first()
        assert p.state == PacketState.FAILED.value


def test_retry_raises_when_attempts_exhausted(test_db):
    """retry() should raise MaxRetriesReachedError when max_attempts reached."""
    svc = PacketService()

    with get_db() as db:
        _make_ready_packet(db, "PKT-001", max_attempts=1)

    claim = asyncio.get_event_loop().run_until_complete(
        svc.claim("PKT-001", "w1")
    )

    # Release as rejected (attempt 1 = max_attempts)
    asyncio.get_event_loop().run_until_complete(
        svc.release(
            "PKT-001", "rejected",
            {"accepted": False},
            worker_id="w1",
            lease_id=claim.lease_id,
            claimed_attempt=claim.claimed_attempt,
        )
    )

    # Attempting retry should fail (max attempts reached)
    with pytest.raises(MaxRetriesReachedError):
        asyncio.get_event_loop().run_until_complete(
            svc.retry("PKT-001")
        )


# ─── Test 8: Core stale worker reclaim scenario (acceptance test) ─────────

def test_stale_worker_reclaim_scenario(test_db):
    """ACCEPTANCE TEST: Full stale worker reclaim race condition.

    1. Worker A claims packet (attempt 1)
    2. Lease A expires
    3. Scanner returns packet to READY
    4. Worker B claims packet (attempt 2)
    5. Worker A finishes late, tries release with old lease_id/attempt
    6. Release is rejected
    7. Packet remains owned by worker B
    """
    svc = PacketService()

    # 1. Worker A claims
    with get_db() as db:
        _make_ready_packet(db, "PKT-001", max_attempts=3)

    claim_a = asyncio.get_event_loop().run_until_complete(
        svc.claim("PKT-001", "wA")
    )
    assert claim_a.attempt == 1
    lease_a_id = claim_a.lease_id
    attempt_a = claim_a.claimed_attempt

    # 2. Expire lease A
    with get_db() as db:
        lease = db.query(Lease).filter_by(packet_id="PKT-001").first()
        lease.expires_at = datetime.now(UTC) - timedelta(minutes=1)
        db.commit()

    # 3. Scanner returns to READY
    check_expired_leases()

    # 4. Worker B claims (attempt 2)
    claim_b = asyncio.get_event_loop().run_until_complete(
        svc.claim("PKT-001", "wB")
    )
    assert claim_b.attempt == 2
    lease_b_id = claim_b.lease_id

    # 5. Worker A tries to release — REJECTED
    with pytest.raises(StaleLeaseError):
        asyncio.get_event_loop().run_until_complete(
            svc.release(
                "PKT-001", "accepted", {"accepted": True},
                worker_id="wA",
                lease_id=lease_a_id,
                claimed_attempt=attempt_a,
            )
        )

    # 6. Verify packet still belongs to worker B
    with get_db() as db:
        p = db.query(Packet).filter_by(id="PKT-001").first()
        assert p.state == PacketState.RUNNING.value
        lease = db.query(Lease).filter_by(packet_id="PKT-001").first()
        assert lease.worker_id == "wB"
        assert lease.claimed_attempt == 2

    # 7. Worker B successfully releases
    asyncio.get_event_loop().run_until_complete(
        svc.release(
            "PKT-001", "accepted", {"accepted": True},
            worker_id="wB",
            lease_id=lease_b_id,
            claimed_attempt=2,
        )
    )

    with get_db() as db:
        p = db.query(Packet).filter_by(id="PKT-001").first()
        assert p.state == PacketState.ACCEPTED.value


# ─── Test 9: Stale release event is observable ────────────────────────────

def test_stale_release_records_event(test_db):
    """Stale lease rejections should be observable in the event log."""
    with get_db() as db:
        _make_running_packet(db, "PKT-001", "w1", attempt_count=1)

    svc = PacketService()
    with pytest.raises(StaleLeaseError):
        asyncio.get_event_loop().run_until_complete(
            svc.release(
                "PKT-001", "accepted", {"accepted": True},
                worker_id="w1",
                lease_id=99999,  # wrong
                claimed_attempt=1,
            )
        )

    with get_db() as db:
        event = db.query(Event).filter_by(
            event_type="packet_release_rejected_stale_lease"
        ).first()
        assert event is not None
        assert event.payload_json["reason"]  # has reason detail


# ─── Test 10: Lease expiration records events ─────────────────────────────

def test_lease_expiration_records_event(test_db):
    """Expired lease scanner should record events for observability."""
    with get_db() as db:
        db.add(Packet(id="PKT-001", feature_id="F1", wave_id="W01",
                       slug="t", title="T", spec_json={},
                       state=PacketState.RUNNING.value, attempt_count=1))
        db.add(Worker(id="w1", current_packet_id="PKT-001"))
        db.add(Lease(packet_id="PKT-001", worker_id="w1",
                      claimed_attempt=1,
                      expires_at=datetime.now(UTC) - timedelta(minutes=5)))

    count = check_expired_leases()
    assert count == 1

    with get_db() as db:
        event = db.query(Event).filter_by(
            event_type="lease_expired_reclaimed"
        ).first()
        assert event is not None
        assert event.payload_json["claimed_attempt"] == 1
        assert event.payload_json["action"] == "packet_returned_to_ready"


# ─── Test 11: Claim response includes fencing tokens ──────────────────────

def test_claim_includes_fencing_tokens(test_db):
    """Claim result should include lease_id, claimed_attempt for fencing."""
    svc = PacketService()

    with get_db() as db:
        _make_ready_packet(db, "PKT-001")

    claim = asyncio.get_event_loop().run_until_complete(
        svc.claim("PKT-001", "w1")
    )

    assert claim.lease_id is not None
    assert claim.claimed_attempt == 1  # matches attempt_count
    assert claim.worker_id == "w1"
    assert claim.expires_at is not None


# ─── Test 12: Release without fencing tokens fails when lease exists (P0-1) ─

def test_release_without_worker_id_fails_when_lease_exists(test_db):
    """W01 P0-1 fix: Release with missing worker_id must be rejected if lease exists."""
    with get_db() as db:
        _make_running_packet(db, "PKT-001", "w1", attempt_count=1)

    svc = PacketService()
    with pytest.raises(StaleLeaseError, match="worker_id is required"):
        asyncio.get_event_loop().run_until_complete(
            svc.release(
                "PKT-001", "rejected", {"accepted": False},
                # worker_id missing — must be rejected
                lease_id=1,
                claimed_attempt=1,
            )
        )

    # Packet state must NOT be mutated
    with get_db() as db:
        p = db.query(Packet).filter_by(id="PKT-001").first()
        assert p.state == PacketState.RUNNING.value


def test_release_without_lease_id_fails_when_lease_exists(test_db):
    """W01 P0-1 fix: Release with missing lease_id must be rejected if lease exists."""
    with get_db() as db:
        _make_running_packet(db, "PKT-001", "w1", attempt_count=1)

    svc = PacketService()
    with pytest.raises(StaleLeaseError, match="lease_id is required"):
        asyncio.get_event_loop().run_until_complete(
            svc.release(
                "PKT-001", "rejected", {"accepted": False},
                worker_id="w1",
                # lease_id missing
                claimed_attempt=1,
            )
        )

    with get_db() as db:
        p = db.query(Packet).filter_by(id="PKT-001").first()
        assert p.state == PacketState.RUNNING.value


def test_release_without_claimed_attempt_fails_when_lease_exists(test_db):
    """W01 P0-1 fix: Release with missing claimed_attempt must be rejected if lease exists."""
    with get_db() as db:
        _make_running_packet(db, "PKT-001", "w1", attempt_count=1)

    svc = PacketService()
    with get_db() as db:
        lease = db.query(Lease).filter_by(packet_id="PKT-001").first()

    with pytest.raises(StaleLeaseError, match="claimed_attempt is required"):
        asyncio.get_event_loop().run_until_complete(
            svc.release(
                "PKT-001", "rejected", {"accepted": False},
                worker_id="w1",
                lease_id=lease.id,
                # claimed_attempt missing
            )
        )

    with get_db() as db:
        p = db.query(Packet).filter_by(id="PKT-001").first()
        assert p.state == PacketState.RUNNING.value


def test_release_without_lease_succeeds(test_db):
    """Release without fencing tokens should work if no lease exists
    (lease already cleaned up — e.g. scanner reclaimed it)."""
    svc = PacketService()

    with get_db() as db:
        _make_ready_packet(db, "PKT-001")

    claim = asyncio.get_event_loop().run_until_complete(
        svc.claim("PKT-001", "w1")
    )

    # Manually delete the lease (simulating scanner cleanup)
    with get_db() as db:
        lease = db.query(Lease).filter_by(packet_id="PKT-001").first()
        if lease:
            db.delete(lease)
            db.commit()

    # Release without fencing tokens should succeed (no lease to check against)
    asyncio.get_event_loop().run_until_complete(
        svc.release(
            "PKT-001", "rejected", {"accepted": False},
            # no worker_id, lease_id, or claimed_attempt — OK because no lease
        )
    )

    with get_db() as db:
        p = db.query(Packet).filter_by(id="PKT-001").first()
        assert p.state == PacketState.REJECTED.value


# ─── Test 13: Renewal from non-RUNNING state fails ────────────────────────

def test_lease_renewal_fails_for_non_running_packet(test_db):
    """Cannot renew lease for a packet that's not in RUNNING state."""
    svc = PacketService()

    with get_db() as db:
        db.add(Packet(id="PKT-001", feature_id="F1", wave_id="W01",
                       slug="t", title="T", spec_json={},
                       state=PacketState.READY.value, attempt_count=0))
        db.add(Lease(packet_id="PKT-001", worker_id="w1",
                      claimed_attempt=0,
                      expires_at=datetime.now(UTC) + timedelta(minutes=5)))

    with pytest.raises(StaleLeaseError, match="not RUNNING|in state"):
        asyncio.get_event_loop().run_until_complete(
            svc.renew_lease("PKT-001", "w1", 1)
        )


# ─── Test 14: Worker stale release does NOT merge (P0-3 fix) ──────────────

def test_worker_stale_release_does_not_merge(test_db):
    """W01 P0-3 fix: If release returns stale_lease=True, worker must NOT merge.

    Simulates the worker._main_loop logic: after _release_with_fencing
    returns stale, the merge path must be skipped.
    """
    # Set up: claim a packet, then simulate another worker reclaiming it
    svc = PacketService()

    with get_db() as db:
        _make_ready_packet(db, "PKT-001", max_attempts=3)

    claim_a = asyncio.get_event_loop().run_until_complete(
        svc.claim("PKT-001", "wA")
    )
    lease_a_id = claim_a.lease_id
    attempt_a = claim_a.claimed_attempt

    # Expire lease and reclaim by worker B
    with get_db() as db:
        lease = db.query(Lease).filter_by(packet_id="PKT-001").first()
        lease.expires_at = datetime.now(UTC) - timedelta(minutes=1)
        db.commit()

    check_expired_leases()

    claim_b = asyncio.get_event_loop().run_until_complete(
        svc.claim("PKT-001", "wB")
    )

    # Worker A tries to release — should be rejected (StaleLeaseError)
    with pytest.raises(StaleLeaseError):
        asyncio.get_event_loop().run_until_complete(
            svc.release(
                "PKT-001", "accepted", {"accepted": True},
                worker_id="wA",
                lease_id=lease_a_id,
                claimed_attempt=attempt_a,
            )
        )

    # Packet must still be RUNNING with worker B — NOT ACCEPTED (not merged)
    with get_db() as db:
        p = db.query(Packet).filter_by(id="PKT-001").first()
        assert p.state == PacketState.RUNNING.value
        lease = db.query(Lease).filter_by(packet_id="PKT-001").first()
        assert lease.worker_id == "wB"


# ─── Test 15: Missing token event is observable ────────────────────────────

def test_missing_fencing_token_records_event(test_db):
    """W01: Missing fencing token rejections should be observable in the event log."""
    with get_db() as db:
        _make_running_packet(db, "PKT-001", "w1", attempt_count=1)

    svc = PacketService()
    with pytest.raises(StaleLeaseError, match="worker_id is required"):
        asyncio.get_event_loop().run_until_complete(
            svc.release(
                "PKT-001", "rejected", {"accepted": False},
                # worker_id missing
                lease_id=1,
                claimed_attempt=1,
            )
        )

    with get_db() as db:
        event = db.query(Event).filter_by(
            event_type="packet_release_rejected_missing_token"
        ).first()
        assert event is not None
        assert "worker_id is required" in event.payload_json["reason"]


# ─── Test 16: Grace period in scanner ─────────────────────────────────────

def test_scanner_grace_period_prevents_premature_reclaim(test_db):
    """W01 P2 fix: Scanner should not reclaim a lease that only just expired
    within the grace period."""
    svc = PacketService()

    with get_db() as db:
        _make_ready_packet(db, "PKT-001")

    claim = asyncio.get_event_loop().run_until_complete(
        svc.claim("PKT-001", "w1")
    )

    # Set lease to expire 10 seconds ago (within 30s grace period)
    with get_db() as db:
        lease = db.query(Lease).filter_by(packet_id="PKT-001").first()
        lease.expires_at = datetime.now(UTC) - timedelta(seconds=10)
        db.commit()

    # Scanner should NOT reclaim — within grace period
    count = check_expired_leases()
    assert count == 0

    # Packet should still be RUNNING
    with get_db() as db:
        p = db.query(Packet).filter_by(id="PKT-001").first()
        assert p.state == PacketState.RUNNING.value

    # Now set lease to expire 60 seconds ago (beyond grace period)
    with get_db() as db:
        lease = db.query(Lease).filter_by(packet_id="PKT-001").first()
        lease.expires_at = datetime.now(UTC) - timedelta(seconds=60)
        db.commit()

    # Scanner should now reclaim
    count = check_expired_leases()
    assert count == 1

    with get_db() as db:
        p = db.query(Packet).filter_by(id="PKT-001").first()
        assert p.state == PacketState.READY.value
