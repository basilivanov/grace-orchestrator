# Execution Packet: FEAT-GRACE-CP-WORKER-W03-WORKER-LOOP

## Objective

Create the worker loop: register worker → claim packet (POST /api/packets/claim) → execute via PacketExecutionAdapter → release result (POST /api/packets/{id}/release) → loop. Heartbeat every 30s. Graceful shutdown on SIGINT.

Worker is the runtime client that drives the entire vertical slice. It does NOT change packet state directly — it delegates to claim/release endpoints.

## Slice

- slice_id: `SLICE-WORKER`
- slice_slug: `worker-loop`
- feature_id: `FEAT-GRACE-CP-WORKER`
- packet_id: `FEAT-GRACE-CP-WORKER-W03-WORKER-LOOP`
- wave_id: `W03`
- status: `ready`
- phase: `PHASE-2`
- depends_on: `FEAT-GRACE-CP-API-W02-FASTAPI-SERVER`
- feature_dir: `grace/packets/FEAT-GRACE-CP-WORKER`

## Source Of Truth

- `CANONICAL_DECISIONS.md` §5 (execution flow), §9 (vertical slice)
- `tasks/PHASE_2_API_WORKER_REVISED.md` Task #21
- `development-plan.xml` — FEAT-GRACE-WORKER
- `knowledge-graph.xml` — CONCEPT-WORKER, REL-004, REL-005, REL-006

## Impacted Modules

- `M-GRACE-CP-WORKER`

## Allowed Write Scope

- `src/grace_control/worker/__init__.py`
- `src/grace_control/worker/api_client.py`
- `src/grace_control/worker/worker.py`
- `tests/test_worker.py`
- `grace/packets/FEAT-GRACE-CP-WORKER/**`

## Frozen Scope

- `src/prefect_grace/**` — legacy code
- `src/grace_control/db/**` — read-only
- `src/grace_control/api/**` — read-only (API is server, worker is client)
- `src/grace_control/core/state_machine.py` — read-only
- `src/grace_control/adapters/**` — import only (worker delegates to adapter)
- `src/grace_control/cli/**`

## Must Preserve

- Worker does NOT change packet state (claim/release endpoints own transitions)
- Worker calls adapter.execute() — adapter returns ExecutionResult
- Worker calls release endpoint with result (accepted/rejected/failed)
- Heartbeat every 30 seconds
- Single worker in MVP-0 (no parallel execution)
- Graceful shutdown: cancel heartbeat task, close httpx client
- Worker ID: auto-generated (worker-{uuid8}) or from --worker-id flag

### GRACE Canon Compliance (обязательно)

Весь новый код должен соответствовать GRACE Canon (`prompts/canon_digest_prompt.md`). Кратко:

- **AI_HEADER**: `# AI_HEADER: worker` + `# ROLE: Worker loop for GRACE Control Plane`
- **MODULE_CONTRACT**: purpose, inputs, returns, side_effects, emitted_logs, error_behavior
- **MODULE_MAP**: Worker, WorkerAPIClient, main
- **FUNCTION_CONTRACT**: start, _main_loop, _heartbeat_loop, _execute_packet
- **Блоки**: `#START_BLOCK_API_CLIENT`, `#START_BLOCK_WORKER`
- **Лимиты**: файл ≤ 1000 строк, функция ≤ 4000 токенов
- **Логирование**: `log_event()` с worker_id + packet_id, `trace_context(trace_id=packet_id)`
- **T0**: `ruff check`, `ruff format --check`, `mypy`, `compileall`

## Required Design Decisions

### 1. WorkerAPIClient (httpx-based)

```python
class WorkerAPIClient:
    def __init__(self, base_url: str = "http://localhost:8042"):
        self.client = httpx.AsyncClient(base_url=base_url, timeout=30.0)

    async def register(self, worker_id: str) -> dict
    async def heartbeat(self, worker_id: str) -> dict
    async def claim_packet(self, worker_id: str) -> PacketClaim | None
    async def release_packet(self, packet_id: str, worker_id: str,
                             status: str, result: dict) -> dict
    async def close(self)
```

### 2. Worker Loop

```python
class Worker:
    def __init__(self, worker_id=None, api_url="http://localhost:8042",
                 project_root=None, state_root=None, worktree_root=None):
        self.executor = PacketExecutionAdapter(project_root, state_root, worktree_root)

    async def start(self):
        await api_client.register(worker_id)
        heartbeat_task = asyncio.create_task(_heartbeat_loop())
        await _main_loop()
        heartbeat_task.cancel()
        await api_client.close()

    async def _main_loop(self):
        while self.running:
            claim = await api_client.claim_packet(worker_id)
            if claim is None: await asyncio.sleep(5); continue
            result = await executor.execute(claim.packet_id, worker_id)
            status = "accepted" if result.accepted else "rejected"
            await api_client.release_packet(claim.packet_id, worker_id, status, result.dict())
```

### 3. Heartbeat

Send POST /api/workers/heartbeat every 30 seconds. On failure, log warning, continue.

## Implementation Requirements

1. `src/grace_control/worker/api_client.py` — WorkerAPIClient with 5 async methods
2. `src/grace_control/worker/worker.py` — Worker class with start, _main_loop, _heartbeat_loop, _execute_packet
3. `tests/test_worker.py`:
   - test_worker_register
   - test_worker_heartbeat
   - test_claim_no_packets (returns None)
   - test_claim_packet_with_lease
   - test_release_packet_accepted
   - test_release_packet_rejected

## Acceptance Criteria

- [ ] Worker registers with API
- [ ] Worker sends heartbeat every 30s
- [ ] Worker claims READY packet (lease created, state→RUNNING)
- [ ] Worker executes via PacketExecutionAdapter
- [ ] Worker releases result (state→ACCEPTED/REJECTED/FAILED)
- [ ] No packets available → worker sleeps 5s, retries
- [ ] SIGINT → graceful shutdown (cancel tasks, close client)
- [ ] Worker does NOT import or call state transition functions directly
- [ ] All tests pass: `pytest tests/test_worker.py -v`

## Verification

```bash
# Start API (separate terminal)
grace api start &
API_PID=$!
sleep 2

# Register worker
curl -s -X POST http://localhost:8042/api/workers/register \
  -H "Content-Type: application/json" \
  -d '{"worker_id":"test-worker"}'

# Heartbeat
curl -s -X POST http://localhost:8042/api/workers/heartbeat \
  -H "Content-Type: application/json" \
  -d '{"worker_id":"test-worker"}'

# Worker list
curl -s http://localhost:8042/api/workers/ | python3 -m json.tool

kill $API_PID

# Unit tests
pytest tests/test_worker.py -v

ruff check src/grace_control/worker/
mypy src/grace_control/worker/
```

## Expected Evidence

- `test-results/worker.xml`
- Worker registration + heartbeat output
- Proof worker loop runs without state transition calls

## Escalation Triggers

- API server not reachable
- Claim returns non-None but packet is not READY
- Adapter.execute() raises unexpected exception
- Release endpoint returns error
- Heartbeat fails continuously (>5 failures)

## Reviewer Gate

Reviewer must reject if:
- Worker directly calls mark_running/mark_accepted/mark_rejected/mark_failed
- Worker ignores heartbeat failures
- No graceful shutdown (SIGINT hangs)
- Adapter called with wrong flags (not execute_agent=True)
- Missing GRACE contracts
- assert or bare except without logging
