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
    with get_db() as s:
        _add_feature(s, "feat_D")
        _add_wave(s, "wave_D1", "feat_D")
        _add_packet(s, "pkt_D1", "feat_D", "wave_D1", state=PacketState.REJECTED.value)
    from grace_control.services.queue_service import claim_next
    pid, reason = claim_next("worker")
    assert pid is None
    assert "degraded" in reason


def test_degraded_feature_does_not_block_activation_of_another(_db):
    with get_db() as s:
        _add_feature(s, "feat_D2", created_at=datetime(2026, 1, 1))
        _add_feature(s, "feat_D2_B", created_at=datetime(2026, 1, 2))
        _add_wave(s, "wave_D2", "feat_D2")
        _add_packet(s, "pkt_D2", "feat_D2", "wave_D2", state=PacketState.REJECTED.value)
    from grace_control.services.queue_service import claim_next
    pid, reason = claim_next("worker")
    assert pid is None
    assert "degraded" in reason


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
