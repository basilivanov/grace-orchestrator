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
    Validates transitions between 10 canonical packet states.
    CANCELLED transitions reserved for post-MVP (no endpoint creates CANCELLED in MVP-0).
    BLOCKED is deprecated alias for BLOCKED_FINAL — kept for back-compat with existing rows.

    Valid transitions:
      DRAFT → READY
      READY → RUNNING
      RUNNING → ACCEPTED | REJECTED | BLOCKED_RECOVERABLE | BLOCKED_FINAL | FAILED
      REJECTED → READY (retry) | BLOCKED_FINAL | BLOCKED_RECOVERABLE | CANCELLED
      BLOCKED_RECOVERABLE → READY (recovery) | BLOCKED_FINAL | CANCELLED
      BLOCKED_FINAL → (terminal)
      BLOCKED → READY (back-compat alias, deprecated)
      ACCEPTED → MERGED
      MERGED → (terminal)
      FAILED → (terminal)
      CANCELLED → (terminal)
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
            PacketState.BLOCKED_RECOVERABLE,
            PacketState.BLOCKED_FINAL,
            PacketState.FAILED,
            PacketState.CANCELLED,
        ],
        PacketState.REJECTED: [
            PacketState.READY,
            PacketState.BLOCKED_RECOVERABLE,
            PacketState.BLOCKED_FINAL,
            PacketState.CANCELLED,
        ],
        PacketState.BLOCKED: [PacketState.READY],  # back-compat alias → BLOCKED_FINAL
        PacketState.BLOCKED_RECOVERABLE: [
            PacketState.READY,
            PacketState.BLOCKED_FINAL,
            PacketState.CANCELLED,
        ],
        PacketState.BLOCKED_FINAL: [],
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
        PacketState.BLOCKED_FINAL,
        PacketState.CANCELLED,
    }

    # Aliases for soft compat — the deprecated "blocked" string maps to BLOCKED_FINAL
    DEPRECATED_ALIASES: dict[str, PacketState] = {
        "blocked": PacketState.BLOCKED_FINAL,
    }

    # START_FUNCTION_CONTRACT
    # name: normalize_state
    # purpose: Map legacy/deprecated state string to canonical PacketState.
    # inputs:
    #   raw: State string from DB or external source.
    # returns: Canonical PacketState (defaults to PacketState(raw) when valid).
    # side_effects: None.
    # emitted_logs: None.
    # error_behavior: Returns the raw value as-is if it cannot be normalized.
    # END_FUNCTION_CONTRACT
    @classmethod
    def normalize_state(cls, raw: str) -> PacketState:
        if raw in cls.DEPRECATED_ALIASES:
            return cls.DEPRECATED_ALIASES[raw]
        try:
            return PacketState(raw)
        except ValueError:
            return PacketState.BLOCKED_FINAL  # safe fallback for unknown legacy values

    # START_FUNCTION_CONTRACT
    # name: write_normalize
    # purpose: Map canonical PacketState to its persistable string form (BLOCKED is deprecated).
    # inputs:
    #   state: Canonical PacketState to write.
    # returns: String to persist. For canonical BLOCKED state, never write the deprecated alias.
    # side_effects: None.
    # emitted_logs: None.
    # error_behavior: Returns state.value as-is for all other states.
    # END_FUNCTION_CONTRACT
    @classmethod
    def write_normalize(cls, state: PacketState) -> str:
        return state.value

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
