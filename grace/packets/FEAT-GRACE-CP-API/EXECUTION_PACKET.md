# Execution Packet: FEAT-GRACE-CP-API-W02-FASTAPI-SERVER

## Objective

Create the FastAPI server for GRACE Control Plane: 9 canonical endpoints from API_CONTRACT.md, CORS via allow_origin_regex, bind 127.0.0.1:8042, lifespan-based DB init, health check.

Architect endpoint creates packets in READY (not DRAFT). Claim endpoint is the SOLE owner of READY→RUNNING transition. Release endpoint transitions RUNNING→ACCEPTED/REJECTED/FAILED.

## Slice

- slice_id: `SLICE-API`
- slice_slug: `fastapi-server`
- feature_id: `FEAT-GRACE-CP-API`
- packet_id: `FEAT-GRACE-CP-API-W02-FASTAPI-SERVER`
- wave_id: `W02`
- status: `ready`
- phase: `PHASE-2`
- depends_on: `FEAT-GRACE-CP-ADAPTER-W02-PACKET-EXECUTION-ADAPTER`
- feature_dir: `grace/packets/FEAT-GRACE-CP-API`

## Source Of Truth

- `CANONICAL_DECISIONS.md` §4 (API contract), §5 (state ownership), §8 (security)
- `docs/API_CONTRACT.md` — all endpoint signatures + response formats
- `tasks/PHASE_2_API_WORKER_REVISED.md` Task #18
- `development-plan.xml` — FEAT-GRACE-API
- `knowledge-graph.xml` — RULE-001, RULE-002

## Impacted Modules

- `M-GRACE-CP-API`

## Allowed Write Scope

- `src/grace_control/api/__init__.py`
- `src/grace_control/api/main.py`
- `src/grace_control/api/routers/__init__.py`
- `src/grace_control/api/routers/features.py`
- `src/grace_control/api/routers/packets.py`
- `src/grace_control/api/routers/workers.py`
- `src/grace_control/api/routers/architect.py`
- `src/grace_control/core/health.py`
- `tests/test_api.py`
- `grace/packets/FEAT-GRACE-CP-API/**`

## Frozen Scope

- `src/prefect_grace/**` — legacy code
- `src/grace_control/db/**` — read-only imports
- `src/grace_control/adapters/**` — read-only imports
- `src/grace_control/worker/**`
- `src/grace_control/cli/**`

## Must Preserve

- 9 canonical endpoints exactly (no cancel, no extra endpoints)
- CORS: allow_origin_regex (not allow_origins with wildcard)
- Bind 127.0.0.1 (not 0.0.0.0)
- Architect creates packets in READY state (not DRAFT)
- Claim: READY→RUNNING (sole owner, creates lease, increments attempt_count)
- Release: RUNNING→ACCEPTED/REJECTED/FAILED (removes lease, updates worker)
- All responses: {"data": {...}, "timestamp": "..."} or {"error": {"code": "...", "message": "..."}}
- No cancel endpoint (post-MVP)

### GRACE Canon Compliance (обязательно)

Весь новый код должен соответствовать GRACE Canon (`prompts/canon_digest_prompt.md`). Кратко:

- **AI_HEADER**: `# AI_HEADER: <имя_роутера>` + `# ROLE: <описание>`
- **MODULE_CONTRACT**: purpose, inputs, returns, side_effects, emitted_logs, error_behavior
- **MODULE_MAP**: перечень всех endpoint-функций
- **FUNCTION_CONTRACT**: у каждой endpoint-функции
- **Блоки**: `#START_BLOCK_<NAME>` / `#END_BLOCK_<NAME>` для логических секций
- **Лимиты**: файл ≤ 1000 строк, функция ≤ 4000 токенов
- **Логирование**: `log_event()` для всех операций
- **T0**: `ruff check`, `ruff format --check`, `mypy`, `compileall`

## Required Design Decisions

### 1. FastAPI App with Lifespan

```python
@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db(os.environ.get("GRACE_DB_URL"))
    yield

app = FastAPI(title="GRACE Control Plane", version="0.1.0", lifespan=lifespan)
```

### 2. CORS Middleware

```python
app.add_middleware(
    CORSMiddleware,
    allow_origin_regex=r"http://localhost:\d+",
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
```

### 3. Uvicorn Bind

```python
uvicorn.run(app, host="127.0.0.1", port=8042)
```

### 4. Endpoints

| Method | Path | Router |
|--------|------|--------|
| GET | /api/features/ | features |
| GET | /api/features/{id} | features |
| GET | /api/packets/?state=&feature_id= | packets |
| GET | /api/packets/{id} | packets |
| POST | /api/packets/claim | packets |
| POST | /api/packets/{id}/release | packets |
| GET | /api/workers/ | workers |
| POST | /api/workers/register | workers |
| POST | /api/workers/heartbeat | workers |
| POST | /api/architect/plan | architect |
| GET | /health | main |

## Implementation Requirements

1. `src/grace_control/api/main.py` — FastAPI app, lifespan, CORS, router includes, health endpoint, uvicorn main()
2. `src/grace_control/api/routers/features.py` — list + get endpoints
3. `src/grace_control/api/routers/packets.py` — list, get, claim, release endpoints
4. `src/grace_control/api/routers/workers.py` — list, register, heartbeat endpoints
5. `src/grace_control/api/routers/architect.py` — plan endpoint (creates packets in READY)
6. `src/grace_control/core/health.py` — check_health() returning status/workers/queue/running
7. `tests/test_api.py` — one test per endpoint, error format, CORS headers, state transitions

## Acceptance Criteria

- [ ] Server starts: `uvicorn.run(app, host="127.0.0.1", port=8042)`
- [ ] `GET /health` → {"status": "healthy", "workers": {...}, "queue_depth": 0}
- [ ] `POST /api/architect/plan` → creates feature+wave+packets in READY state
- [ ] `GET /api/packets/` → lists packets with state filter
- [ ] `POST /api/packets/claim` → READY→RUNNING, creates lease
- [ ] `POST /api/packets/{id}/release` → RUNNING→ACCEPTED/REJECTED/FAILED, removes lease
- [ ] `POST /api/workers/register` → creates/updates worker
- [ ] `POST /api/workers/heartbeat` → updates last_heartbeat
- [ ] Error responses: {"error": {"code": "...", "message": "..."}}
- [ ] All tests pass: `pytest tests/test_api.py -v`

## Verification

```bash
# Start server in background
grace api start &
sleep 2

# Test all endpoints
curl -s http://localhost:8042/health | python3 -m json.tool
curl -s http://localhost:8042/api/features/ | python3 -m json.tool
curl -s http://localhost:8042/api/packets/ | python3 -m json.tool

# Create plan
curl -s -X POST http://localhost:8042/api/architect/plan \
  -H "Content-Type: application/json" \
  -d '{"feature_spec":{"title":"Test","waves":[{"title":"W1","packets":[{"title":"Add test","scope":"src/test.py"}]}]}}'

# Check packets are READY
curl -s http://localhost:8042/api/packets/?state=ready

kill %1

# Unit tests
pytest tests/test_api.py -v

ruff check src/grace_control/api/
mypy src/grace_control/api/
```

## Expected Evidence

- `test-results/api.xml`
- curl output showing all endpoints respond
- Proof packets created in READY state (not DRAFT)
- Proof CORS headers present

## Escalation Triggers

- Port 8042 already in use
- FastAPI/uvicorn import error
- DB init fails on startup
- CORS blocks legitimate localhost request
- Architect creates packets in DRAFT (not READY)

## Reviewer Gate

Reviewer must reject if:
- Cancel endpoint exists (post-MVP leak)
- Architect creates DRAFT (should be READY)
- CORS uses allow_origins (not allow_origin_regex)
- Bind is 0.0.0.0 (must be 127.0.0.1)
- Claim does NOT transition state (stateless claim)
- Release doesn't remove lease
- Missing GRACE contracts on any router
