"""Block G: Packet Operations extended unit tests — 5 tests."""
import pytest

from grace_control.core.packet_operations import (
    mark_failed, mark_ready, mark_rejected, mark_running, retry_packet,
)
from grace_control.core.state_machine import StateTransitionError
from grace_control.db import get_db
from grace_control.db.schema import PacketState
from tests.conftest import make_packet


def test_mark_ready_wrong_state_raises(db):
    with get_db() as d:
        make_packet(d, pid="P1", state=PacketState.RUNNING.value)
    with pytest.raises(StateTransitionError):
        mark_ready("P1")


def test_mark_running_increments_attempt(db):
    with get_db() as d:
        make_packet(d, pid="P1", state=PacketState.READY.value, attempt=0)
    mark_running("P1", "w1")
    with get_db() as d:
        from grace_control.db.schema import Packet
        p = d.query(Packet).filter_by(id="P1").first()
        assert p.state == PacketState.RUNNING.value
        assert p.attempt_count == 1


def test_mark_running_twice_raises(db):
    with get_db() as d:
        make_packet(d, pid="P1", state=PacketState.READY.value)
    mark_running("P1", "w1")
    with pytest.raises(StateTransitionError):
        mark_running("P1", "w1")


def test_mark_failed_from_running(db):
    with get_db() as d:
        make_packet(d, pid="P1", state=PacketState.RUNNING.value)
    mark_failed("P1", "error msg")
    with get_db() as d:
        from grace_control.db.schema import Packet
        assert d.query(Packet).filter_by(id="P1").first().state == PacketState.FAILED.value


def test_retry_resets_to_ready_not_draft(db):
    with get_db() as d:
        make_packet(d, pid="P1", state=PacketState.REJECTED.value, attempt=1, max_att=3)
    retry_packet("P1")
    with get_db() as d:
        from grace_control.db.schema import Packet
        assert d.query(Packet).filter_by(id="P1").first().state == PacketState.READY.value
