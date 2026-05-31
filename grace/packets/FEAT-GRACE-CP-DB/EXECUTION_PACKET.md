# Execution Packet: FEAT-GRACE-CP-DB-W01-DB-SCHEMA

## Objective

Create the SQLite database schema for GRACE Control Plane: 7 tables via SQLAlchemy ORM with database helper (init_db, get_db), SQLite-safe (no FOR UPDATE SKIP LOCKED), in-memory test support.

This is the foundation of the entire control plane. Every other packet depends on these tables existing and being queryable.

## Slice

- slice_id: `SLICE-DB-SCHEMA`
- slice_slug: `db-schema`
- feature_id: `FEAT-GRACE-CP-DB`
- packet_id: `FEAT-GRACE-CP-DB-W01-DB-SCHEMA`
- wave_id: `W01`
- status: `ready`
- phase: `PHASE-1`
- depends_on: ``
- feature_dir: `grace/packets/FEAT-GRACE-CP-DB`

## Source Of Truth

- `CANONICAL_DECISIONS.md` §3 (canonical DB schema, 7 tables)
- `tasks/PHASE_1_CORE_REVISED.md` Task #10
- `development-plan.xml` — FEAT-GRACE-DB
- `technology.xml` — databases section

## Impacted Modules

- `M-GRACE-CP-DB`

## Allowed Write Scope

- `src/grace_control/db/__init__.py`
- `src/grace_control/db/schema.py`
- `tests/test_db_schema.py`
- `grace/packets/FEAT-GRACE-CP-DB/**`

## Frozen Scope

- `src/prefect_grace/**` — legacy code
- `src/grace_control/api/**`
- `src/grace_control/worker/**`
- `src/grace_control/cli/**`
- `src/grace_control/adapters/**`
- `src/grace_control/core/state_machine.py`
- `.gitignore`

## Must Preserve

- SQLite only (no PostgreSQL in MVP-0)
- No FOR UPDATE SKIP LOCKED
- SQLAlchemy 2.0+ declarative style
- All 7 tables: features, waves, packets, packet_runs, workers, leases, events
- 8 PacketState enum values: DRAFT, READY, RUNNING, ACCEPTED, MERGED, REJECTED, FAILED, CANCELLED
- Session context manager (get_db) with commit/rollback/close

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

### 1. SQLAlchemy Base = declarative_base()

Use `from sqlalchemy.orm import declarative_base` with Python 3.11+ type hints.

### 2. PacketState as Python Enum

```python
class PacketState(enum.Enum):
    DRAFT = "draft"
    READY = "ready"
    RUNNING = "running"
    ACCEPTED = "accepted"
    MERGED = "merged"
    REJECTED = "rejected"
    FAILED = "failed"
    CANCELLED = "cancelled"
```

### 3. Database URL

Default: `sqlite:///{cwd}/grace.db`. Configurable via `GRACE_DB_URL` env var. In-memory for tests: `sqlite:///:memory:`.

### 4. Session Factory

```python
engine = create_engine(db_url, connect_args={"check_same_thread": False})
SessionLocal = sessionmaker(bind=engine, autocommit=False, autoflush=False)

@contextmanager
def get_db() -> Session:
    db = SessionLocal()
    try:
        yield db
        db.commit()
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()
```

### 5. init_db() creates all tables

```python
def init_db(db_url: str | None = None):
    global engine, SessionLocal
    if db_url is None:
        db_url = f"sqlite:///{Path.cwd() / 'grace.db'}"
    engine = create_engine(db_url, connect_args={"check_same_thread": False})
    SessionLocal = sessionmaker(bind=engine)
    Base.metadata.create_all(engine)
```

## Implementation Requirements

1. `src/grace_control/db/__init__.py`:
   - `init_db(db_url)` — create engine + session + tables
   - `get_db()` — session context manager

2. `src/grace_control/db/schema.py`:
   - `Base = declarative_base()`
   - `PacketState(enum.Enum)` — 8 values
   - `Feature(Base)` — id, slug, title, description, spec_json, status, created_at, updated_at
   - `Wave(Base)` — id, feature_id, slug, title, description, order, status, created_at
   - `Packet(Base)` — id, feature_id, wave_id, slug, title, description, spec_json, state, acceptance_profile, attempt_count, max_attempts, created_at, updated_at
   - `PacketRun(Base)` — id, packet_id, run_number, executor_id, worker_id, status, result_json, evidence_path, started_at, finished_at, duration_ms
   - `Worker(Base)` — id, status, current_packet_id, last_heartbeat, started_at
   - `Lease(Base)` — id, packet_id, worker_id, acquired_at, expires_at, heartbeat_at
   - `Event(Base)` — id, timestamp, event_type, entity_type, entity_id, payload_json, trace_id

3. `tests/test_db_schema.py`:
   - test_create_feature
   - test_create_packet
   - test_packet_state_transitions
   - test_lease_mechanism
   - test_worker_heartbeat
   - test_all_tables_exist (7 tables)
   - test_in_memory_db

## Acceptance Criteria

- [ ] `src/grace_control/db/__init__.py` exists with init_db() and get_db()
- [ ] `src/grace_control/db/schema.py` exists with 7 table classes + PacketState enum
- [ ] SQLite database file created on init_db()
- [ ] All 7 tables created by Base.metadata.create_all()
- [ ] In-memory DB works for tests
- [ ] 8 PacketState enum values defined
- [ ] All tests pass: `pytest tests/test_db_schema.py -v`
- [ ] GRACE Canon: AI_HEADER, MODULE_CONTRACT, FUNCTION_CONTRACT on all functions

## Verification

```bash
# Unit tests
pytest tests/test_db_schema.py -v

# Verify all tables exist
python3 -c "
from grace_control.db import init_db
init_db('sqlite:///:memory:')
from grace_control.db.schema import Base
tables = Base.metadata.tables.keys()
assert len(tables) == 7, f'Expected 7 tables, got {len(tables)}: {tables}'
print('OK: 7 tables created')
"

# GRACE Canon checks
ruff check src/grace_control/db/
ruff format --check src/grace_control/db/
mypy src/grace_control/db/
python3 -m compileall -q src/grace_control/db/
```

## Expected Evidence

- `test-results/db-schema.xml` — pytest output
- Table verification output (7 tables)
- ruff/mypy clean output

## Escalation Triggers

- Fewer or more than 7 tables created
- SQLAlchemy version conflict
- In-memory DB not working for tests
- ImportError on any dependency
- PacketState enum has wrong values

## Reviewer Gate

Reviewer must reject if:
- Tables don't match CANONICAL_DECISIONS.md §3 (wrong columns, missing tables)
- No SQLite-safe (uses FOR UPDATE SKIP LOCKED)
- Missing GRACE contracts (AI_HEADER, MODULE_CONTRACT, FUNCTION_CONTRACT)
- init_db() called outside test fixture
- PacketState missing canonical values
