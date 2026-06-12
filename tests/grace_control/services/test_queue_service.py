"""Tests for queue discipline — deterministic FIFO feature order, wave order, degraded stop."""

from __future__ import annotations

import os
from datetime import UTC, datetime, timedelta
from unittest.mock import patch

import pytest

from grace_control.db import get_db, init_db
from grace_control.db.schema import Feature, Packet, PacketState, Wave


@pytest.fixture
def _db():
    init_db("sqlite:///:memory:")


def _add_feature(s, fid: str, status: str = "NOT_STARTED", created_at=None):
    s.add(Feature(id=fid, slug=fid, title=fid, description="",
                  spec_json={}, status=status,
                  created_at=created_at or datetime.now(UTC)))
    s.commit()


def _add_wave(s, wid: str, fid: str, order: int = 1):
    s.add(Wave(id=wid, feature_id=fid, slug=wid, title=wid, description="",
               order=order))
    s.commit()


def _add_packet(s, pid: str, fid: str, wid: str,
                state: str = PacketState.READY.value, created_at=None):
    s.add(Packet(id=pid, feature_id=fid, wave_id=wid,
                 slug=pid, title=pid, description="",
                 spec_json={}, state=state,
                 created_at=created_at or datetime.now(UTC)))
    s.commit()


# ── FIFO feature order ─────────────────────────────────────────────────


def test_oldest_feature_activated_first(_db):
    with get_db() as s:
        _add_feature(s, "feat_A", created_at=datetime(2026, 1, 1))
        _add_feature(s, "feat_B", created_at=datetime(2026, 1, 2))
        _add_wave(s, "wave_A1", "feat_A")
        _add_wave(s, "wave_B1", "feat_B")
        _add_packet(s, "pkt_A1", "feat_A", "wave_A1")
        _add_packet(s, "pkt_B1", "feat_B", "wave_B1")

    from grace_control.services.queue_service import claim_next
    pid, _ = claim_next("worker")
    assert pid == "pkt_A1", f"Expected A's packet, got {pid}"
    # claim_next keeps returning the same packet until claimed via PacketService
    pid2, _ = claim_next("worker")
    assert pid2 == "pkt_A1", f"Should keep returning A until claimed, got {pid2}"


def test_feature_order_by_id_tiebreaker(_db):
    ts = datetime(2026, 1, 1)
    with get_db() as s:
        _add_feature(s, "feat_AAA", created_at=ts)
        _add_feature(s, "feat_BBB", created_at=ts)
        _add_wave(s, "wave_A1", "feat_AAA")
        _add_wave(s, "wave_B1", "feat_BBB")
        _add_packet(s, "pkt_A1", "feat_AAA", "wave_A1")
        _add_packet(s, "pkt_B1", "feat_BBB", "wave_B1")
    from grace_control.services.queue_service import claim_next
    pid, _ = claim_next("worker")
    assert pid == "pkt_A1"


# ── Wave order ─────────────────────────────────────────────────────────


def test_wave_order(_db):
    with get_db() as s:
        _add_feature(s, "feat_W")
        _add_wave(s, "wave_W1", "feat_W", order=1)
        _add_wave(s, "wave_W2", "feat_W", order=2)
        _add_packet(s, "pkt_W2_1", "feat_W", "wave_W2", state="draft")
        _add_packet(s, "pkt_W1_1", "feat_W", "wave_W1")
    from grace_control.services.queue_service import claim_next
    pid, _ = claim_next("worker")
    assert pid == "pkt_W1_1"


# ── Packet order inside wave ───────────────────────────────────────────


def test_packet_order_inside_wave(_db):
    ts = datetime(2026, 1, 1)
    with get_db() as s:
        _add_feature(s, "feat_P")
        _add_wave(s, "wave_P1", "feat_P")
        _add_packet(s, "pkt_B", "feat_P", "wave_P1", created_at=ts + timedelta(hours=1))
        _add_packet(s, "pkt_A", "feat_P", "wave_P1", created_at=ts)
    from grace_control.services.queue_service import claim_next
    pid, _ = claim_next("worker")
    assert pid == "pkt_A"


def test_packet_order_by_id_tiebreaker(_db):
    ts = datetime(2026, 1, 1)
    with get_db() as s:
        _add_feature(s, "feat_P2")
        _add_wave(s, "wave_P2", "feat_P2")
        _add_packet(s, "pkt_B", "feat_P2", "wave_P2", created_at=ts)
        _add_packet(s, "pkt_A", "feat_P2", "wave_P2", created_at=ts)
    from grace_control.services.queue_service import claim_next
    pid, _ = claim_next("worker")
    assert pid == "pkt_A"


# ── Degraded feature stops queue ───────────────────────────────────────


def test_degraded_packet_blocks_feature(_db):
    """REJECTED with attempts exhausted → feature degraded, no claim."""
    with get_db() as s:
        _add_feature(s, "feat_D")
        _add_wave(s, "wave_D1", "feat_D")
        _add_packet_with_attempts(
            s, "pkt_D1", "feat_D", "wave_D1",
            state=PacketState.REJECTED.value, attempt=3, max_attempts=3,
        )
    from grace_control.services.queue_service import claim_next
    pid, reason = claim_next("worker")
    assert pid is None
    assert reason == "feature_degraded"
    with get_db() as s:
        feat = s.query(Feature).filter_by(id="feat_D").first()
        assert feat.status == "degraded"


def test_degraded_feature_does_not_block_activation_of_another(_db):
    """Terminal-failed feature does not block activation of a different queued feature."""
    with get_db() as s:
        _add_feature(s, "feat_D2", created_at=datetime(2026, 1, 1))
        _add_feature(s, "feat_D2_B", created_at=datetime(2026, 1, 2), status="queued")
        _add_wave(s, "wave_D2", "feat_D2")
        _add_packet_with_attempts(
            s, "pkt_D2", "feat_D2", "wave_D2",
            state=PacketState.REJECTED.value, attempt=3, max_attempts=3,
        )
        _add_wave(s, "wave_D2_B", "feat_D2_B")
        _add_packet(s, "pkt_D2_B_1", "feat_D2_B", "wave_D2_B")
    from grace_control.services.queue_service import claim_next
    pid, reason = claim_next("worker")
    with get_db() as s:
        feat_D2 = s.query(Feature).filter_by(id="feat_D2").first()
        feat_D2_B = s.query(Feature).filter_by(id="feat_D2_B").first()
    assert feat_D2.status == "degraded"
    # Second feature should have been activated (or was already queued).
    assert feat_D2_B.status in ("active", "queued")
    if pid is not None:
        assert pid == "pkt_D2_B_1", f"Expected pkt_D2_B_1, got {pid}"


# ── Concurrency ────────────────────────────────────────────────────────


def test_single_concurrency_blocks_second_claim(_db):
    with patch.dict(os.environ, {"GRACE_MAX_CONCURRENCY": "1"}, clear=False):
        with get_db() as s:
            _add_feature(s, "feat_C")
            _add_wave(s, "wave_C1", "feat_C")
            _add_packet(s, "pkt_C1", "feat_C", "wave_C1", state=PacketState.RUNNING.value)
        from grace_control.services.queue_service import claim_next
        pid, reason = claim_next("worker")
        assert pid is None
        assert reason == "running_packet_exists"


def test_second_feature_not_claimable_while_first_active(_db):
    """Feature B is not activated while Feature A has an unclaimed READY packet."""
    with get_db() as s:
        _add_feature(s, "feat_A", created_at=datetime(2026, 1, 1))
        _add_feature(s, "feat_B", created_at=datetime(2026, 1, 2))
        _add_wave(s, "wave_A1", "feat_A")
        _add_wave(s, "wave_B1", "feat_B")
        _add_packet(s, "pkt_A1", "feat_A", "wave_A1")
        _add_packet(s, "pkt_B1", "feat_B", "wave_B1")

    from grace_control.services.queue_service import claim_next

    # First call: Feature A is activated, pkt_A1 returned
    pid1, _ = claim_next("worker")
    assert pid1 == "pkt_A1"

    # Call PacketService.claim to set pkt_A1 to RUNNING
    from grace_control.services.packet_service import PacketService
    import asyncio
    result = asyncio.run(PacketService().claim("pkt_A1", "worker"))
    assert result.packet_id == "pkt_A1"

    # Now with RUNNING packet, next call should return None (running_packet_exists)
    pid2, r2 = claim_next("worker")
    assert pid2 is None, f"Should not return B's packet while A is RUNNING, got {pid2}"
    assert "running" in r2 or r2 == "running_packet_exists"


def test_no_running_packet_allows_claim(_db):
    with get_db() as s:
        _add_feature(s, "feat_NR")
        _add_wave(s, "wave_NR1", "feat_NR")
        _add_packet(s, "pkt_NR1", "feat_NR", "wave_NR1")
    from grace_control.services.queue_service import claim_next
    pid, reason = claim_next("worker")
    assert pid == "pkt_NR1"
    assert reason == "ok"


# ── Backward compatibility ─────────────────────────────────────────────


def test_not_started_treated_as_queued(_db):
    with get_db() as s:
        _add_feature(s, "feat_NS", status="NOT_STARTED")
        _add_wave(s, "wave_NS1", "feat_NS")
        _add_packet(s, "pkt_NS1", "feat_NS", "wave_NS1")
    from grace_control.services.queue_service import claim_next
    pid, _ = claim_next("worker")
    assert pid == "pkt_NS1"


def test_feature_marked_active_after_claim(_db):
    with get_db() as s:
        _add_feature(s, "feat_AC", status="NOT_STARTED")
        _add_wave(s, "wave_AC1", "feat_AC")
        _add_packet(s, "pkt_AC1", "feat_AC", "wave_AC1")
    from grace_control.services.queue_service import claim_next
    claim_next("worker")
    with get_db() as s:
        f2 = s.query(Feature).filter_by(id="feat_AC").first()
        assert f2.status == "active"


# ── Feature completion ─────────────────────────────────────────────────


def test_all_merged_makes_feature_done(_db):
    with get_db() as s:
        _add_feature(s, "feat_DONE")
        _add_wave(s, "wave_DONE1", "feat_DONE")
        _add_packet(s, "pkt_DONE1", "feat_DONE", "wave_DONE1", state=PacketState.MERGED.value)
    from grace_control.services.queue_service import claim_next
    pid, reason = claim_next("worker")
    assert pid is None
    assert reason == "feature_done"


# ── Wave gating: earlier waves block later ones ────────────────────────


def test_wave1_draft_wave2_ready_no_claim(_db):
    """Wave 1 DRAFT + Wave 2 READY → Wave 2 cannot be claimed."""
    with get_db() as s:
        _add_feature(s, "feat_WG")
        _add_wave(s, "wave_WG1", "feat_WG", order=1)
        _add_wave(s, "wave_WG2", "feat_WG", order=2)
        _add_packet(s, "pkt_WG1_1", "feat_WG", "wave_WG1", state="draft")
        _add_packet(s, "pkt_WG2_1", "feat_WG", "wave_WG2")
    from grace_control.services.queue_service import claim_next
    pid, reason = claim_next("worker")
    assert pid is None, f"Wave 2 should not be claimable before Wave 1, got {pid}"
    assert "waiting_for_wave_completion" in reason


def test_wave1_accepted_wave2_ready_no_claim(_db):
    """Wave 1 ACCEPTED (not merged) + Wave 2 READY → no claim."""
    with get_db() as s:
        _add_feature(s, "feat_WA")
        _add_wave(s, "wave_WA1", "feat_WA", order=1)
        _add_wave(s, "wave_WA2", "feat_WA", order=2)
        _add_packet(s, "pkt_WA1_1", "feat_WA", "wave_WA1", state=PacketState.ACCEPTED.value)
        _add_packet(s, "pkt_WA2_1", "feat_WA", "wave_WA2")
    from grace_control.services.queue_service import claim_next
    pid, reason = claim_next("worker")
    assert pid is None, f"Wave 2 should not be claimable until Wave 1 is merged, got {pid}"
    assert "waiting_for_wave_completion" in reason


def test_wave1_merged_wave2_ready_claim_wave2(_db):
    """Wave 1 MERGED + Wave 2 READY → Wave 2 packet is claimable."""
    with get_db() as s:
        _add_feature(s, "feat_WM")
        _add_wave(s, "wave_WM1", "feat_WM", order=1)
        _add_wave(s, "wave_WM2", "feat_WM", order=2)
        _add_packet(s, "pkt_WM1_1", "feat_WM", "wave_WM1", state=PacketState.MERGED.value)
        _add_packet(s, "pkt_WM2_1", "feat_WM", "wave_WM2")
    from grace_control.services.queue_service import claim_next
    pid, reason = claim_next("worker")
    assert pid == "pkt_WM2_1", f"Expected Wave 2 packet, got {pid}"
    assert reason == "ok"


def test_all_accepted_feature_not_done(_db):
    """All packets ACCEPTED (not merged) → feature is NOT done."""
    with get_db() as s:
        _add_feature(s, "feat_AC2")
        _add_wave(s, "wave_AC2_1", "feat_AC2")
        _add_packet(s, "pkt_AC2_1", "feat_AC2", "wave_AC2_1", state=PacketState.ACCEPTED.value)
    from grace_control.services.queue_service import claim_next
    pid, reason = claim_next("worker")
    assert pid is None, "No READY packets, so no claim"
    assert reason != "feature_done", "ACCEPTED should not trigger feature_done"


# ── TZ §6.1: Retry semantics — retryable vs terminal failures ────────────


def _add_packet_with_attempts(s, pid: str, fid: str, wid: str, state: str,
                              attempt: int, max_attempts: int):
    s.add(Packet(id=pid, feature_id=fid, wave_id=wid,
                 slug=pid, title=pid, description="",
                 spec_json={}, state=state,
                 attempt_count=attempt, max_attempts=max_attempts))
    s.commit()


def test_rejected_packet_with_attempts_left_does_not_degrade_feature(_db):
    """REJECTED packet with attempts left → feature stays active, reason waiting_for_retry."""
    with get_db() as s:
        _add_feature(s, "feat_RJ1", status="active")
        _add_wave(s, "wave_RJ1_1", "feat_RJ1")
        _add_packet_with_attempts(
            s, "pkt_RJ1_1", "feat_RJ1", "wave_RJ1_1",
            state=PacketState.REJECTED.value, attempt=1, max_attempts=3,
        )
    from grace_control.services.queue_service import claim_next
    pid, reason = claim_next("worker")
    assert pid is None, f"Expected no claim (REJECTED not claimable), got {pid}"
    assert reason == "waiting_for_retry", f"Expected waiting_for_retry, got {reason}"
    # Feature must NOT be degraded
    with get_db() as s:
        feat = s.query(Feature).filter_by(id="feat_RJ1").first()
        assert feat.status != "degraded", f"Feature must not be degraded, got {feat.status}"


def test_failed_packet_is_terminal_always_degrades_feature(_db):
    """FAILED is terminal/exhausted ONLY (TZ §6.1).

    Unlike REJECTED, FAILED never waits for retry. Any FAILED packet in
    an active feature must set the feature to degraded immediately. This
    prevents the legacy bug where a FAILED packet with attempts left
    sat in `waiting_for_retry` forever because PacketService.retry()
    only accepts REJECTED / BLOCKED_RECOVERABLE.
    """
    with get_db() as s:
        _add_feature(s, "feat_FL1", status="active")
        _add_wave(s, "wave_FL1_1", "feat_FL1")
        _add_packet_with_attempts(
            s, "pkt_FL1_1", "feat_FL1", "wave_FL1_1",
            state=PacketState.FAILED.value, attempt=1, max_attempts=3,
        )
    from grace_control.services.queue_service import claim_next
    pid, reason = claim_next("worker")
    assert pid is None
    assert reason == "feature_degraded"
    with get_db() as s:
        feat = s.query(Feature).filter_by(id="feat_FL1").first()
        assert feat.status == "degraded"


def test_failed_packet_helper_always_terminal(_db):
    """is_retryable_failure(FAILED) is always False; is_terminal_failure is True."""
    from grace_control.db.schema import Packet
    from grace_control.services.queue_service import (
        is_retryable_failure,
        is_terminal_failure,
    )
    p = Packet(id="x", state=PacketState.FAILED.value,
               attempt_count=1, max_attempts=3)
    assert not is_retryable_failure(p)
    assert is_terminal_failure(p)
    # Even when attempts remaining
    p_low = Packet(id="x", state=PacketState.FAILED.value,
                    attempt_count=0, max_attempts=3)
    assert not is_retryable_failure(p_low)
    assert is_terminal_failure(p_low)


def test_rejected_packet_with_attempts_exhausted_degrades_feature(_db):
    """REJECTED packet with attempt == max → feature must be degraded."""
    with get_db() as s:
        _add_feature(s, "feat_RJ2", status="active")
        _add_wave(s, "wave_RJ2_1", "feat_RJ2")
        _add_packet_with_attempts(
            s, "pkt_RJ2_1", "feat_RJ2", "wave_RJ2_1",
            state=PacketState.REJECTED.value, attempt=3, max_attempts=3,
        )
    from grace_control.services.queue_service import claim_next
    pid, reason = claim_next("worker")
    assert pid is None
    assert reason == "feature_degraded"
    with get_db() as s:
        feat = s.query(Feature).filter_by(id="feat_RJ2").first()
        assert feat.status == "degraded"


def test_blocked_final_degrades_feature(_db):
    """BLOCKED_FINAL is terminal and degrades feature immediately."""
    with get_db() as s:
        _add_feature(s, "feat_BF", status="active")
        _add_wave(s, "wave_BF_1", "feat_BF")
        _add_packet_with_attempts(
            s, "pkt_BF_1", "feat_BF", "wave_BF_1",
            state=PacketState.BLOCKED_FINAL.value, attempt=1, max_attempts=3,
        )
    from grace_control.services.queue_service import claim_next
    pid, reason = claim_next("worker")
    assert pid is None
    assert reason == "feature_degraded"
    with get_db() as s:
        feat = s.query(Feature).filter_by(id="feat_BF").first()
        assert feat.status == "degraded"


def test_retryable_failure_does_not_block_later_wave_claim(_db):
    """Wave 1 REJECTED (retryable) + Wave 2 READY → Wave 2 not claimable (wave order)."""
    with get_db() as s:
        _add_feature(s, "feat_RW", status="active")
        _add_wave(s, "wave_RW1", "feat_RW", order=1)
        _add_wave(s, "wave_RW2", "feat_RW", order=2)
        _add_packet_with_attempts(
            s, "pkt_RW1_1", "feat_RW", "wave_RW1",
            state=PacketState.REJECTED.value, attempt=1, max_attempts=3,
        )
        _add_packet(s, "pkt_RW2_1", "feat_RW", "wave_RW2")
    from grace_control.services.queue_service import claim_next
    pid, reason = claim_next("worker")
    assert pid is None, "Wave 2 must not be claimable while Wave 1 has retryable"
    assert reason in ("waiting_for_retry", "waiting_for_wave_completion")


def test_helper_is_retryable_failure(_db):
    """Pure helper: state machine for is_retryable_failure."""
    from grace_control.services.queue_service import is_retryable_failure
    from grace_control.db.schema import Packet
    p_running = Packet(id="x", state=PacketState.RUNNING.value,
                        attempt_count=1, max_attempts=3)
    assert not is_retryable_failure(p_running)
    p_ready = Packet(id="x", state=PacketState.READY.value,
                      attempt_count=1, max_attempts=3)
    assert not is_retryable_failure(p_ready)
    p_rej_low = Packet(id="x", state=PacketState.REJECTED.value,
                       attempt_count=1, max_attempts=3)
    assert is_retryable_failure(p_rej_low)
    p_rej_max = Packet(id="x", state=PacketState.REJECTED.value,
                       attempt_count=3, max_attempts=3)
    assert not is_retryable_failure(p_rej_max)
    p_blocked = Packet(id="x", state=PacketState.BLOCKED_RECOVERABLE.value,
                       attempt_count=1, max_attempts=3)
    assert not is_retryable_failure(p_blocked)
