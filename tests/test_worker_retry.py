# ############################################################################
# AI_HEADER: test_worker_retry
# ROLE: Unit tests for auto-retry on REJECTED packets.
# ############################################################################

from __future__ import annotations

import pytest

from grace_control.core.packet_operations import mark_rejected, retry_packet
from grace_control.core.state_machine import StateTransitionError
from grace_control.db import get_db, init_db
from grace_control.db.schema import Packet, PacketState


@pytest.fixture
def test_db():
    init_db("sqlite:///:memory:")
    with get_db() as db:
        db.add(Packet(
            id="PKT-RETRY", feature_id="F1", wave_id="W01",
            slug="retry", title="Retry test", spec_json={},
            state=PacketState.READY.value, attempt_count=0, max_attempts=3,
        ))


def test_retry_rejected_to_ready(test_db):
    """REJECTED packet → retry → READY (attempts < max)."""
    from grace_control.core.packet_operations import mark_running
    mark_running("PKT-RETRY", "w1")
    mark_rejected("PKT-RETRY", "Test rejection")

    retry_packet("PKT-RETRY")
    with get_db() as db:
        p = db.query(Packet).filter_by(id="PKT-RETRY").first()
        assert p.state == PacketState.READY.value


def test_max_attempts_blocks_retry(test_db):
    """Max attempts reached → retry raises StateTransitionError."""
    with get_db() as db:
        db.add(Packet(
            id="PKT-MAXED", feature_id="F1", wave_id="W01",
            slug="maxed", title="Maxed", spec_json={},
            state=PacketState.REJECTED.value, attempt_count=3, max_attempts=3,
        ))
    with pytest.raises(StateTransitionError, match="Max attempts"):
        retry_packet("PKT-MAXED")


def test_retry_loop_mock(test_db):
    """Simulate worker retry flow: REJECTED → retry → READY → RUNNING → ACCEPTED."""
    from grace_control.core.packet_operations import mark_accepted, mark_running

    # First attempt: READY → RUNNING → REJECTED
    mark_running("PKT-RETRY", "w1")
    mark_rejected("PKT-RETRY", "First fail")

    # Auto-retry: REJECTED → READY
    retry_packet("PKT-RETRY")
    with get_db() as db:
        p = db.query(Packet).filter_by(id="PKT-RETRY").first()
        assert p.state == PacketState.READY.value

    # Second attempt: READY → RUNNING → ACCEPTED
    mark_running("PKT-RETRY", "w1")
    with get_db() as db:
        p = db.query(Packet).filter_by(id="PKT-RETRY").first()
        assert p.state == PacketState.RUNNING.value
        assert p.attempt_count == 2

    mark_accepted("PKT-RETRY", "/evidence/R02")
    with get_db() as db:
        p = db.query(Packet).filter_by(id="PKT-RETRY").first()
        assert p.state == PacketState.ACCEPTED.value
