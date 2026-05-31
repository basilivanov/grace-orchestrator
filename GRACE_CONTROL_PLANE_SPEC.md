# GRACE Control Plane — Technical Specification v2

## 1. Цель

Заменить Prefect на собственный GRACE Control Plane, заточенный под AI-driven разработку.

**Главный use case:**
```text
Architect пишет ТЗ → закидывает в GRACE → утром готовый протестированный код
```

**Не цель:** Универсальный workflow engine. Только packet execution.

---

## 2. Что уже есть (переиспользуем)

✅ **Packet execution engine:**
- `run_e2e_packet()` — полный цикл выполнения пакета
- `run_managed_packet()` — managed execution с worktree
- Worktree management
- Evidence collection
- Agent launcher (codex_launcher)

✅ **Domain models:**
- PacketStatus, FeatureStatus, ReviewVerdict
- TestVerdict, WaveVerdict
- Acceptance logic

✅ **Infrastructure:**
- CLI framework
- Test tier runner (T0/T1/T2)
- File-based state storage (мигрируем в DB)

---

## 3. Что заменяем

❌ **Prefect:**
- @flow/@task decorators → прямые вызовы функций
- Work pools & queues → SQLite queue
- Deployments → worker loop
- Artifacts → evidence в DB
- Flow tracking → events в DB

---

## 4. Упрощённая архитектура

### 4.1 Главная модель

```text
Feature (ТЗ от architect)
  ↓
Architect Agent → генерирует Waves + Packets
  ↓
Packets → READY queue
  ↓
Worker → claim → execute → tests → accept/reject
  ↓
Evidence → DB
  ↓
Merge (если accepted)
```

### 4.2 Packet lifecycle

```text
DRAFT       — создан architect agent
READY       — готов к выполнению
RUNNING     — worker выполняет
TESTING     — тесты запущены
REVIEW      — на ревью (опционально)
ACCEPTED    — принят
REJECTED    — отклонён
MERGED      — смержен
FAILED      — провален
```

**8 состояний вместо 23.**

---

## 5. Database Schema (SQLite → Postgres)

### 5.1 Минимальная схема (8 таблиц)

```sql
-- Основное состояние пакета
CREATE TABLE packets (
    id TEXT PRIMARY KEY,
    feature_id TEXT,
    wave_id TEXT,
    title TEXT NOT NULL,
    description TEXT,
    state TEXT NOT NULL,  -- DRAFT, READY, RUNNING, etc.
    complexity TEXT,      -- simple, medium, complex
    acceptance_profile TEXT,  -- FAST, NORMAL, STRICT
    risk TEXT,            -- low, medium, high
    scope TEXT,           -- expected files/modules
    priority INTEGER DEFAULT 0,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Попытки выполнения пакета
CREATE TABLE packet_runs (
    id TEXT PRIMARY KEY,
    packet_id TEXT NOT NULL,
    attempt INTEGER NOT NULL,
    status TEXT NOT NULL,  -- running, succeeded, failed
    started_at TIMESTAMP,
    finished_at TIMESTAMP,
    result_json TEXT,      -- serialized result
    FOREIGN KEY (packet_id) REFERENCES packets(id),
    UNIQUE(packet_id, attempt)
);

-- Запуски агентов
CREATE TABLE agent_runs (
    id TEXT PRIMARY KEY,
    packet_run_id TEXT NOT NULL,
    role TEXT NOT NULL,    -- coder, reviewer, architect
    executor TEXT NOT NULL, -- cheap-coder, strong-coder, etc.
    status TEXT NOT NULL,
    result_path TEXT,
    started_at TIMESTAMP,
    finished_at TIMESTAMP,
    FOREIGN KEY (packet_run_id) REFERENCES packet_runs(id)
);

-- Запуски тестов
CREATE TABLE test_runs (
    id TEXT PRIMARY KEY,
    packet_run_id TEXT NOT NULL,
    tier TEXT NOT NULL,    -- T0, T1, T2
    status TEXT NOT NULL,  -- passed, failed
    command TEXT,
    output_path TEXT,
    duration_ms INTEGER,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (packet_run_id) REFERENCES packet_runs(id)
);

-- Evidence items
CREATE TABLE evidence_items (
    id TEXT PRIMARY KEY,
    packet_run_id TEXT NOT NULL,
    type TEXT NOT NULL,    -- diff, test_output, review
    tier TEXT,
    path TEXT NOT NULL,
    status TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (packet_run_id) REFERENCES packet_runs(id)
);

-- Audit events
CREATE TABLE events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    entity_type TEXT NOT NULL,  -- packet, packet_run, agent_run
    entity_id TEXT NOT NULL,
    event_type TEXT NOT NULL,   -- PACKET_CREATED, STATE_CHANGED, etc.
    payload_json TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Workers
CREATE TABLE workers (
    id TEXT PRIMARY KEY,
    hostname TEXT NOT NULL,
    pid INTEGER,
    status TEXT NOT NULL,  -- active, stopped
    heartbeat_at TIMESTAMP,
    started_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Leases (для предотвращения двойного выполнения)
CREATE TABLE leases (
    id TEXT PRIMARY KEY,
    packet_id TEXT NOT NULL,
    worker_id TEXT NOT NULL,
    lease_until TIMESTAMP NOT NULL,
    heartbeat_at TIMESTAMP,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (packet_id) REFERENCES packets(id),
    FOREIGN KEY (worker_id) REFERENCES workers(id)
);

CREATE INDEX idx_packets_state ON packets(state);
CREATE INDEX idx_packets_priority ON packets(priority DESC, created_at ASC);
CREATE INDEX idx_leases_until ON leases(lease_until);
CREATE INDEX idx_events_entity ON events(entity_type, entity_id);
```

### 5.2 Postgres migration path

```python
# Используем SQLAlchemy для абстракции
# SQLite для dev/test
# Postgres для production

DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:///grace.db")
engine = create_engine(DATABASE_URL)
```

---

## 6. Упрощённый CLI

### 6.1 Architect workflow

```bash
# 1. Architect пишет ТЗ в файл
vim feature-spec.md

# 2. Запускает architect agent
grace architect plan feature-spec.md

# Architect agent:
# - Читает ТЗ
# - Генерирует waves
# - Генерирует packets
# - Регистрирует их в DB (state=DRAFT)
# - Переводит в READY

# 3. Проверяет что создалось
grace packet list

# 4. Запускает worker (или уже запущен)
grace worker start

# 5. Утром проверяет результаты
grace packet status PKT-001
grace packet evidence PKT-001
```

### 6.2 Минимальные команды

```bash
# Architect commands
grace architect plan <feature-spec.md>     # Генерирует packets из ТЗ
grace architect status                     # Статус текущей feature

# Packet commands
grace packet list                          # Список пакетов
grace packet status <packet-id>            # Статус пакета
grace packet events <packet-id>            # История событий
grace packet evidence <packet-id>          # Собранные доказательства
grace packet accept <packet-id>            # Принять вручную
grace packet reject <packet-id>            # Отклонить вручную

# Worker commands
grace worker start                         # Запустить worker
grace worker status                        # Статус workers
grace worker stop                          # Остановить worker

# System commands
grace init                                 # Инициализация проекта
grace db migrate                           # Миграция БД
```

**Нет команд для ручной регистрации пакетов** — это делает architect agent.

---

## 7. Acceptance Profiles (3 вместо 5)

### 7.1 FAST

**Для:** Низкорисковые правки.

**Примеры:**
- Документация
- Тесты
- Простые CLI команды
- Логирование
- Typo fixes

**Требования:**
```text
T0 (lint/format) green
T1 (touched scope tests) green
Reviewer НЕ нужен
```

**Результат:**
```text
Tests green → auto ACCEPTED
```

---

### 7.2 NORMAL

**Для:** Обычные задачи среднего риска.

**Примеры:**
- Новый endpoint
- Новый сервисный метод
- Бизнес-логика
- UI компоненты

**Требования:**
```text
T0 green
T1 green
T2 (full unit tests) green
Reviewer опционально (по policy)
```

---

### 7.3 STRICT

**Для:** Опасные зоны.

**Примеры:**
- State machine
- Auth/security
- Database migrations
- Scheduler
- Policy engine
- Billing

**Требования:**
```text
T0 green
T1 green
T2 green
Reviewer обязательно
User acceptance может требоваться
```

---

## 8. Complexity Router

### 8.1 Простая эвристика (без LLM)

```python
def classify_packet(packet: Packet) -> AcceptanceProfile:
    """Классифицирует пакет по сложности."""
    
    # Проверяем scope (expected files)
    high_risk_patterns = [
        "*/migrations/*",
        "*/auth/*",
        "*/security/*",
        "*/state_machine/*",
        "*/policy/*",
        "*/scheduler/*",
        "*/billing/*",
    ]
    
    for pattern in high_risk_patterns:
        if any(fnmatch(f, pattern) for f in packet.scope):
            return AcceptanceProfile.STRICT
    
    # Проверяем размер изменений (после выполнения)
    if packet.diff_lines and packet.diff_lines > 200:
        return AcceptanceProfile.NORMAL
    
    # Проверяем тип задачи по ключевым словам
    low_risk_keywords = ["docs", "test", "logging", "typo", "comment"]
    if any(kw in packet.title.lower() for kw in low_risk_keywords):
        return AcceptanceProfile.FAST
    
    # По умолчанию NORMAL
    return AcceptanceProfile.NORMAL
```

### 8.2 Escalation

Профиль может повыситься после выполнения:

```text
Packet был FAST
Agent изменил src/auth/**
Router повышает → STRICT
Reviewer теперь required
```

---

## 9. Worker Loop

### 9.1 Основной цикл

```python
def worker_loop(worker_id: str):
    """Основной цикл worker."""
    
    while True:
        # Claim next packet with lease
        packet = claim_next_packet(worker_id)
        
        if not packet:
            time.sleep(5)
            continue
        
        try:
            # Execute packet (используем существующий код)
            result = run_e2e_packet(
                packet_id=packet.id,
                project_root=config.project_root,
                state_root=config.state_root,
                worktree_root=config.worktree_root,
            )
            
            # Update state based on result
            handle_packet_result(packet, result)
            
        except Exception as e:
            log_error(packet.id, e)
            mark_packet_failed(packet.id, str(e))
        
        finally:
            release_lease(packet.id, worker_id)
```

### 9.2 Lease mechanism

```python
def claim_next_packet(worker_id: str) -> Packet | None:
    """Claim следующий пакет из очереди."""
    
    with db.transaction():
        # Find next READY packet
        packet = db.execute("""
            SELECT * FROM packets
            WHERE state = 'READY'
            ORDER BY priority DESC, created_at ASC
            LIMIT 1
            FOR UPDATE SKIP LOCKED
        """).fetchone()
        
        if not packet:
            return None
        
        # Create lease
        lease_until = datetime.now() + timedelta(minutes=30)
        db.execute("""
            INSERT INTO leases (id, packet_id, worker_id, lease_until, heartbeat_at)
            VALUES (?, ?, ?, ?, ?)
        """, (uuid4(), packet.id, worker_id, lease_until, datetime.now()))
        
        # Update packet state
        db.execute("""
            UPDATE packets SET state = 'RUNNING' WHERE id = ?
        """, (packet.id,))
        
        # Log event
        log_event("PACKET_CLAIMED", packet.id, {"worker_id": worker_id})
        
        return packet
```

### 9.3 Heartbeat

```python
def heartbeat_loop(worker_id: str):
    """Обновляет heartbeat каждые 30 секунд."""
    
    while True:
        db.execute("""
            UPDATE workers SET heartbeat_at = ? WHERE id = ?
        """, (datetime.now(), worker_id))
        
        db.execute("""
            UPDATE leases SET heartbeat_at = ? WHERE worker_id = ?
        """, (datetime.now(), worker_id))
        
        time.sleep(30)
```

---

## 10. Architect Agent Integration

### 10.1 Architect prompt

```markdown
You are GRACE Architect Agent.

Your task: Read the feature specification and generate a structured plan.

Output format:

```yaml
feature:
  id: FTR-001
  title: "Feature title"
  description: "..."

waves:
  - id: WAV-001
    title: "Wave 1: Foundation"
    packets:
      - id: PKT-001
        title: "Add database tables"
        scope:
          - "src/grace_control/storage/**"
          - "migrations/**"
        complexity: medium
        depends_on: []
      
      - id: PKT-002
        title: "Add worker loop"
        scope:
          - "src/grace_control/workers/**"
        complexity: medium
        depends_on: []
```

Generate packets that are:
- Small (< 200 lines of changes)
- Independent where possible
- With clear scope
```

### 10.2 Architect command

```python
def cmd_architect_plan(feature_spec_path: str):
    """Запускает architect agent для генерации плана."""
    
    # Read feature spec
    spec = Path(feature_spec_path).read_text()
    
    # Run architect agent
    result = run_architect_agent(spec)
    
    # Parse result
    plan = parse_architect_plan(result)
    
    # Register packets in DB
    with db.transaction():
        # Create feature
        db.execute("""
            INSERT INTO features (id, title, description)
            VALUES (?, ?, ?)
        """, (plan.feature.id, plan.feature.title, plan.feature.description))
        
        # Create packets
        for wave in plan.waves:
            for packet in wave.packets:
                db.execute("""
                    INSERT INTO packets (id, feature_id, wave_id, title, scope, state)
                    VALUES (?, ?, ?, ?, ?, 'DRAFT')
                """, (packet.id, plan.feature.id, wave.id, packet.title, json.dumps(packet.scope)))
                
                # Classify complexity
                profile = classify_packet(packet)
                db.execute("""
                    UPDATE packets SET acceptance_profile = ? WHERE id = ?
                """, (profile.value, packet.id))
        
        # Mark packets as READY
        db.execute("""
            UPDATE packets SET state = 'READY' WHERE feature_id = ?
        """, (plan.feature.id,))
    
    print(f"Created {len(plan.packets)} packets")
    print("Run: grace worker start")
```

---

## 11. Test Tiers

### 11.1 Три уровня (T0/T1/T2)

```yaml
test_tiers:
  T0:
    name: "Mechanical checks"
    commands:
      - "ruff check ."
      - "ruff format --check ."
      - "mypy src"
  
  T1:
    name: "Touched scope tests"
    resolver: "touched_scope"  # Определяет тесты по изменённым файлам
    fallback: "pytest tests"
  
  T2:
    name: "Full unit tests"
    commands:
      - "pytest tests/unit -v"
```

### 11.2 Acceptance rules

```python
ACCEPTANCE_RULES = {
    AcceptanceProfile.FAST: ["T0", "T1"],
    AcceptanceProfile.NORMAL: ["T0", "T1", "T2"],
    AcceptanceProfile.STRICT: ["T0", "T1", "T2"],  # + reviewer
}
```

---

## 12. Evidence Collection

### 12.1 Evidence types

```text
DIFF_SUMMARY     — git diff summary
TEST_OUTPUT      — test stdout/stderr
LINT_OUTPUT      — lint results
REVIEW_VERDICT   — reviewer output
```

### 12.2 Storage

```text
.grace/evidence/{packet_id}/{packet_run_id}/
  ├── diff-summary.md
  ├── T0-lint.txt
  ├── T1-tests.txt
  ├── T2-tests.txt
  └── review-verdict.md
```

Пути записываются в `evidence_items` таблицу.

---

## 13. Acceptance Decision

### 13.1 Fast path

```python
def check_acceptance(packet: Packet, packet_run: PacketRun) -> Decision:
    """Проверяет можно ли принять пакет."""
    
    profile = packet.acceptance_profile
    required_tiers = ACCEPTANCE_RULES[profile]
    
    # Check all required test tiers passed
    for tier in required_tiers:
        test_run = get_test_run(packet_run.id, tier)
        if not test_run or test_run.status != "passed":
            return Decision.REJECT(f"Test tier {tier} failed")
    
    # Check reviewer required
    if profile == AcceptanceProfile.STRICT:
        review = get_review_run(packet_run.id)
        if not review or review.verdict != "PASS":
            return Decision.REJECT("Review required but not passed")
    
    # Check forbidden paths not touched
    if any(is_forbidden(f) for f in packet_run.changed_files):
        return Decision.REJECT("Forbidden paths touched")
    
    # All checks passed
    return Decision.ACCEPT("All checks passed")
```

---

## 14. Migration from Prefect

### 14.1 Что НЕ переписываем

Оставляем как есть:
- `run_e2e_packet()` — работает
- `run_managed_packet()` — работает
- Worktree management — работает
- Evidence collection — работает
- Agent launcher — работает

### 14.2 Что переписываем

```python
# Было (Prefect):
@flow(name="feature-pipeline")
def feature_pipeline(feature_id: str):
    result = run_packet_task(packet_id)
    publish_artifact(result)

# Стало (Native):
def feature_pipeline(feature_id: str):
    result = run_e2e_packet(packet_id)
    save_evidence_to_db(result)
```

Просто убираем декораторы и заменяем Prefect artifacts на DB.

---

## 15. MVP Scope

### Phase 1 — Core (1-2 недели)

```text
✓ DB schema (8 таблиц)
✓ State machine (8 состояний)
✓ Complexity router (simple heuristics)
✓ Worker loop with lease
✓ Test tiers T0/T1/T2
✓ Acceptance checker
✓ CLI: architect plan, packet list/status, worker start
✓ Event logging
```

### Phase 2 — Production (1-2 недели)

```text
✓ Review integration
✓ Rework loop
✓ Escalation (cheap → normal → strong executor)
✓ Postgres migration
✓ Monitoring/metrics
```

### Phase 3 — Swarm (2-3 недели)

```text
✓ Dependency graph
✓ Conflict detection
✓ Parallel execution
✓ Merge coordinator
```

---

## 16. Критерии готовности MVP

### 16.1 FAST packet

Система готова если:

```text
1. Architect создаёт low-risk packet
2. Packet классифицируется как FAST
3. Worker выполняет packet
4. T0/T1 проходят
5. Reviewer НЕ вызывается
6. Packet автоматически ACCEPTED
7. Event FAST_PATH_ACCEPTED записан
```

### 16.2 STRICT packet

Система готова если:

```text
1. Architect создаёт high-risk packet (auth/migrations)
2. Packet классифицируется как STRICT
3. Worker выполняет packet
4. T0/T1/T2 проходят
5. Reviewer вызывается обязательно
6. Без review pass packet НЕ принимается
```

### 16.3 Audit trail

По любому packet можно восстановить:

```text
- Кто создал (architect)
- Какой executor выполнял
- Какие тесты прошли
- Почему был выбран acceptance profile
- Почему reviewer был/не был вызван
- Почему packet был принят/отклонён
```

---

## 17. Configuration (YAML)

### 17.1 project.yaml — упрощённая версия

Убираем Prefect-специфичные поля, оставляем только нужное:

```yaml
version: 2

# Project identification
project:
  key: my-project
  root: /path/to/project
  default_branch: main
  grace_dir: grace
  packets_dir: grace/packets

# Runtime paths
runtime:
  state_root: /var/lib/grace/my-project
  artifact_root: /var/lib/grace/my-project/artifacts
  worktree_root: /var/lib/grace/my-project/worktrees
  
  # Database (SQLite or Postgres)
  database_url: sqlite:///grace.db
  # database_url: postgresql://user:pass@localhost/grace

# Executor configuration
executors:
  default: codex-cli
  command: codex1
  
  # Role-specific configurations
  roles:
    architect:
      model: claude-opus-4-8
      reasoning: xhigh
      sandbox: danger-full-access
    
    coder:
      model: claude-sonnet-4-6
      reasoning: high
      sandbox: danger-full-access
    
    reviewer:
      model: claude-opus-4-8
      reasoning: xhigh
      sandbox: danger-full-access

# Test tiers
test_tiers:
  T0:
    name: "Mechanical checks"
    commands:
      - "ruff check ."
      - "ruff format --check ."
      - "mypy src"
  
  T1:
    name: "Touched scope tests"
    resolver: "touched_scope"
    fallback: "pytest tests"
  
  T2:
    name: "Full unit tests"
    commands:
      - "pytest tests/unit -v"

# Security policies
security:
  allow_sandbox_bypass: false
  sandbox_bypass_audit_log: "/var/lib/grace/audit/sandbox_bypass.jsonl"

# Acceptance profiles
acceptance:
  fast:
    test_tiers: ["T0", "T1"]
    reviewer_required: false
    max_diff_lines: 120
  
  normal:
    test_tiers: ["T0", "T1", "T2"]
    reviewer_required: false  # optional by policy
    max_diff_lines: 300
  
  strict:
    test_tiers: ["T0", "T1", "T2"]
    reviewer_required: true
    max_diff_lines: null  # no limit
```

### 17.2 Что удалили из project.yaml

❌ **Prefect-специфичные поля:**
```yaml
workflow_runtime:
  type: prefect
  api_url: http://127.0.0.1:4200/api
  work_pool: grace-process
  queues:
    live:
      name: grace-live
      concurrency_limit: 1
```

❌ **Verification profiles** (слишком сложно для MVP):
```yaml
verification:
  backend_profiles:
    backend_quick: pytest tests/ -k "not slow"
```

❌ **Codex-специфичные поля** (переносим в executors.roles):
```yaml
codex:
  binary: agy
  workdir: /path
  shared_model: claude-sonnet-4-6
```

### 17.3 Feature spec YAML (для architect agent)

Architect читает feature spec в YAML формате:

```yaml
feature_id: FEAT-USER-AUTH-001
title: "Add user authentication"
summary: >-
  Implement JWT-based authentication with login, logout, and session management.

impacted_surfaces:
  - backend/auth
  - backend/api
  - tests

scope:
  - Add JWT token generation and validation
  - Add login/logout endpoints
  - Add session middleware
  - Add auth tests

acceptance_criteria:
  - Login endpoint returns valid JWT token
  - Protected endpoints require valid token
  - Logout invalidates token
  - All auth tests pass

non_goals:
  - Do not implement OAuth/social login
  - Do not implement password reset
  - Do not touch frontend

execute: true
timeout_seconds: 3600
```

Architect agent читает этот файл и генерирует packets.

### 17.4 Packet contract (генерируется architect agent)

```yaml
packet_id: PKT-001
feature_id: FEAT-USER-AUTH-001
wave_id: WAV-001
title: "Add JWT token generation"
description: >-
  Implement JWT token generation with user claims and expiration.

scope:
  - "src/auth/jwt.py"
  - "tests/auth/test_jwt.py"

complexity: medium
risk: high  # auth is always high risk
acceptance_profile: STRICT

depends_on: []

expected_changes:
  - Create src/auth/jwt.py
  - Create tests/auth/test_jwt.py
  - Update requirements.txt (add PyJWT)

acceptance_criteria:
  - JWT tokens generated with correct claims
  - Token expiration works
  - Token validation works
  - All tests pass
```

### 17.5 Открытые вопросы

#### 17.5.1 Executor selection

**Решение:** Escalation (Option C)

```text
Начинаем с cheap (gemini-flash)
Если fail → retry с normal (gemini-pro)
Если fail → retry с strong (claude-opus)
```

Конфигурируется в project.yaml:

```yaml
executors:
  escalation:
    enabled: true
    max_attempts: 3
    tiers:
      - name: cheap
        model: gemini-3.5-flash
      - name: normal
        model: gemini-3.1-pro
      - name: strong
        model: claude-opus-4-8
```

#### 17.5.2 Review trigger

**Решение:** Всегда для STRICT (Option A)

```python
if packet.acceptance_profile == AcceptanceProfile.STRICT:
    reviewer_required = True
elif packet.acceptance_profile == AcceptanceProfile.NORMAL:
    reviewer_required = policy.check("reviewer_required_for_normal")
else:  # FAST
    reviewer_required = False
```

#### 17.5.3 Merge strategy

**Решение:** Автоматический merge после ACCEPTED

У вас уже есть код для merge. Worker делает:

```python
if packet.state == PacketState.ACCEPTED:
    # Auto-merge
    merge_result = git_merge_packet(packet)
    if merge_result.success:
        packet.state = PacketState.MERGED
        log_event("PACKET_MERGED", packet.id)
    else:
        packet.state = PacketState.NEEDS_REWORK
        log_event("MERGE_CONFLICT", packet.id, merge_result.conflicts)
```

Используем существующий `git_mutation_gate.py` и merge logic.

---

---

## 18. Что переиспользуем из текущего кода

### 18.1 Готовые модули (не трогаем)

✅ **Packet execution:**
- `platform/e2e_packet_runner.py` — полный E2E цикл
- `platform/managed_packet_runner.py` — managed execution
- `flows/managed_packet_runner_flow.py` — обёртка (убираем @flow)

✅ **Worktree management:**
- `platform/worktree_manager.py` — создание/cleanup worktrees
- `flows/worktree_scope_lifecycle_flow.py` — lifecycle (убираем @flow)

✅ **Evidence collection:**
- `platform/evidence_manifest.py` — сбор evidence
- `platform/packet_artifacts.py` — artifacts
- `flows/pipeline_helpers/evidence_collector.py` — helpers

✅ **Agent launcher:**
- `tasks/codex_launcher.py` — запуск codex/agy
- `tasks/codex_launcher_helpers/command_builder.py` — построение команд

✅ **Git operations:**
- `platform/git_mutation_gate.py` — merge logic
- Используем для автоматического merge после ACCEPTED

✅ **Models:**
- `models.py` — PacketStatus, FeatureStatus, ReviewVerdict, etc.
- Оставляем как есть

✅ **Test runner:**
- Существующая логика запуска тестов
- Адаптируем под test_tiers из project.yaml

### 18.2 Что заменяем

❌ **Prefect flows → прямые вызовы:**

```python
# Было:
@flow(name="e2e-packet-runner")
def e2e_packet_runner_flow(packet_id: str):
    result = run_e2e_packet_task(packet_id)
    publish_artifact(result)

# Стало:
def execute_packet(packet_id: str):
    result = run_e2e_packet(packet_id)
    save_evidence_to_db(result)
```

❌ **Prefect work pools → DB queue:**

```python
# Было:
deployment = RunnerDeployment.from_entrypoint(
    work_pool_name="grace-process",
    work_queue_name="grace-live"
)

# Стало:
packet = claim_next_packet_from_db(worker_id)
```

❌ **Prefect artifacts → DB evidence:**

```python
# Было:
create_markdown_artifact(
    key="packet-result",
    markdown=result_md
)

# Стало:
db.execute("""
    INSERT INTO evidence_items (packet_run_id, type, path)
    VALUES (?, 'PACKET_RESULT', ?)
""", (run_id, result_path))
```

❌ **runtime_adapter.py → упрощаем:**

```python
# Было: PrefectRuntimeAdapter, DryRunRuntime, WorkflowRuntime
# Стало: NativeRuntime (один класс)

class NativeRuntime:
    def submit_packet_run(self, packet_id: str):
        # Просто ставим в очередь
        db.execute("UPDATE packets SET state='READY' WHERE id=?", (packet_id,))
    
    def read_run_status(self, packet_id: str):
        # Читаем из DB
        return db.execute("SELECT state FROM packets WHERE id=?", (packet_id,)).fetchone()
```

### 18.3 Что удаляем / упрощаем

#### 18.3.1 Удаляем полностью

❌ **Prefect-специфичные модули:**
- `deploy_live.py` — Prefect deployments
- `runtime.py` — PrefectAPIContext
- `flows/live_dashboard.py` — Prefect dashboard flow
- `flows/packet_lifecycle.py` — Prefect packet transition flow

❌ **Prefect dependencies:**
```toml
# Удаляем из pyproject.toml:
prefect = "^2.0.0"
prefect-docker = "^0.3.0"
```

❌ **Сложные verification profiles:**
```yaml
# Удаляем из project.yaml:
verification:
  backend_profiles:
    backend_quick: pytest tests/ -k "not slow"
    backend_full: pytest tests/
  frontend_profiles:
    frontend_quick: npm test -- --run
```

Заменяем на простые test_tiers (T0/T1/T2).

❌ **Monitoring queue:**
```yaml
# Удаляем из project.yaml:
workflow_runtime:
  queues:
    monitoring:
      name: grace-monitoring
      concurrency_limit: 1
  monitoring_interval_seconds: 300
```

Мониторинг делаем через events в DB.

❌ **Briefs в YAML:**
- `src/prefect_grace/briefs/*.yaml` — старые feature specs
- Architect теперь генерирует packets напрямую, не через briefs

#### 18.3.2 Упрощаем (оставляем но переписываем)

⚠️ **prefect_compat.py → no-op decorators:**

```python
# Было: импорт из Prefect
from prefect import flow, task, get_run_logger

# Стало: no-op заглушки
def flow(name=None, **kwargs):
    def decorator(fn):
        fn.__flow_name__ = name
        return fn
    return decorator

def task(name=None, **kwargs):
    def decorator(fn):
        fn.__task_name__ = name
        return fn
    return decorator

def get_run_logger():
    import logging
    return logging.getLogger("grace")

def tags(*args):
    def decorator(fn):
        return fn
    return decorator
```

Это позволит не переписывать все flows сразу — просто убираем Prefect import.

⚠️ **runtime_adapter.py → один класс вместо трёх:**

```python
# Было: PrefectRuntimeAdapter, DryRunRuntime, WorkflowRuntime (ABC)
# Стало: NativeRuntime (один класс)

class NativeRuntime:
    def __init__(self, db_url: str):
        self.db = create_engine(db_url)
    
    def submit_packet_run(self, packet_id: str):
        db.execute("UPDATE packets SET state='READY' WHERE id=?", (packet_id,))
    
    def read_run_status(self, packet_id: str):
        return db.execute("SELECT state FROM packets WHERE id=?", (packet_id,)).fetchone()
    
    def publish_artifact(self, packet_id: str, name: str, body: str):
        # Сохраняем в evidence_items
        pass
```

⚠️ **project.yaml → упрощённая структура:**

```yaml
# Удаляем:
workflow_runtime:
  type: prefect
  api_url: http://127.0.0.1:4200/api
  work_pool: grace-process

# Добавляем:
runtime:
  database_url: sqlite:///grace.db

# Упрощаем:
executors:
  default: codex-cli
  command: codex1
  roles:
    architect:
      model: claude-opus-4-8
    coder:
      model: claude-sonnet-4-6
```

⚠️ **CLI commands → убираем Prefect-зависимые:**

```bash
# Удаляем команды:
grace deploy              # Prefect deployment
grace queue-watcher       # Prefect queue monitoring
grace prefect-smoke       # Prefect smoke tests

# Оставляем/добавляем:
grace architect plan      # NEW
grace packet list         # NEW
grace packet status       # NEW
grace worker start        # NEW
grace init                # EXISTS
grace validate-config     # EXISTS
```

#### 18.3.3 Что НЕ трогаем (работает как есть)

✅ **Packet execution engine:**
- `platform/e2e_packet_runner.py`
- `platform/managed_packet_runner.py`
- Просто убираем @flow/@task декораторы

✅ **Worktree management:**
- `platform/worktree_manager.py`
- Работает независимо от Prefect

✅ **Evidence collection:**
- `platform/evidence_manifest.py`
- `platform/packet_artifacts.py`
- Меняем только storage (DB вместо Prefect artifacts)

✅ **Agent launcher:**
- `tasks/codex_launcher.py`
- `tasks/codex_launcher_helpers/command_builder.py`
- Работает как есть

✅ **Git operations:**
- `platform/git_mutation_gate.py`
- Используем для auto-merge

✅ **Models:**
- `models.py` — PacketStatus, FeatureStatus, etc.
- Оставляем все enums и dataclasses

✅ **Policy engine:**
- `policies/sandbox_policy.py`
- Работает независимо от Prefect

✅ **Storage:**
- `storage/file_backend.py`
- Дополняем DB storage, но file backend оставляем для evidence files

#### 18.3.4 Файлы для удаления (список)

```bash
# Prefect-специфичные
src/prefect_grace/deploy_live.py
src/prefect_grace/runtime.py
src/prefect_grace/flows/live_dashboard.py
src/prefect_grace/flows/packet_lifecycle.py

# Briefs (старый формат)
src/prefect_grace/briefs/*.yaml

# Prefect CLI commands
src/prefect_grace/cli_commands/prefect_smokes.py
src/prefect_grace/cli_commands/queue_watcher.py

# Verification profiles (заменяем на test_tiers)
# Удаляем секцию из project.yaml, не файлы
```

#### 18.3.5 Файлы для упрощения (список)

```bash
# Заменяем Prefect на no-op
src/prefect_grace/prefect_compat.py

# Упрощаем runtime adapter
src/prefect_grace/platform/runtime_adapter.py

# Убираем @flow/@task декораторы
src/prefect_grace/flows/e2e_packet_runner_flow.py
src/prefect_grace/flows/managed_packet_runner_flow.py
src/prefect_grace/flows/feature_pipeline.py
src/prefect_grace/flows/worktree_scope_lifecycle_flow.py
src/prefect_grace/flows/verifier_reviewer_handoff_flow.py

# Упрощаем project config loader
src/prefect_grace/platform/project_adapter.py
src/prefect_grace/runtime_config.py
```

#### 18.3.6 Оценка сложности миграции

**Простые изменения (1-2 дня):**
- ✅ Удалить Prefect dependencies
- ✅ Создать no-op prefect_compat.py
- ✅ Упростить project.yaml
- ✅ Удалить deploy_live.py, runtime.py

**Средние изменения (3-5 дней):**
- ⚠️ Создать DB schema
- ⚠️ Реализовать NativeRuntime
- ⚠️ Убрать @flow/@task из всех flows
- ⚠️ Заменить Prefect artifacts на DB evidence

**Сложные изменения (5-7 дней):**
- 🔴 Реализовать worker loop
- 🔴 Реализовать state machine
- 🔴 Интегрировать architect agent
- 🔴 Протестировать E2E flow

**Итого:** 9-14 дней для полной миграции.

### 18.4 Migration path

**Phase 1:** Создать NativeRuntime рядом с PrefectRuntimeAdapter

```python
# runtime_adapter.py
class NativeRuntime(WorkflowRuntime):
    def __init__(self, db_url: str):
        self.db = create_engine(db_url)
    
    def submit_packet_run(self, packet: dict, params: dict):
        # Enqueue в DB
        pass
```

**Phase 2:** Заменить все вызовы PrefectRuntimeAdapter на NativeRuntime

```python
# Было:
runtime = create_runtime("prefect", config)

# Стало:
runtime = create_runtime("native", config)
```

**Phase 3:** Удалить Prefect dependencies из pyproject.toml

```toml
# Удаляем:
# prefect = "^2.0.0"
# prefect-docker = "^0.3.0"
```

---

## 19. Architect Agent Prompt

### 19.1 System prompt

```markdown
You are GRACE Architect Agent.

Your role: Read feature specifications and generate a structured implementation plan with waves and packets.

## Input format

You will receive a feature specification in YAML format with:
- feature_id, title, summary
- impacted_surfaces (which parts of codebase)
- scope (what needs to be done)
- acceptance_criteria
- non_goals

## Output format

Generate a YAML plan with:

```yaml
feature:
  id: <feature_id from input>
  title: <feature title>
  description: <detailed description>

waves:
  - id: WAV-001
    title: "Wave 1: Foundation"
    description: "Core infrastructure and models"
    
    packets:
      - id: PKT-001
        title: "Add database models"
        description: "Create SQLAlchemy models for auth"
        scope:
          - "src/models/user.py"
          - "src/models/session.py"
          - "tests/models/test_user.py"
        complexity: medium
        risk: medium
        depends_on: []
        
      - id: PKT-002
        title: "Add JWT utilities"
        description: "Implement JWT token generation and validation"
        scope:
          - "src/auth/jwt.py"
          - "tests/auth/test_jwt.py"
        complexity: medium
        risk: high  # auth is always high risk
        depends_on: []
  
  - id: WAV-002
    title: "Wave 2: API endpoints"
    description: "Login and logout endpoints"
    
    packets:
      - id: PKT-003
        title: "Add login endpoint"
        description: "POST /api/auth/login endpoint"
        scope:
          - "src/api/auth.py"
          - "tests/api/test_auth.py"
        complexity: medium
        risk: high
        depends_on: ["PKT-001", "PKT-002"]
```

## Packet design principles

1. **Small packets:** Each packet should change < 200 lines of code
2. **Clear scope:** List exact files that will be touched
3. **Dependencies:** Mark dependencies between packets
4. **Risk assessment:** 
   - high risk: auth, billing, migrations, state machines
   - medium risk: business logic, API endpoints
   - low risk: docs, tests, logging
5. **Complexity:**
   - simple: docs, tests, config changes
   - medium: new features, refactoring
   - complex: architectural changes, multi-module refactors

## Wave design principles

1. **Logical grouping:** Group related packets into waves
2. **Foundation first:** Database models and core utilities before API
3. **Independent waves:** Waves should be executable in parallel where possible
4. **Clear boundaries:** Each wave should have a clear deliverable

## Risk classification rules

Mark as **high risk** if packet touches:
- Authentication or authorization
- Billing or payments
- Database migrations
- State machines or schedulers
- Security policies
- Production configuration

Mark as **medium risk** if packet:
- Adds new API endpoints
- Changes business logic
- Modifies existing features

Mark as **low risk** if packet:
- Updates documentation
- Adds tests
- Fixes typos
- Adds logging

## Example

Input:
```yaml
feature_id: FEAT-USER-PROFILE-001
title: "Add user profile page"
scope:
  - Add user profile API endpoint
  - Add profile update functionality
  - Add profile tests
```

Output:
```yaml
feature:
  id: FEAT-USER-PROFILE-001
  title: "Add user profile page"

waves:
  - id: WAV-001
    title: "Backend API"
    packets:
      - id: PKT-001
        title: "Add GET /api/users/me endpoint"
        scope:
          - "src/api/users.py"
          - "tests/api/test_users.py"
        complexity: simple
        risk: low
        depends_on: []
      
      - id: PKT-002
        title: "Add PUT /api/users/me endpoint"
        scope:
          - "src/api/users.py"
          - "tests/api/test_users.py"
        complexity: medium
        risk: medium
        depends_on: ["PKT-001"]
```

Now generate the plan for the given feature specification.
```

### 19.2 CLI integration

```python
def cmd_architect_plan(feature_spec_path: str):
    """Run architect agent to generate implementation plan."""
    
    # Read feature spec
    spec_yaml = Path(feature_spec_path).read_text()
    spec = yaml.safe_load(spec_yaml)
    
    # Build architect prompt
    prompt = f"""
{ARCHITECT_SYSTEM_PROMPT}

Feature specification:
```yaml
{spec_yaml}
```

Generate the implementation plan.
"""
    
    # Run architect agent
    result = run_codex_agent(
        role="architect",
        prompt=prompt,
        workdir=config.project_root,
    )
    
    # Parse result (expect YAML in code block)
    plan_yaml = extract_yaml_from_markdown(result)
    plan = yaml.safe_load(plan_yaml)
    
    # Validate plan structure
    validate_architect_plan(plan)
    
    # Register in DB
    register_feature_plan(plan)
    
    print(f"✓ Created feature {plan['feature']['id']}")
    print(f"✓ Created {len(plan['waves'])} waves")
    
    total_packets = sum(len(w['packets']) for w in plan['waves'])
    print(f"✓ Created {total_packets} packets")
    print(f"\nRun: grace worker start")
```

---

## 20. Следующие шаги

### 20.1 Реализация (порядок)

1. ✅ **Утвердить ТЗ**
2. **DB schema** — создать 8 таблиц в SQLite
3. **State machine** — реализовать 8 состояний + transitions
4. **Complexity router** — простая эвристика по file patterns
5. **Worker loop** — claim, execute, release lease
6. **Architect integration** — prompt + CLI команда
7. **CLI commands** — packet list/status, worker start
8. **Test на реальном feature** — запустить полный цикл
9. **Итерировать** — улучшать на основе опыта

### 20.2 Критерии готовности

MVP готов когда:

✅ Architect создаёт packets из feature spec
✅ Worker выполняет packet через существующий run_e2e_packet
✅ Tests запускаются (T0/T1/T2)
✅ Evidence собирается в DB
✅ Acceptance decision работает (FAST/NORMAL/STRICT)
✅ Auto-merge работает для ACCEPTED packets
✅ Events логируются в DB
✅ CLI команды работают

### 20.3 Метрики успеха

После MVP измеряем:

- **Fast path rate** — % пакетов принятых без reviewer
- **Escalation rate** — % пакетов требующих strong executor
- **Acceptance rate** — % пакетов принятых с первой попытки
- **Average packet time** — среднее время выполнения пакета
- **Cost per packet** — средняя стоимость (tokens)

---

**Конец спецификации v2.1**
