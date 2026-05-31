# Execution Packet: FEAT-GRACE-CP-ADAPTER-W02-PACKET-EXECUTION-ADAPTER

## Objective

Create the PacketExecutionAdapter — the critical bridge between the new control plane (DB packets) and the legacy execution engine (run_e2e_packet).

The adapter must: load packet from DB → materialize EXECUTION_PACKET.md file → call legacy run_e2e_packet(dry_run=False, execute_agent=True) → parse E2EPacketRunnerResult → create PacketRun record → return ExecutionResult to worker.

CRITICAL: Adapter is STATELESS. It does NOT change packet state. Only claim/release endpoints own state transitions.

## Slice

- slice_id: `SLICE-ADAPTER`
- slice_slug: `packet-execution-adapter`
- feature_id: `FEAT-GRACE-CP-ADAPTER`
- packet_id: `FEAT-GRACE-CP-ADAPTER-W02-PACKET-EXECUTION-ADAPTER`
- wave_id: `W02`
- status: `ready`
- phase: `PHASE-1`
- depends_on: `FEAT-GRACE-CP-DB-W01-DB-SCHEMA, FEAT-GRACE-CP-STATE-W01-STATE-MACHINE`
- feature_dir: `grace/packets/FEAT-GRACE-CP-ADAPTER`

## Source Of Truth

- `CANONICAL_DECISIONS.md` §5 (adapter spec, state ownership, result mapping)
- `tasks/PHASE_1_CORE_REVISED.md` Task #22
- `src/prefect_grace/platform/e2e_packet_runner.py` — run_e2e_packet signature (lines 349-364)
- `src/prefect_grace/platform/packet_parser.py` — parse_packet_markdown, ParsedPacket
- `src/prefect_grace/platform/status_model.py` — DomainStatus, E2EPacketRunnerResult
- `development-plan.xml` — FEAT-GRACE-ADAPTER
- `knowledge-graph.xml` — CONCEPT-ADAPTER, REL-006, REL-007, REL-014, REL-015

## Impacted Modules

- `M-GRACE-CP-ADAPTER`

## Allowed Write Scope

- `src/grace_control/adapters/__init__.py`
- `src/grace_control/adapters/packet_executor.py`
- `tests/test_packet_executor.py`
- `grace/packets/FEAT-GRACE-CP-ADAPTER/**`

## Frozen Scope

- `src/prefect_grace/**` — legacy, read-only (imports only)
- `src/grace_control/db/**` — read-only (imports only)
- `src/grace_control/core/state_machine.py` — read-only
- `src/grace_control/api/**`
- `src/grace_control/worker/**`
- `src/grace_control/cli/**`

## Must Preserve

- Adapter is STATELESS: no mark_running, mark_accepted, mark_rejected, mark_failed calls
- run_e2e_packet called with dry_run=False AND execute_agent=True (both required!)
- Real E2EPacketRunnerResult type, not dict
- Correct mapping: ok+accepted→ACCEPTED, rework_required/blocked/scope_blocked→REJECTED, agent_failed/verifier_failed/reviewer_failed/runner_error/handoff_error→FAILED
- Materialized packet file MUST be parseable by parse_packet_markdown
- run_e2e_packet is synchronous — run in asyncio.run_in_executor

### GRACE Canon Compliance (обязательно)

Весь новый код должен соответствовать GRACE Canon (`prompts/canon_digest_prompt.md`). Кратко:

- **AI_HEADER**: `# AI_HEADER: packet_executor` + `# ROLE: Bridge between DB packets and legacy run_e2e_packet`
- **MODULE_CONTRACT**: purpose, inputs, returns, side_effects, emitted_logs, error_behavior
- **MODULE_MAP**: PacketExecutionAdapter, ExecutionResult
- **FUNCTION_CONTRACT**: execute, _materialize_packet, _call_legacy_runner, _parse_result, _save_evidence
- **Блоки**: `#START_BLOCK_MODELS` (ExecutionResult), `#START_BLOCK_ADAPTER` (PacketExecutionAdapter)
- **Лимиты**: файл ≤ 1000 строк, функция ≤ 4000 токенов
- **Логирование**: `log_event()` с packet_id, `trace_context(trace_id=packet_id)`
- **T0**: `ruff check`, `ruff format --check`, `mypy`, `compileall`

## Required Design Decisions

### 1. ExecutionResult model

```python
from pydantic import BaseModel
class ExecutionResult(BaseModel):
    accepted: bool
    reason: str | None
    evidence_path: str
    duration_ms: int
    domain_status: str
```

### 2. Real run_e2e_packet signature

```python
from prefect_grace.platform.e2e_packet_runner import run_e2e_packet, E2EPacketRunnerResult

result: E2EPacketRunnerResult = run_e2e_packet(
    project_root=Path,
    packet_path=Path,
    state_root=Path,
    worktree_root=Path,
    project_key="grace-cp",
    attempt=packet.attempt_count + 1,
    base_ref="HEAD",
    dry_run=False,        # MUST be False — real execution
    execute_agent=True,   # MUST be True — live agents
    timeout_seconds=3600,
    keep_worktree=True,
)
```

### 3. Result mapping (E2EPacketRunnerResult → ExecutionResult)

```python
accepted = result.ok and result.domain_status == "accepted"

if result.domain_status in ("rework_required", "blocked", "scope_blocked"):
    accepted = False  # REJECTED by release endpoint
elif result.domain_status in ("agent_failed", "verifier_failed",
                               "reviewer_failed", "runner_error", "handoff_error"):
    accepted = False  # FAILED by release endpoint
```

### 4. Materialized packet format

Must produce markdown with `# Execution Packet: {id}`, `## Objective`, `## Specification` (YAML block), `## Acceptance Profile`. Must be parseable by `parse_packet_markdown()`.

## Implementation Requirements

1. `src/grace_control/adapters/packet_executor.py`:
   - `ExecutionResult(BaseModel)` — accepted, reason, evidence_path, duration_ms, domain_status
   - `PacketExecutionAdapter` class:
     - `__init__(project_root, state_root, worktree_root)`
     - `async execute(packet_id, worker_id) -> ExecutionResult`
     - `_materialize_packet(packet) -> Path`
     - `async _call_legacy_runner(packet_path) -> E2EPacketRunnerResult`
     - `_parse_result(E2EPacketRunnerResult) -> ExecutionResult`
     - `_save_evidence(packet_id, run_number, result_dict) -> str`

2. `tests/test_packet_executor.py`:
   - test_materialize_packet_compatible_with_parser
   - test_result_mapping_accepted
   - test_result_mapping_rejected
   - test_result_mapping_failed
   - test_adapter_has_no_state_transition_calls (structural check)
   - test_execute_agent_flag_is_true

## Acceptance Criteria

- [ ] PacketExecutionAdapter implemented in src/grace_control/adapters/
- [ ] Adapter has ZERO calls to mark_running/mark_accepted/mark_rejected/mark_failed
- [ ] Materialized packet parseable by parse_packet_markdown
- [ ] run_e2e_packet called with dry_run=False AND execute_agent=True
- [ ] E2EPacketRunnerResult correctly mapped to ExecutionResult
- [ ] PacketRun record created with status + evidence_path
- [ ] All tests pass: `pytest tests/test_packet_executor.py -v`

## Verification

```bash
pytest tests/test_packet_executor.py -v

# Structural check: adapter has no state transition calls
python3 -c "
import ast, sys
with open('src/grace_control/adapters/packet_executor.py') as f:
    tree = ast.parse(f.read())
for node in ast.walk(tree):
    if isinstance(node, ast.Call):
        name = getattr(node.func, 'id', '') or getattr(getattr(node.func, 'attr', None), '', '')
        if name in ('mark_ready', 'mark_running', 'mark_accepted', 'mark_rejected', 'mark_failed'):
            print(f'ERROR: adapter calls {name} at line {node.lineno}')
            sys.exit(1)
print('OK: adapter is stateless')
"

ruff check src/grace_control/adapters/
mypy src/grace_control/adapters/
```

## Expected Evidence

- `test-results/adapter.xml`
- Structural check output (adapter is stateless)
- Proof that materialized packet is parseable by parse_packet_markdown

## Escalation Triggers

- run_e2e_packet signature changed in legacy code
- parse_packet_markdown cannot parse materialized file
- Executor sync call blocks event loop (must use run_in_executor)
- ImportError on prefect_grace modules

## Reviewer Gate

Reviewer must reject if:
- Adapter calls any state transition function (mark_*)
- execute_agent=False or dry_run=True (fake execution)
- E2EPacketRunnerResult mapping is wrong (rework_required → accepted)
- Missing GRACE contracts
- Materialized packet cannot be parsed by legacy parser
