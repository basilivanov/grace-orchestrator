# ############################################################################
# AI_HEADER: state_machine
# ROLE: Packet state machine — 8 canonical states, validated transitions.
# ############################################################################

# START_MODULE_CONTRACT
# purpose: Validate packet state transitions against canonical rules.
# inputs: PacketState (from grace_control.db.schema).
# returns: Boolean (can_transition), raises StateTransitionError on invalid.
# side_effects: None (pure validation).
# emitted_logs: None.
# error_behavior: Raises StateTransitionError on invalid transition.
# END_MODULE_CONTRACT

# START_MODULE_MAP
# mapping:
#   - class: StateTransitionError
#   - class: PacketStateMachine
# END_MODULE_MAP

from __future__ import annotations

from grace_control.db.schema import PacketState

#START_BLOCK_ERROR
class StateTransitionError(Exception):
    """Raised when an invalid state transition is attempted."""
#END_BLOCK_ERROR

#START_BLOCK_STATE_MACHINE
class PacketStateMachine:
    """
    Validates transitions between 8 canonical packet states.
    CANCELLED transitions reserved for post-MVP (no endpoint creates CANCELLED in MVP-0).

    Valid transitions:
      DRAFT → READY
      READY → RUNNING
      RUNNING → ACCEPTED | REJECTED | FAILED
      REJECTED → READY (retry)
      ACCEPTED → MERGED (post-MVP)
    """

    # START_FUNCTION_CONTRACT
    # name: VALID_TRANSITIONS
    # purpose: Define all valid state transitions.
    # inputs: None.
    # returns: Dict mapping each state to its valid next states.
    # side_effects: None.
    # emitted_logs: None.
    # error_behavior: None.
    # END_FUNCTION_CONTRACT
    VALID_TRANSITIONS: dict[PacketState, list[PacketState]] = {
        PacketState.DRAFT: [PacketState.READY],
        PacketState.READY: [PacketState.RUNNING, PacketState.CANCELLED],
        PacketState.RUNNING: [
            PacketState.ACCEPTED,
            PacketState.REJECTED,
            PacketState.FAILED,
            PacketState.CANCELLED,
        ],
        PacketState.REJECTED: [PacketState.READY, PacketState.CANCELLED],
        PacketState.ACCEPTED: [PacketState.MERGED],
        PacketState.MERGED: [],
        PacketState.FAILED: [],
        PacketState.CANCELLED: [],
    }

    # START_FUNCTION_CONTRACT
    # name: TERMINAL_STATES
    # purpose: Define states from which no further transitions are allowed.
    # inputs: None.
    # returns: Set of terminal PacketState values.
    # side_effects: None.
    # emitted_logs: None.
    # error_behavior: None.
    # END_FUNCTION_CONTRACT
    TERMINAL_STATES: set[PacketState] = {
        PacketState.MERGED,
        PacketState.FAILED,
        PacketState.CANCELLED,
    }

    # START_FUNCTION_CONTRACT
    # name: can_transition
    # purpose: Check if transition from_state → to_state is valid.
    # inputs:
    #   from_state: Current PacketState.
    #   to_state: Desired PacketState.
    # returns: True if valid, False otherwise.
    # side_effects: None.
    # emitted_logs: None.
    # error_behavior: Never raises.
    # END_FUNCTION_CONTRACT
    def can_transition(self, from_state: PacketState, to_state: PacketState) -> bool:
        return to_state in self.VALID_TRANSITIONS.get(from_state, [])

    # START_FUNCTION_CONTRACT
    # name: transition
    # purpose: Validate and apply a state transition.
    # inputs:
    #   from_state: Current PacketState.
    #   to_state: Desired PacketState.
    # returns: None.
    # side_effects: None.
    # emitted_logs: None.
    # error_behavior: Raises StateTransitionError if transition is invalid.
    # END_FUNCTION_CONTRACT
    def transition(
        self,
        from_state: PacketState,
        to_state: PacketState,
    ) -> None:
        if not self.can_transition(from_state, to_state):
            raise StateTransitionError(
                f"Invalid transition: {from_state.value} → {to_state.value}"
            )

    # START_FUNCTION_CONTRACT
    # name: is_terminal
    # purpose: Check if a state is terminal.
    # inputs:
    #   state: PacketState to check.
    # returns: True if terminal, False otherwise.
    # side_effects: None.
    # emitted_logs: None.
    # error_behavior: Never raises.
    # END_FUNCTION_CONTRACT
    def is_terminal(self, state: PacketState) -> bool:
        return state in self.TERMINAL_STATES

#END_BLOCK_STATE_MACHINE
