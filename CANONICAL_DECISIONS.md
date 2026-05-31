# GRACE Control Plane - Canonical Decisions

**Версия:** 1.0 (финальная, без противоречий)
**Дата:** 2026-05-31

Этот документ — единственный источник правды для всех архитектурных решений MVP.

---

## 1. Canonical Package Strategy

### Структура проекта

```
src/
├── prefect_grace/              # LEGACY — переиспользуем, НЕ удаляем
│   ├── platform/               # ✅ Переиспользуем execution engine
│   │   ├── e2e_packet_runner.py
│   │   ├── managed_packet_runner_flow.py
│   │   └── worktree_manager.py
│   ├── tasks/                  # ✅ Переиспользуем codex_launcher
│   │   └── codex_launcher.py
│   └── prefect_compat.py       # 🆕 No-op декораторы
│
└── grace_control/              # 🆕 NEW — Control Plane wrapper
    ├── api/                    # FastAPI server
    ├── core/                   # State machine, executors
    ├── worker/                 # Worker loop
    ├── cli/                    # CLI wrapper
    └── adapters/               # 🆕 Bridge к legacy code
        └── packet_executor.py  # DB packet → run_e2e_packet
```

### Правило

- **НЕ удаляем** `src/prefect_grace/flows/`, `platform/`, `tasks/`
- **Добавляем** `prefect_compat.py` для no-op декораторов
- **Создаём** `grace_control/` как новый слой
- **Используем** `grace_control/adapters/` для интеграции

---

## 2. Canonical States

### Минимальный набор состояний

```python
class PacketState(enum.Enum):
    """Canonical packet states for MVP."""
    
    # Main flow
    DRAFT = "draft"              # Created by architect
    READY = "ready"              # Ready for worker
    RUNNING = "running"          # Worker executing
    ACCEPTED = "accepted"        # Tests passed, ready to merge
    MERGED = "merged"            # Merged to main (terminal)
    
    # Error branches
    REJECTED = "rejected"        # Tests failed, needs rework
    FAILED = "failed"            # Execution error (terminal)
    CANCELLED = "cancelled"      # Manually cancelled (terminal)
```

### Убрали из MVP

- ❌ `TESTING` — это не state пакета, а stage внутри `packet_runs`
- ❌ `REVIEW` — для MVP нет human review (только для STRICT в post-MVP)
- ❌ `BLOCKED` — для MVP нет dependencies между packets
- ❌ `NEEDS_REWORK` — это просто `REJECTED` + retry

### State transitions

```
DRAFT → READY → RUNNING → ACCEPTED → MERGED
                    ↓
                REJECTED (retry → READY)
                    ↓
                FAILED (terminal)
```

---

## 3. Canonical DB Schema

### Минимальные таблицы для MVP

```python
# 1. features
id, slug, title, description, spec_json, status, created_at, updated_at

# 2. waves
id, feature_id, slug, title, description, order, status, created_at

# 3. packets
id, feature_id, wave_id, slug, title, description, spec_json,
state, acceptance_profile, attempt_count, max_attempts,
created_at, updated_at

# 4. packet_runs
id, packet_id, run_number, executor_id, worker_id,
status, result_json, evidence_path,
started_at, finished_at, duration_ms

# 5. workers
id, status, current_packet_id, last_heartbeat,
started_at

# 6. leases
id, packet_id, worker_id, acquired_at, expires_at, heartbeat_at

# 7. events
id, timestamp, event_type, entity_type, entity_id,
payload_json, trace_id
```

### Убрали из MVP

- ❌ `test_runs` — тесты записываются в `packet_runs.result_json`
- ❌ `capabilities` — для MVP один тип worker
- ❌ `resources` — для MVP нет resource limits

---

## 4. Canonical API Contract

### Base URL

```
http://localhost:8000/api
```

### Endpoints (MVP only)

```
# Features
GET    /api/features/
GET    /api/features/{feature_id}

# Packets
GET    /api/packets/
GET    /api/packets/{packet_id}
POST   /api/packets/{packet_id}/cancel

# Workers
GET    /api/workers/
POST   /api/workers/register
POST   /api/workers/heartbeat

# Worker operations (internal)
POST   /api/packets/claim
POST   /api/packets/{packet_id}/release

# Architect
POST   /api/architect/plan

# System
GET    /health
```

### Убрали из MVP

- ❌ `/api/artifacts/*` — artifacts только через filesystem
- ❌ `/api/system/*` — только `/health`
- ❌ WebSocket — нет real-time updates в MVP

---

## 5. Canonical Execution Flow

### PacketExecutionAdapter

```python
class PacketExecutionAdapter:
    """
    Bridge между DB packet и существующим run_e2e_packet.
    
    Responsibilities:
    1. Load packet from DB
    2. Materialize packet file (EXECUTION_PACKET.md)
    3. Call existing run_e2e_packet(...)
    4. Parse result
    5. Save evidence
    6. Update DB state
    """
    
    async def execute(self, packet_id: str) -> ExecutionResult:
        # 1. Load from DB
        packet = db.query(Packet).filter_by(id=packet_id).first()
        
        # 2. Materialize packet file
        packet_path = self._materialize_packet(packet)
        
        # 3. Call existing runner
        from prefect_grace.platform.e2e_packet_runner import run_e2e_packet
        
        result = run_e2e_packet(
            project_root=self.project_root,
            packet_path=packet_path,
            state_root=self.state_root,
            worktree_root=self.worktree_root,
            dry_run=False,  # MVP: live execution
            execute_agent=True,
            merge_after_accept=True
        )
        
        # 4. Parse result
        execution_result = self._parse_result(result)
        
        # 5. Save evidence
        self._save_evidence(packet_id, result)
        
        # 6. Update DB
        self._update_state(packet, execution_result)
        
        return execution_result
```

---

## 6. Canonical MVP Scope

### В MVP (Phase 0-2)

✅ **Phase 0: Cleanup**
- Добавить `prefect_compat.py`
- НЕ удалять flows/platform/tasks
- Создать структуру `grace_control/`

✅ **Phase 1: Core**
- DB schema (7 таблиц)
- State machine (8 состояний)
- PacketExecutionAdapter
- Executors (только API providers)
- Logging

✅ **Phase 2: API & Worker**
- FastAPI server (только API contract endpoints)
- Worker loop с lease
- Architect integration
- CLI (только `grace packet list/get`)

✅ **Phase 3: E2E Test**
- Один E2E test: plan → execute → accept → merge
- Verification

### НЕ в MVP (Post-MVP)

❌ **UI/Dashboard** — только CLI + JSON
❌ **Telegram** — только logs
❌ **WebSocket** — только polling
❌ **Image viewer** — только JSON artifacts
❌ **Thumbnails** — только raw files
❌ **Cancellation** — только в post-MVP
❌ **Health checks** — только basic `/health`
❌ **GRACE Canon checker** — только в post-MVP
❌ **Complexity router** — все packets NORMAL profile
❌ **Acceptance policies** — только simple policy
❌ **Test infrastructure** — только basic pytest

---

## 7. Canonical pyproject.toml

### Build system

```toml
[build-system]
requires = ["hatchling"]
build-backend = "hatchling.build"

[project]
name = "prefect-grace"
version = "0.1.0"
requires-python = ">=3.11"
dependencies = [
    "prefect>=3.0.0",
    "fastapi>=0.109.0",
    "uvicorn[standard]>=0.27.0",
    "sqlalchemy>=2.0.25",
    "httpx>=0.26.0",
    "click>=8.1.7",
    "rich>=13.7.0",
    "pydantic>=2.5.3",
]

[project.scripts]
grace = "grace_control.cli.main:cli"
grace-api = "grace_control.api.main:main"
grace-worker = "grace_control.worker.worker:main"
```

### НЕ poetry

- Текущий проект на `hatchling`
- НЕ переходим на `poetry`
- Используем существующий `pyproject.toml`

---

## 8. Canonical Security

### MVP security model

```python
# API server
app = FastAPI()

# Bind только localhost
uvicorn.run(
    app,
    host="127.0.0.1",  # НЕ 0.0.0.0
    port=8000
)

# CORS только для localhost
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:*"],  # НЕ "*"
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
```

### Post-MVP

- Authentication (API keys)
- Authorization (RBAC)
- HTTPS
- Rate limiting

---

## 9. Canonical First Vertical Slice

### MVP-0: Минимальный рабочий цикл

```
1. grace architect plan feature.yaml
   → Creates packets in DB (state: DRAFT → READY)

2. grace worker start
   → Claims packet (lease)
   → PacketExecutionAdapter.execute()
   → Calls existing run_e2e_packet()
   → Saves evidence JSON
   → Updates state (RUNNING → ACCEPTED/REJECTED)
   → Auto-merge if ACCEPTED

3. grace packet list
   → Shows packet states

4. grace packet get PKT-001
   → Shows packet details + evidence path
```

### Что НЕ в MVP-0

- ❌ Parallel packets
- ❌ Multiple workers
- ❌ UI/Telegram
- ❌ Cancellation
- ❌ Health checks (кроме basic)
- ❌ Retry logic (только manual)

---

## 10. Canonical Timeline

### Revised timeline

**Phase 0:** Cleanup (2 дня)
**Phase 1:** Core + Adapter (1 неделя)
**Phase 2:** API + Worker (1 неделя)
**Phase 3:** E2E Test (2 дня)

**Итого: 2.5 недели до MVP-0**

### Post-MVP waves

**Wave 1:** Retry + Cancellation (3 дня)
**Wave 2:** UI + Telegram (1 неделя)
**Wave 3:** GRACE Canon + Complexity Router (1 неделя)
**Wave 4:** Parallel execution + Multiple workers (1 неделя)

---

## ✅ Canonical Checklist

Перед началом реализации проверить:

- [ ] Все ТЗ ссылаются на этот документ
- [ ] Нет упоминаний удалённых features (UI, Telegram, WebSocket)
- [ ] Нет упоминаний `poetry` (только `hatchling`)
- [ ] Нет упоминаний `FOR UPDATE SKIP LOCKED` (только SQLite-safe lease)
- [ ] Нет упоминаний 9+ states (только 8)
- [ ] Нет упоминаний `TESTING`/`REVIEW` states
- [ ] Все API endpoints из API_CONTRACT.md
- [ ] PacketExecutionAdapter явно описан

---

**Этот документ — единственный источник правды. Все противоречия разрешены.**
