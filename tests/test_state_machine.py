# ############################################################################
# AI_HEADER: test_state_machine
# ROLE: Unit tests for GRACE Control Plane state machine and packet operations.
# ############################################################################

from __future__ import annotations

import pytest

from grace_control.core.packet_operations import (
    mark_accepted,
    mark_failed,
    mark_ready,
    mark_rejected,
    mark_running,
    retry_packet,
)
from grace_control.core.state_machine import PacketStateMachine, StateTransitionError
from grace_control.db import get_db, init_db
from grace_control.db.schema import Packet, PacketState


@pytest.fixture
def test_db():
    init_db("sqlite:///:memory:")
    yield


def test_valid_transitions():
    sm = PacketStateMachine()
    assert sm.can_transition(PacketState.DRAFT, PacketState.READY)
    assert sm.can_transition(PacketState.READY, PacketState.RUNNING)
    assert sm.can_transition(PacketState.RUNNING, PacketState.ACCEPTED)
    assert sm.can_transition(PacketState.RUNNING, PacketState.REJECTED)
    assert sm.can_transition(PacketState.RUNNING, PacketState.FAILED)
    assert sm.can_transition(PacketState.REJECTED, PacketState.READY)
    assert sm.can_transition(PacketState.ACCEPTED, PacketState.MERGED)


def test_invalid_transitions():
    sm = PacketStateMachine()
    assert not sm.can_transition(PacketState.DRAFT, PacketState.RUNNING)
    assert not sm.can_transition(PacketState.READY, PacketState.ACCEPTED)
    assert not sm.can_transition(PacketState.MERGED, PacketState.READY)
    assert not sm.can_transition(PacketState.FAILED, PacketState.READY)
    assert not sm.can_transition(PacketState.CANCELLED, PacketState.READY)


def test_terminal_states():
    sm = PacketStateMachine()
    assert sm.is_terminal(PacketState.MERGED)
    assert sm.is_terminal(PacketState.FAILED)
    assert sm.is_terminal(PacketState.CANCELLED)
    assert not sm.is_terminal(PacketState.RUNNING)
    assert not sm.is_terminal(PacketState.ACCEPTED)


def test_state_transition_error():
    sm = PacketStateMachine()
    with pytest.raises(StateTransitionError, match="Invalid transition"):
        sm.transition(PacketState.DRAFT, PacketState.RUNNING)


def test_cancelled_transitions():
    sm = PacketStateMachine()
    assert sm.can_transition(PacketState.READY, PacketState.CANCELLED)
    assert sm.can_transition(PacketState.RUNNING, PacketState.CANCELLED)
    assert sm.can_transition(PacketState.REJECTED, PacketState.CANCELLED)
    # Terminal states cannot transition
    assert not sm.can_transition(PacketState.CANCELLED, PacketState.READY)
    assert not sm.can_transition(PacketState.MERGED, PacketState.CANCELLED)
    assert not sm.can_transition(PacketState.FAILED, PacketState.CANCELLED)


def test_packet_lifecycle(test_db):
    with get_db() as db:
        db.add(Packet(
            id="PKT-001", feature_id="F1", wave_id="W01",
            slug="t", title="T", spec_json={}, state=PacketState.DRAFT.value,
        ))

    mark_ready("PKT-001")
    with get_db() as db:
        p = db.query(Packet).filter_by(id="PKT-001").first()
        assert p.state == PacketState.READY.value

    mark_running("PKT-001", "worker-1")
    with get_db() as db:
        p = db.query(Packet).filter_by(id="PKT-001").first()
        assert p.state == PacketState.RUNNING.value
        assert p.attempt_count == 1

    mark_accepted("PKT-001", ".grace/packets/PKT-001/runs/R01")
    with get_db() as db:
        p = db.query(Packet).filter_by(id="PKT-001").first()
        assert p.state == PacketState.ACCEPTED.value


def test_retry_rejected_packet(test_db):
    with get_db() as db:
        db.add(Packet(
            id="PKT-001", feature_id="F1", wave_id="W01",
            slug="t", title="T", spec_json={},
            state=PacketState.REJECTED.value, attempt_count=1, max_attempts=3,
        ))

    retry_packet("PKT-001")
    with get_db() as db:
        p = db.query(Packet).filter_by(id="PKT-001").first()
        assert p.state == PacketState.READY.value


def test_max_attempts_exceeded(test_db):
    with get_db() as db:
        db.add(Packet(
            id="PKT-001", feature_id="F1", wave_id="W01",
            slug="t", title="T", spec_json={},
            state=PacketState.REJECTED.value, attempt_count=3, max_attempts=3,
        ))

    with pytest.raises(StateTransitionError, match="Max attempts"):
        retry_packet("PKT-001")


def test_cannot_retry_non_rejected(test_db):
    with get_db() as db:
        db.add(Packet(
            id="PKT-001", feature_id="F1", wave_id="W01",
            slug="t", title="T", spec_json={},
            state=PacketState.READY.value, attempt_count=0, max_attempts=3,
        ))

    with pytest.raises(StateTransitionError, match="Can only retry REJECTED"):
        retry_packet("PKT-001")


def test_packet_not_found(test_db):
    with pytest.raises(ValueError, match="not found"):
        mark_ready("NONEXISTENT")
