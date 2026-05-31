# GRACE Control Plane

**LLM-driven autonomous development orchestrator** — packet-based, agent-driven, SQLite-backed.

MVP-0 ready: API server + worker loop + state machine + GRACE Canon checker + structured logging.

## Architecture

```
grace architect plan → packets in DB (READY)
       ↓
grace worker start → claim → execute → release → ACCEPTED → merge → MERGED
       ↓
grace packet list → Rich-formatted dashboard
```

**Packages:**
- `grace_control/` — new Control Plane (FastAPI, state machine, worker, CLI)
- `prefect_grace/` — legacy execution engine (worktree isolation, agent launcher, git ops)
- `prefect_grace/prefect_compat.py` — compatibility layer (no Prefect runtime required)

## Quick Start

```bash
pip install grace-orchestrator
```

```bash
# Terminal 1: API server
grace api start
# → http://127.0.0.1:8042

# Terminal 2: Worker
grace worker start

# Terminal 3: Create plan
echo 'title: Auth
waves:
  - title: Foundation
    packets:
      - title: Add JWT utils
        scope: src/auth/jwt.py' > feature.yaml
grace architect plan feature.yaml

# Check progress
grace packet list
grace health
```

## API Endpoints (9)

| Method | Path | Purpose |
|--------|------|---------|
| GET | /api/features/ | List features |
| GET | /api/features/{id} | Get feature |
| GET | /api/packets/ | List packets (filter: ?state=ready) |
| GET | /api/packets/{id} | Get packet + runs |
| POST | /api/packets/claim | Worker claims packet (READY→RUNNING) |
| POST | /api/packets/{id}/release | Worker releases (RUNNING→ACCEPTED/REJECTED/FAILED) |
| POST | /api/packets/{id}/cancel | Cancel packet → CANCELLED |
| POST | /api/packets/{id}/merge | Merge accepted → MERGED |
| GET | /api/workers/ | List workers |
| POST | /api/workers/register | Register worker |
| POST | /api/workers/heartbeat | Worker heartbeat |
| POST | /api/architect/plan | Create feature + waves + packets |
| GET | /health | System health |

## CLI Commands (6)

```bash
grace architect plan <file>   # Create plan from YAML
grace packet list              # Rich table with states
grace packet get <id>          # Details + runs
grace worker start             # Run worker loop
grace api start                # Start API server
grace health                   # System status
```

## State Machine (8 states)

```
DRAFT → READY → RUNNING → ACCEPTED → MERGED
                  ↓           ↓
              REJECTED     MERGED (auto)
                  ↓
              READY (retry, max 3 attempts)
```

## DB Schema (7 tables)

features, waves, packets, packet_runs, workers, leases, events — SQLite via SQLAlchemy.

## Implemented Features

- **MVP-0:** DB, state machine, adapter, API, worker, CLI, E2E
- **Wave 1:** Auto-retry, cancellation, auto-merge
- **Wave 3:** GRACE Canon checker, complexity router
- **Wave 4:** DAG validator, scope conflict detector, parallel-safe claim
- **Infra:** Structured JSONL logging, event audit trail, lease expiration checker

## Tests

```bash
pytest tests/ --asyncio-mode=auto
# 38 tests, 8.8s
```

## Project Structure

```
src/grace_control/
├── db/schema.py              # 7 SQLAlchemy models
├── core/
│   ├── state_machine.py      # 8 states + transitions
│   ├── packet_operations.py  # mark_ready/running/accepted/...
│   ├── grace_canon.py        # Canon compliance checker
│   ├── complexity_router.py  # FAST→CHEAP, STRICT→PREMIUM
│   ├── dag_validator.py      # Cycle detection + scope conflicts
│   ├── lease_manager.py      # Expired lease recovery
│   ├── event_recorder.py     # Audit trail to events table
│   ├── structured_logger.py  # JSONL logging + trace_context
│   └── health.py             # System health check
├── api/
│   ├── main.py               # FastAPI app + lifespan + CORS
│   └── routers/              # features, packets, workers, architect
├── adapters/
│   └── packet_executor.py    # DB packet → legacy run_e2e_packet
├── worker/
│   ├── api_client.py         # httpx-based API client
│   └── worker.py             # claim→execute→release loop
└── cli/main.py               # 6 CLI commands

src/prefect_grace/            # Legacy execution engine (kept as-is)
├── flows/                    # Prefect flows (compat-only)
├── platform/                 # e2e_packet_runner, worktree_manager, etc.
├── tasks/                    # codex_launcher, agent tools
└── prefect_compat.py         # No-op decorators when Prefect unavailable

grace/packets/                # 14 control packet specifications
tests/                        # 38 tests across 7 test files
```

## Configuration

- `CANONICAL_DECISIONS.md` — single source of truth
- `docs/API_CONTRACT.md` — canonical API endpoints
- `tasks/README.md` — task specifications (REVISED)
- Environment: `GRACE_DB_URL` (sqlite:///grace.db), `GRACE_API_PORT` (8042)

## License

MIT
