"""Tests for packet retry semantics (TZ §6.2)."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime

import pytest

from grace_control.db import get_db, init_db
from grace_control.db.schema import Feature, Packet, PacketState, Wave
from grace_control.services.packet_service import (
    MaxRetriesReachedError,
    PacketService,
    StateTransitionError,
)


@pytest.fixture
def _db():
    init_db("sqlite:///:memory:")


def _add_feature(s, fid: str, status: str = "active"):
    s.add(Feature(id=fid, slug=fid, title=fid, description="",
                  spec_json={}, status=status,
                  created_at=datetime.now(UTC)))
    s.commit()


def _add_wave(s, wid: str, fid: str):
    s.add(Wave(id=wid, feature_id=fid, slug=wid, title=wid, description="",
               order=1))
    s.commit()


def _add_packet(s, pid: str, fid: str, wid: str, state: str,
                 attempt: int = 0, max_attempts: int = 3):
    s.add(Packet(id=pid, feature_id=fid, wave_id=wid,
                 slug=pid, title=pid, description="",
                 spec_json={}, state=state,
                 attempt_count=attempt, max_attempts=max_attempts,
                 created_at=datetime.now(UTC)))
    s.commit()


def test_retry_rejected_packet_with_attempts_left_moves_to_ready(_db):
    with get_db() as s:
        _add_feature(s, "feat_RR1")
        _add_wave(s, "wave_RR1", "feat_RR1")
        _add_packet(s, "pkt_RR1", "feat_RR1", "wave_RR1",
                     state=PacketState.REJECTED.value, attempt=1, max_attempts=3)
    # Replace the db factory with the in-memory test one.
    svc = PacketService(db_factory=_get_test_db)
    asyncio.run(svc.retry("pkt_RR1"))
    with get_db() as s:
        p = s.query(Packet).filter_by(id="pkt_RR1").first()
        assert p.state == PacketState.READY.value


def test_retry_rejected_packet_attempts_exhausted_raises(_db):
    with get_db() as s:
        _add_feature(s, "feat_RR2")
        _add_wave(s, "wave_RR2", "feat_RR2")
        _add_packet(s, "pkt_RR2", "feat_RR2", "wave_RR2",
                     state=PacketState.REJECTED.value, attempt=3, max_attempts=3)
    svc = PacketService(db_factory=_get_test_db)
    with pytest.raises(MaxRetriesReachedError):
        asyncio.run(svc.retry("pkt_RR2"))
    # Packet should be transitioned to FAILED (terminal).
    with get_db() as s:
        p = s.query(Packet).filter_by(id="pkt_RR2").first()
        assert p.state == PacketState.FAILED.value


def test_retry_packet_in_wrong_state_raises(_db):
    with get_db() as s:
        _add_feature(s, "feat_RR3")
        _add_wave(s, "wave_RR3", "feat_RR3")
        _add_packet(s, "pkt_RR3", "feat_RR3", "wave_RR3",
                     state=PacketState.READY.value, attempt=0, max_attempts=3)
    svc = PacketService(db_factory=_get_test_db)
    with pytest.raises(StateTransitionError):
        asyncio.run(svc.retry("pkt_RR3"))


def test_retry_blocked_recoverable_moves_to_ready(_db):
    with get_db() as s:
        _add_feature(s, "feat_RR4")
        _add_wave(s, "wave_RR4", "feat_RR4")
        _add_packet(s, "pkt_RR4", "feat_RR4", "wave_RR4",
                     state=PacketState.BLOCKED_RECOVERABLE.value,
                     attempt=1, max_attempts=3)
    svc = PacketService(db_factory=_get_test_db)
    asyncio.run(svc.retry("pkt_RR4"))
    with get_db() as s:
        p = s.query(Packet).filter_by(id="pkt_RR4").first()
        assert p.state == PacketState.READY.value


# Helper to swap the packet service DB factory to the in-memory one used
# in tests. We monkeypatch get_db to the same session for the test.
def _get_test_db():
    # Returns a session bound to the in-memory sqlite used by init_db().
    from grace_control.db import SessionLocal
    return SessionLocal()
