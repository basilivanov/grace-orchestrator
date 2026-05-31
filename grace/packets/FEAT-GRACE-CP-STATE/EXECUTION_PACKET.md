# Execution Packet: FEAT-GRACE-CP-STATE-W01-STATE-MACHINE

## Objective

Implement the Packet State Machine: 8 canonical states with validated transitions, terminal state detection, packet operations (mark_ready, mark_running, mark_accepted, mark_rejected, mark_failed, retry_packet), and StateTransitionError for invalid transitions.

CANCELLED transitions are reserved for post-MVP — no endpoint creates CANCELLED state in MVP-0.

## Slice

- slice_id: `SLICE-STATE-MACHINE`
- slice_slug: `state-machine`
- feature_id: `FEAT-GRACE-CP-STATE`
- packet_id: `FEAT-GRACE-CP-STATE-W01-STATE-MACHINE`
- wave_id: `W01`
- status: `ready`
- phase: `PHASE-1`
- depends_on: `FEAT-GRACE-CP-DB-W01-DB-SCHEMA`
- feature_dir: `grace/packets/FEAT-GRACE-CP-STATE`

## Source Of Truth

- `CANONICAL_DECISIONS.md` §2 (canonical states), §5 (state ownership rules)
- `tasks/PHASE_1_CORE_REVISED.md` Task #11
- `development-plan.xml` — FEAT-GRACE-STATE
- `knowledge-graph.xml` — CONCEPT-STATE-MACHINE

## Impacted Modules

- `M-GRACE-CP-STATE`

## Allowed Write Scope

- `src/grace_control/core/__init__.py`
- `src/grace_control/core/state_machine.py`
- `src/grace_control/core/packet_operations.py`
- `tests/test_state_machine.py`
- `grace/packets/FEAT-GRACE-CP-STATE/**`

## Frozen Scope

- `src/prefect_grace/**` — legacy code
- `src/grace_control/db/**` — read-only (imports only)
- `src/grace_control/api/**`
- `src/grace_control/worker/**`
- `src/grace_control/cli/**`
- `src/grace_control/adapters/**`

## Must Preserve

- 8 canonical states only (no TESTING, REVIEW, BLOCKED, NEEDS_REWORK states)
- CANCELLED = reserved for post-MVP (no transitions INTO CANCELLED in MVP-0)
- State transitions validated before commit
- Terminal states: MERGED, FAILED, CANCELLED
- Mutable only from non-terminal states
- No direct DB writes in state machine — use packet_operations

### GRACE Canon Compliance (обязательно)

Весь новый код должен соответствовать GRACE Canon (`prompts/canon_digest_prompt.md`). Кратко:

- **AI_HEADER**: первая строка `# AI_HEADER: <имя>` + `# ROLE: <описание>`
- **MODULE_CONTRACT**: purpose, inputs, returns, side_effects, emitted_logs, error_behavior
- **MODULE_MAP**: перечень всех классов/функций
- **FUNCTION_CONTRACT**: у каждой функции
- **Блоки**: `#START_BLOCK_<NAME>` / `#END_BLOCK_<NAME>`
- **Лимиты**: файл ≤ 1000 строк, функция ≤ 4000 токенов
- **Логирование**: `log_event()` вместо `print()`, `trace_context()` для сквозного trace_id
- **T0**: `ruff check`, `ruff format --check`, `mypy`, `compileall`

## Required Design Decisions

### 1. PacketStateMachine class

```python
class PacketStateMachine:
    VALID_TRANSITIONS = {
        PacketState.DRAFT: [PacketState.READY],
        PacketState.READY: [PacketState.RUNNING],
        PacketState.RUNNING: [PacketState.ACCEPTED, PacketState.REJECTED, PacketState.FAILED],
        PacketState.REJECTED: [PacketState.READY],
        PacketState.ACCEPTED: [PacketState.MERGED],  # post-MVP
        PacketState.MERGED: [],
        PacketState.FAILED: [],
        PacketState.CANCELLED: [],
    }

    TERMINAL_STATES = {PacketState.MERGED, PacketState.FAILED, PacketState.CANCELLED}
```

### 2. StateTransitionError

```python
class StateTransitionError(Exception):
    pass
```

### 3. Packet operations (thin wrappers over state machine)

```python
def mark_ready(packet_id)       # DRAFT → READY
def mark_running(packet_id, wid)# READY → RUNNING
def mark_accepted(packet_id, ev)# RUNNING → ACCEPTED
def mark_rejected(packet_id, r) # RUNNING → REJECTED
def mark_failed(packet_id, err) # RUNNING → FAILED
def retry_packet(packet_id)     # REJECTED → READY (if attempts < max)
```

Note: These are NOT used by adapter. They're used by API endpoints (claim/release) and manual operations.

## Implementation Requirements

1. `src/grace_control/core/state_machine.py`:
   - `PacketStateMachine` class
   - `can_transition(from_state, to_state) -> bool`
   - `transition(packet, to_state, reason) -> None`
   - `is_terminal(state) -> bool`

2. `src/grace_control/core/packet_operations.py`:
   - Six operation functions (mark_ready, mark_running, mark_accepted, mark_rejected, mark_failed, retry_packet)
   - Each opens get_db() context, finds packet, validates transition

3. `tests/test_state_machine.py`:
   - test_valid_transitions
   - test_invalid_transitions
   - test_terminal_states
   - test_packet_lifecycle (DRAFT→READY→RUNNING→ACCEPTED)
   - test_retry_rejected_packet
   - test_max_attempts_exceeded
   - test_no_cancelled_transitions (reserved)

## Acceptance Criteria

- [ ] PacketStateMachine with VALID_TRANSITIONS dict
- [ ] StateTransitionError raised on invalid transition
- [ ] Terminal states: MERGED, FAILED, CANCELLED
- [ ] No transitions INTO CANCELLED (reserved)
- [ ] packet_operations.py with 6 functions
- [ ] retry_packet checks max_attempts
- [ ] All tests pass: `pytest tests/test_state_machine.py -v`

## Verification

```bash
pytest tests/test_state_machine.py -v

python3 -c "
from grace_control.db.schema import PacketState
from grace_control.core.state_machine import PacketStateMachine
sm = PacketStateMachine()
# Verify valid
assert sm.can_transition(PacketState.DRAFT, PacketState.READY)
assert sm.can_transition(PacketState.READY, PacketState.RUNNING)
assert sm.can_transition(PacketState.RUNNING, PacketState.ACCEPTED)
# Verify invalid
assert not sm.can_transition(PacketState.DRAFT, PacketState.RUNNING)
assert not sm.can_transition(PacketState.ACCEPTED, PacketState.READY)
# Verify terminal
assert sm.is_terminal(PacketState.MERGED)
assert sm.is_terminal(PacketState.FAILED)
assert not sm.is_terminal(PacketState.RUNNING)
print('OK: state machine valid')
"

ruff check src/grace_control/core/
ruff format --check src/grace_control/core/
mypy src/grace_control/core/
```

## Expected Evidence

- `test-results/state-machine.xml`
- Transition validation output
- ruff/mypy clean output

## Escalation Triggers

- CANCELLED appears in VALID_TRANSITIONS (wrong — reserved)
- More than 8 states defined
- Terminal states don't prevent further transitions
- ImportError on grace_control.db.schema

## Reviewer Gate

Reviewer must reject if:
- CANCELLED has valid transitions (not reserved)
- State machine has fewer or more than 8 states
- Terminal states are wrong (MERGED should be terminal, READY should not)
- Missing GRACE contracts
- retry_packet ignores max_attempts
