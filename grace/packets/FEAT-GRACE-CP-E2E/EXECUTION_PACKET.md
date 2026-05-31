# Execution Packet: FEAT-GRACE-CP-E2E-W04-E2E-VERTICAL-SLICE

## Objective

Create the E2E test for MVP-0 vertical slice: API server starts → architect creates plan (packets in READY) → worker claims → adapter executes → release → packet state = ACCEPTED.

The test proves the full vertical slice works. It requires API + DB + adapter + worker working together. Shared DB via GRACE_DB_URL env var.

## Slice

- slice_id: `SLICE-E2E`
- slice_slug: `e2e-vertical-slice`
- feature_id: `FEAT-GRACE-CP-E2E`
- packet_id: `FEAT-GRACE-CP-E2E-W04-E2E-VERTICAL-SLICE`
- wave_id: `W04`
- status: `ready`
- phase: `PHASE-3`
- depends_on: `FEAT-GRACE-CP-WORKER-W03-WORKER-LOOP, FEAT-GRACE-CP-CLI-W03-CLI-COMMANDS`
- feature_dir: `grace/packets/FEAT-GRACE-CP-E2E`

## Source Of Truth

- `CANONICAL_DECISIONS.md` §9 (vertical slice definition)
- `tasks/PHASE_3_CLI_E2E_REVISED.md` Task #20
- `development-plan.xml` — FEAT-GRACE-E2E
- `verification-matrix.md` — SLICE-E2E

## Impacted Modules

- `M-GRACE-CP-E2E`

## Allowed Write Scope

- `tests/test_e2e_mvp0.py`
- `scripts/verify_mvp0.sh`
- `grace/packets/FEAT-GRACE-CP-E2E/**`

## Frozen Scope

- `src/prefect_grace/**` — legacy code
- `src/grace_control/**` — all source code (test only exercises, does not modify)
- `grace/packets/FEAT-GRACE-CP-{DB,STATE,ADAPTER,API,WORKER,CLI}/**`

## Must Preserve

- Test uses GRACE_DB_URL to share DB between API server and test process
- Test verifies full flow: architect plan → claim → execute → release → ACCEPTED
- Test DOES NOT manually call mark_ready (architect creates READY)
- Test DOES NOT modify source code — only exercises existing components
- Test waits up to 60s for worker to complete (polling)
- Test verifies PacketRun record exists with evidence_path
- Cleanup: terminate API server + worker processes

### GRACE Canon Compliance (обязательно)

Тестовый файл должен содержать GRACE контракты:
- **AI_HEADER**: `# AI_HEADER: test_e2e_mvp0` + `# ROLE: MVP-0 vertical slice E2E test`
- **MODULE_CONTRACT**: purpose, test flow, fixtures
- **FUNCTION_CONTRACT**: у каждого теста — что проверяет, какие компоненты задействует
- **Блоки**: `#START_BLOCK_FIXTURES`, `#START_BLOCK_TESTS`
- **T0**: ruff + mypy на тестовый файл

## Required Design Decisions

### 1. API Server Fixture (shared DB)

```python
@pytest.fixture
async def api_server(tmp_path):
    db_url = f"sqlite:///{tmp_path}/test.db"
    os.environ["GRACE_DB_URL"] = db_url

    def run_server():
        uvicorn.run(app, host="127.0.0.1", port=8043)

    proc = Process(target=run_server)
    proc.start()
    await asyncio.sleep(2)

    yield "http://localhost:8043", db_url

    proc.terminate()
    proc.join()
```

### 2. E2E Test Flow

```python
@pytest.mark.asyncio
async def test_mvp0_vertical_slice(api_server, tmp_path):
    api_url, db_url = api_server
    init_db(db_url)

    # 1. Create feature plan (packets in READY)
    response = await client.post(f"{api_url}/api/architect/plan", json=feature_spec)
    packet_id = response.json()["data"]["packets"][0]
    assert packet_state(packet_id) == "ready"

    # 2. Start worker in background
    worker_task = asyncio.create_task(worker.start())

    # 3. Wait for execution (poll, max 60s)
    while time.time() - start < 60:
        state = packet_state(packet_id)
        if state in ("accepted", "rejected", "failed"):
            break
        await asyncio.sleep(2)

    # 4. Stop worker
    worker.running = False; worker_task.cancel()

    # 5. Verify
    assert packet_state(packet_id) == "accepted"
    runs = get_runs(packet_id)
    assert len(runs) > 0
    assert runs[0]["status"] == "accepted"
    assert runs[0]["evidence_path"] is not None
```

### 3. Verification Script

```bash
#!/bin/bash
set -e
echo "MVP-0 E2E Verification"
pytest tests/test_e2e_mvp0.py -v
echo "PASSED"
```

## Implementation Requirements

1. `tests/test_e2e_mvp0.py`:
   - api_server fixture with GRACE_DB_URL + multiprocessing
   - test_mvp0_vertical_slice: full flow
   - test_packet_state_lifecycle: DRAFT?→READY→RUNNING→ACCEPTED
   - test_e2e_json_output: verify JSON envelope format

2. `scripts/verify_mvp0.sh`:
   - Start API → run E2E → stop API
   - Exit 0 on success, exit 1 on failure

## Acceptance Criteria

- [ ] E2E test passes: `pytest tests/test_e2e_mvp0.py -v`
- [ ] Full flow: architect plan → worker claim → execute → release → ACCEPTED
- [ ] No manual mark_ready call (architect creates READY)
- [ ] DB shared via GRACE_DB_URL between API server and test
- [ ] PacketRun record exists with accepted status
- [ ] Evidence path is not None
- [ ] Verification script exit 0

## Verification

```bash
pytest tests/test_e2e_mvp0.py -v

bash scripts/verify_mvp0.sh
echo "Exit code: $?"

ruff check tests/test_e2e_mvp0.py
```

## Expected Evidence

- `test-results/e2e.xml`
- `state/test.db` — SQLite database with packet in ACCEPTED state
- Verification script output

## Escalation Triggers

- API server fails to start (port conflict)
- Architect creates DRAFT instead of READY
- Worker fails to claim packet
- Adapter fails with import error
- Test times out (>60s without state change)
- DB not shared (server and test see different data)

## Reviewer Gate

Reviewer must reject if:
- E2E test manually calls mark_ready (shouldn't need to)
- DB not shared (test creates separate DB)
- E2E test modifies source code (should only exercise)
- No cleanup of API/worker processes
- Test is flaky (passes sometimes, fails sometimes)
- Missing GRACE contracts in test file
