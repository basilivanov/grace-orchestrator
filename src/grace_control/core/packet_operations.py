# ############################################################################
# AI_HEADER: packet_operations
# ROLE: Thin wrappers over state machine for DB-backed packet state transitions.
# ############################################################################

# START_MODULE_CONTRACT
# purpose: Provide functions to transition packet states with DB persistence.
# inputs: packet_id, optional worker_id / evidence_path / reason / error.
# returns: None.
# side_effects: Updates packet state and attempt_count in DB.
# emitted_logs: None.
# error_behavior: Raises ValueError if packet not found, StateTransitionError if invalid.
# END_MODULE_CONTRACT

# START_MODULE_MAP
# mapping:
#   - function: mark_ready
#   - function: mark_running
#   - function: mark_accepted
#   - function: mark_rejected
#   - function: mark_failed
#   - function: retry_packet
# END_MODULE_MAP

from __future__ import annotations

from grace_control.core.state_machine import PacketStateMachine, StateTransitionError
from grace_control.db import get_db
from grace_control.db.schema import Packet, PacketState

_state_machine = PacketStateMachine()

#START_BLOCK_OPERATIONS

# START_FUNCTION_CONTRACT
# name: _get_packet
# purpose: Fetch packet from DB, raise ValueError if not found.
# inputs:
#   db: SQLAlchemy session.
#   packet_id: Packet ID string.
# returns: Packet ORM object.
# side_effects: None.
# emitted_logs: None.
# error_behavior: Raises ValueError if packet not found.
# END_FUNCTION_CONTRACT
def _get_packet(db, packet_id: str) -> Packet:
    packet = db.query(Packet).filter_by(id=packet_id).first()
    if not packet:
        raise ValueError(f"Packet {packet_id} not found")
    return packet


# START_FUNCTION_CONTRACT
# name: mark_ready
# purpose: Transition packet DRAFT → READY.
# inputs: packet_id.
# returns: None.
# side_effects: DB write.
# emitted_logs: None.
# error_behavior: Raises StateTransitionError if not in DRAFT.
# END_FUNCTION_CONTRACT
def mark_ready(packet_id: str) -> None:
    with get_db() as db:
        packet = _get_packet(db, packet_id)
        _state_machine.transition(PacketState(packet.state), PacketState.READY)
        packet.state = PacketState.READY.value


# START_FUNCTION_CONTRACT
# name: mark_running
# purpose: Transition packet READY → RUNNING, increment attempt_count.
# inputs: packet_id, worker_id.
# returns: None.
# side_effects: DB write (state + attempt_count).
# emitted_logs: None.
# error_behavior: Raises StateTransitionError if not in READY.
# END_FUNCTION_CONTRACT
def mark_running(packet_id: str, worker_id: str) -> None:
    with get_db() as db:
        packet = _get_packet(db, packet_id)
        _state_machine.transition(PacketState(packet.state), PacketState.RUNNING)
        packet.state = PacketState.RUNNING.value
        packet.attempt_count += 1


# START_FUNCTION_CONTRACT
# name: mark_accepted
# purpose: Transition packet RUNNING → ACCEPTED.
# inputs: packet_id, evidence_path.
# returns: None.
# side_effects: DB write.
# emitted_logs: None.
# error_behavior: Raises StateTransitionError if not in RUNNING.
# END_FUNCTION_CONTRACT
def mark_accepted(packet_id: str, evidence_path: str) -> None:
    with get_db() as db:
        packet = _get_packet(db, packet_id)
        _state_machine.transition(PacketState(packet.state), PacketState.ACCEPTED)
        packet.state = PacketState.ACCEPTED.value


# START_FUNCTION_CONTRACT
# name: mark_rejected
# purpose: Transition packet RUNNING → REJECTED.
# inputs: packet_id, reason.
# returns: None.
# side_effects: DB write.
# emitted_logs: None.
# error_behavior: Raises StateTransitionError if not in RUNNING.
# END_FUNCTION_CONTRACT
def mark_rejected(packet_id: str, reason: str) -> None:
    with get_db() as db:
        packet = _get_packet(db, packet_id)
        _state_machine.transition(PacketState(packet.state), PacketState.REJECTED)
        packet.state = PacketState.REJECTED.value


# START_FUNCTION_CONTRACT
# name: mark_failed
# purpose: Transition packet RUNNING → FAILED.
# inputs: packet_id, error_message.
# returns: None.
# side_effects: DB write.
# emitted_logs: None.
# error_behavior: Raises StateTransitionError if not in RUNNING.
# END_FUNCTION_CONTRACT
def mark_failed(packet_id: str, error_message: str) -> None:
    with get_db() as db:
        packet = _get_packet(db, packet_id)
        _state_machine.transition(PacketState(packet.state), PacketState.FAILED)
        packet.state = PacketState.FAILED.value


# START_FUNCTION_CONTRACT
# name: retry_packet
# purpose: Retry a rejected packet — REJECTED → READY if attempts remain.
# inputs: packet_id.
# returns: None.
# side_effects: DB write.
# emitted_logs: None.
# error_behavior: Raises StateTransitionError if not in REJECTED or max attempts reached.
# END_FUNCTION_CONTRACT
def retry_packet(packet_id: str) -> None:
    with get_db() as db:
        packet = _get_packet(db, packet_id)

        if PacketState(packet.state) != PacketState.REJECTED:
            raise StateTransitionError(
                f"Can only retry REJECTED packets, got {packet.state}"
            )

        if packet.attempt_count >= packet.max_attempts:
            raise StateTransitionError(
                f"Max attempts ({packet.max_attempts}) reached for {packet_id}"
            )

        _state_machine.transition(PacketState(packet.state), PacketState.READY)
        packet.state = PacketState.READY.value

#END_BLOCK_OPERATIONS
