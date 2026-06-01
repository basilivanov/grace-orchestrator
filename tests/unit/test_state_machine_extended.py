"""Block A: State Machine extended unit tests — 12 tests."""
import pytest
from grace_control.core.state_machine import PacketStateMachine, StateTransitionError
from grace_control.db.schema import PacketState

sm = PacketStateMachine()


def test_all_valid_transitions_enumerated():
    valid = [
        (PacketState.DRAFT, PacketState.READY),
        (PacketState.READY, PacketState.RUNNING),
        (PacketState.READY, PacketState.CANCELLED),
        (PacketState.RUNNING, PacketState.ACCEPTED),
        (PacketState.RUNNING, PacketState.REJECTED),
        (PacketState.RUNNING, PacketState.FAILED),
        (PacketState.RUNNING, PacketState.CANCELLED),
        (PacketState.REJECTED, PacketState.READY),
        (PacketState.REJECTED, PacketState.CANCELLED),
        (PacketState.ACCEPTED, PacketState.MERGED),
    ]
    for f, t in valid:
        assert sm.can_transition(f, t), f"{f.value} → {t.value} should be valid"


def test_all_invalid_transitions():
    invalid = [
        (PacketState.DRAFT, PacketState.RUNNING), (PacketState.DRAFT, PacketState.ACCEPTED),
        (PacketState.DRAFT, PacketState.MERGED), (PacketState.READY, PacketState.ACCEPTED),
        (PacketState.READY, PacketState.MERGED), (PacketState.RUNNING, PacketState.READY),
        (PacketState.RUNNING, PacketState.DRAFT),
    ]
    for term in (PacketState.MERGED, PacketState.FAILED, PacketState.CANCELLED):
        for s in PacketState:
            if s != term:
                invalid.append((term, s))
    for f, t in invalid:
        assert not sm.can_transition(f, t), f"{f.value} → {t.value} should be invalid"


def test_transition_raises_on_invalid():
    with pytest.raises(StateTransitionError, match="Invalid transition"):
        sm.transition(PacketState.DRAFT, PacketState.RUNNING)


def test_terminal_states_complete():
    assert sm.is_terminal(PacketState.MERGED)
    assert sm.is_terminal(PacketState.FAILED)
    assert sm.is_terminal(PacketState.CANCELLED)
    assert not sm.is_terminal(PacketState.DRAFT)
    assert not sm.is_terminal(PacketState.READY)
    assert not sm.is_terminal(PacketState.RUNNING)
    assert not sm.is_terminal(PacketState.ACCEPTED)
    assert not sm.is_terminal(PacketState.REJECTED)


def test_accepted_is_not_terminal():
    assert not sm.is_terminal(PacketState.ACCEPTED)
    assert sm.can_transition(PacketState.ACCEPTED, PacketState.MERGED)


def test_rejected_can_retry_or_cancel():
    assert sm.can_transition(PacketState.REJECTED, PacketState.READY)
    assert sm.can_transition(PacketState.REJECTED, PacketState.CANCELLED)
    assert not sm.can_transition(PacketState.REJECTED, PacketState.RUNNING)


def test_state_enum_values_lowercase():
    assert PacketState.DRAFT.value == "draft"
    assert PacketState.READY.value == "ready"
    assert PacketState.RUNNING.value == "running"
    assert PacketState.ACCEPTED.value == "accepted"
    assert PacketState.MERGED.value == "merged"
    assert PacketState.REJECTED.value == "rejected"
    assert PacketState.FAILED.value == "failed"
    assert PacketState.CANCELLED.value == "cancelled"


def test_state_roundtrip_from_string():
    assert PacketState("ready") == PacketState.READY
    assert PacketState("cancelled") == PacketState.CANCELLED
    assert PacketState("failed") == PacketState.FAILED


def test_all_8_states_exist():
    states = {s.value for s in PacketState}
    assert states == {"draft", "ready", "running", "accepted", "merged", "rejected", "failed", "cancelled"}
    assert len(states) == 8


def test_transition_idempotency_raises():
    with pytest.raises(StateTransitionError):
        sm.transition(PacketState.READY, PacketState.READY)


def test_from_unknown_state_raises():
    with pytest.raises(ValueError):
        PacketState("invalid_state")
