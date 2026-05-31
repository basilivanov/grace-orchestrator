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
http://localhost:8042/api
```

### Endpoints (MVP only)

```
# Features
GET    /api/features/
GET    /api/features/{feature_id}

# Packets
GET    /api/packets/
GET    /api/packets/{packet_id}

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

- ❌ `/api/packets/{packet_id}/cancel` — cancellation = post-MVP
- ❌ `/api/artifacts/*` — artifacts только через filesystem
- ❌ `/api/system/*` — только `/health`
- ❌ WebSocket — нет real-time updates в MVP

---

## 5. Canonical Execution Flow

### State Ownership Rules (CRITICAL)

**Один владелец на каждый переход состояния:**

| Переход | Владелец | Когда |
|---------|----------|-------|
| DRAFT → READY | Architect endpoint (POST /api/architect/plan) или CLI `grace architect plan` | При создании плана (packets сразу READY) |
| READY → RUNNING | claim endpoint (POST /api/packets/claim) | Worker забирает пакет |
| RUNNING → ACCEPTED | release endpoint (POST /api/packets/{id}/release) | Worker завершил успешно |
| RUNNING → REJECTED | release endpoint | Worker завершил, тесты провалены |
| RUNNING → FAILED | release endpoint или adapter (exception) | Ошибка выполнения |
| ACCEPTED → MERGED | **Post-MVP** (MVP-0 заканчивается на ACCEPTED) | — |
| REJECTED → READY | packet_operations.retry_packet() | Ручной или автоматический retry |

**Adapter НЕ меняет состояние пакета напрямую.** Adapter только:
1. Материализует packet file из DB
2. Вызывает run_e2e_packet()
3. Парсит результат
4. Сохраняет evidence + packet_run запись
5. Возвращает результат worker'у, который вызывает release

### PacketExecutionAdapter

```python
class PacketExecutionAdapter:
    """
    Bridge между DB packet и существующим run_e2e_packet.

    Responsibilities:
    1. Load packet from DB
    2. Materialize packet file (EXECUTION_PACKET.md)
    3. Call existing run_e2e_packet(...)
    4. Parse E2EPacketRunnerResult
    5. Save evidence + create packet_run record
    6. Return result worker'у (worker вызывает release)

    DOES NOT change packet state — worker/release endpoint owns state.
    """

    async def execute(self, packet_id: str, worker_id: str) -> ExecutionResult:
        # 1. Load from DB
        packet = db.query(Packet).filter_by(id=packet_id).first()

        # 2. Materialize packet file
        packet_path = self._materialize_packet(packet)

        # 3. Call existing runner (CRITICAL: execute_agent=True!)
        from prefect_grace.platform.e2e_packet_runner import run_e2e_packet

        result: E2EPacketRunnerResult = run_e2e_packet(
            project_root=self.project_root,
            packet_path=packet_path,
            state_root=self.state_root,
            worktree_root=self.worktree_root,
            dry_run=False,        # MUST be False
            execute_agent=True,    # MUST be True for live agents
        )

        # 4. Map result to ExecutionResult
        execution_result = self._parse_result(result)

        # 5. Save evidence + create packet_run record
        self._save_evidence(packet_id, run_number, result)

        # 6. Return to worker (worker calls release endpoint)
        return execution_result
```

### Mapping E2EPacketRunnerResult → ExecutionResult

```
result.ok == True and result.domain_status == "accepted"
  → ExecutionResult(accepted=True)

result.domain_status in ("rework_required", "blocked", "scope_blocked")
  → ExecutionResult(accepted=False, reason=result.registry_reason)

result.domain_status in ("agent_failed", "verifier_failed",
                          "reviewer_failed", "runner_error", "handoff_error")
  → ExecutionResult(accepted=False, reason=f"Execution error: {result.registry_reason}")
  → Worker вызывает release со status="failed"
```

### Architectural constraint: Adapter does NOT call mark_running/mark_accepted/etc.

Состоянием владеет API (claim/release endpoints). Adapter — чистая функция преобразования DB packet → legacy runner → структурированный результат.

---

## 6. Canonical MVP Scope

### В MVP (Phase 0-3)

✅ **Phase 0: Cleanup**
- Добавить `prefect_compat.py`
- НЕ удалять flows/platform/tasks
- Создать структуру `grace_control/`
- Prefect dependency — transitional (keep in pyproject.toml, no new flows)

✅ **Phase 1: Core**
- DB schema (7 таблиц)
- State machine (8 состояний)
- PacketExecutionAdapter (bridge, не меняет состояние)

✅ **Phase 2: API & Worker**
- FastAPI server (canonical endpoints, без cancel)
- Worker loop с lease
- CORS через allow_origin_regex (не allow_origins с pattern)
- Bind 127.0.0.1
- Architect создаёт packets сразу в READY (не DRAFT)
- claim endpoint: READY → RUNNING (единственный владелец перехода)
- release endpoint: RUNNING → ACCEPTED/REJECTED/FAILED

✅ **Phase 3: CLI & E2E Test**
- CLI: packet list/get, worker start, api start, health
- CLI: `grace architect plan <file>` команда
- E2E test: единая DB через GRACE_DB_URL env var

### НЕ в MVP (Post-MVP)

❌ **Cancellation** — endpoint + логика (post-MVP)
❌ **Auto-merge** — MVP-0 заканчивается на ACCEPTED
❌ **UI/Dashboard** — только CLI + JSON
❌ **Telegram** — только logs
❌ **WebSocket** — только polling
❌ **Image viewer** — только JSON artifacts
❌ **GRACE Canon checker** — только basic structural checks
❌ **Complexity router** — все packets NORMAL profile
❌ **Acceptance policies** — только simple policy
❌ **Multiple workers** — только один worker в MVP-0

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
    port=8042
)

# CORS только для localhost
app.add_middleware(
    CORSMiddleware,
    allow_origin_regex=r"http://localhost:\d+",  # Regex по портам, НЕ "*"
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
   → Creates packets in DB (state: READY — worker может забрать сразу)

2. grace worker start
   → Claims packet (lease: READY → RUNNING)
   → PacketExecutionAdapter.execute()
   → Calls existing run_e2e_packet(dry_run=False, execute_agent=True)
   → Saves evidence + packet_run record
   → Worker calls release (RUNNING → ACCEPTED/REJECTED/FAILED)

3. grace packet list
   → Shows packet states

4. grace packet get PKT-001
   → Shows packet details + evidence path + runs

MVP-0 заканчивается на ACCEPTED. MERGED — post-MVP.
```

### Что НЕ в MVP-0

- ❌ Auto-merge (MVP-0 заканчивается на ACCEPTED)
- ❌ Parallel packets / Multiple workers
- ❌ UI/Telegram/WebSocket/Cancellation
- ❌ GRACE Canon checker / Complexity router
- ❌ Retry logic (только ручной через CLI)

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
