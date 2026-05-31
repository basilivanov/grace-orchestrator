# GRACE Control Plane — Executive Summary

## 🎯 Цель

Заменить Prefect на собственный GRACE Control Plane для AI-driven разработки.

**Use case:**
```text
Architect пишет ТЗ → grace architect plan feature.yaml → утром готовый код
```

---

## ✅ Что уже есть (переиспользуем)

- ✅ Packet execution engine (`run_e2e_packet`, `run_managed_packet`)
- ✅ Worktree management
- ✅ Evidence collection
- ✅ Agent launcher (codex_launcher)
- ✅ Git merge logic
- ✅ Models (PacketStatus, ReviewVerdict, etc.)
- ✅ Policy engine
- ✅ Test runner

**Просто убираем Prefect декораторы — бизнес-логика остаётся.**

---

## 🔄 Что заменяем

| Было (Prefect) | Стало (Native) |
|----------------|----------------|
| @flow/@task decorators | Прямые вызовы функций |
| Work pools & queues | SQLite/Postgres queue |
| Prefect artifacts | Evidence в DB |
| Prefect deployments | Worker loop |
| Flow tracking | Events в DB |

---

## 📊 Архитектура

### Упрощённая модель

```text
Feature spec (YAML)
  ↓
Architect Agent → генерирует Waves + Packets
  ↓
Packets → READY в DB
  ↓
Worker → claim → execute → tests → accept/reject
  ↓
Evidence → DB
  ↓
Auto-merge (если ACCEPTED)
```

### State machine (8 состояний)

```text
DRAFT → READY → RUNNING → TESTING → [REVIEW] → ACCEPTED/REJECTED → MERGED
                                                      ↓
                                                   FAILED
```

### Acceptance profiles (3 уровня)

```text
FAST    — T0+T1, no reviewer, auto-accept
NORMAL  — T0+T1+T2, optional reviewer
STRICT  — T0+T1+T2, reviewer required
```

---

## 🗄️ Database (SQLite → Postgres)

**8 таблиц:**
- packets — основное состояние
- packet_runs — попытки выполнения
- agent_runs — запуски агентов
- test_runs — запуски тестов
- evidence_items — доказательства
- events — audit trail
- workers — активные воркеры
- leases — блокировки пакетов

**Migration path:**
```python
DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:///grace.db")
# Production: postgresql://user:pass@localhost/grace
```

---

## 🛠️ CLI

### Architect workflow

```bash
# 1. Пишет ТЗ
vim my-feature.yaml

# 2. Запускает architect agent
grace architect plan my-feature.yaml
# → Создаёт Feature, Waves, Packets в DB

# 3. Запускает worker
grace worker start
# → Worker выполняет packets по очереди

# 4. Проверяет результаты
grace packet list
grace packet status PKT-001
grace packet evidence PKT-001
```

### Команды

```bash
# Architect
grace architect plan <feature.yaml>
grace architect status

# Packets
grace packet list
grace packet status <id>
grace packet events <id>
grace packet evidence <id>
grace packet accept <id>
grace packet reject <id>

# Worker
grace worker start
grace worker status
grace worker stop

# System
grace init
grace db migrate
grace validate-config
```

---

## 📝 Configuration (project.yaml)

### Упрощённая версия

```yaml
version: 2

project:
  key: my-project
  root: /path/to/project
  default_branch: main

runtime:
  state_root: /var/lib/grace/my-project
  database_url: sqlite:///grace.db

executors:
  default: codex-cli
  command: codex1
  roles:
    architect:
      model: claude-opus-4-8
    coder:
      model: claude-sonnet-4-6
    reviewer:
      model: claude-opus-4-8

test_tiers:
  T0:
    name: "Mechanical checks"
    commands: ["ruff check .", "mypy src"]
  T1:
    name: "Touched scope tests"
    resolver: "touched_scope"
  T2:
    name: "Full unit tests"
    commands: ["pytest tests/unit -v"]

acceptance:
  fast:
    test_tiers: ["T0", "T1"]
    reviewer_required: false
  normal:
    test_tiers: ["T0", "T1", "T2"]
    reviewer_required: false
  strict:
    test_tiers: ["T0", "T1", "T2"]
    reviewer_required: true
```

### Что удалили

❌ Prefect-специфичные поля:
```yaml
workflow_runtime:
  type: prefect
  api_url: http://127.0.0.1:4200/api
  work_pool: grace-process
```

❌ Сложные verification profiles
❌ Monitoring queue
❌ Codex-специфичные поля (перенесли в executors.roles)

---

## 🤖 Architect Agent

### Input (feature spec)

```yaml
feature_id: FEAT-USER-AUTH-001
title: "Add user authentication"
summary: "Implement JWT-based auth"

scope:
  - Add JWT token generation
  - Add login/logout endpoints
  - Add auth tests

acceptance_criteria:
  - Login returns valid JWT
  - Protected endpoints require token
  - All tests pass
```

### Output (generated plan)

```yaml
feature:
  id: FEAT-USER-AUTH-001
  title: "Add user authentication"

waves:
  - id: WAV-001
    title: "Foundation"
    packets:
      - id: PKT-001
        title: "Add JWT utilities"
        scope: ["src/auth/jwt.py", "tests/auth/test_jwt.py"]
        complexity: medium
        risk: high
        depends_on: []
      
      - id: PKT-002
        title: "Add login endpoint"
        scope: ["src/api/auth.py", "tests/api/test_auth.py"]
        complexity: medium
        risk: high
        depends_on: ["PKT-001"]
```

Architect сам регистрирует packets в DB.

---

## 🔧 Worker Loop

```python
while True:
    # Claim packet with lease
    packet = claim_next_packet(worker_id)
    
    if packet:
        try:
            # Execute (используем существующий код)
            result = run_e2e_packet(packet_id=packet.id)
            
            # Run tests
            run_test_tiers(packet, result)
            
            # Check acceptance
            decision = check_acceptance(packet, result)
            
            if decision.accept:
                packet.state = "ACCEPTED"
                # Auto-merge
                merge_packet(packet)
            else:
                packet.state = "REJECTED"
        
        finally:
            release_lease(packet.id, worker_id)
    else:
        time.sleep(5)
```

---

## 🗑️ Что удаляем

### Файлы для удаления

```bash
src/prefect_grace/deploy_live.py
src/prefect_grace/runtime.py
src/prefect_grace/flows/live_dashboard.py
src/prefect_grace/flows/packet_lifecycle.py
src/prefect_grace/briefs/*.yaml
src/prefect_grace/cli_commands/prefect_smokes.py
src/prefect_grace/cli_commands/queue_watcher.py
```

### Dependencies

```toml
# Удаляем из pyproject.toml:
prefect = "^2.0.0"
prefect-docker = "^0.3.0"
```

---

## ⚙️ Что упрощаем

### prefect_compat.py → no-op

```python
def flow(name=None, **kwargs):
    def decorator(fn):
        return fn
    return decorator

def task(name=None, **kwargs):
    def decorator(fn):
        return fn
    return decorator
```

### runtime_adapter.py → один класс

```python
# Было: PrefectRuntimeAdapter, DryRunRuntime, WorkflowRuntime
# Стало: NativeRuntime

class NativeRuntime:
    def submit_packet_run(self, packet_id):
        db.execute("UPDATE packets SET state='READY' WHERE id=?", (packet_id,))
```

### Flows → убираем декораторы

```python
# Было:
@flow(name="e2e-packet-runner")
def e2e_packet_runner_flow(packet_id):
    result = run_e2e_packet_task(packet_id)

# Стало:
def execute_packet(packet_id):
    result = run_e2e_packet(packet_id)
```

---

## 📅 План реализации

### Phase 1 — Core (1-2 недели)

```text
✓ DB schema (8 таблиц)
✓ State machine (8 состояний)
✓ Complexity router (file patterns)
✓ Worker loop with lease
✓ Test tiers T0/T1/T2
✓ Acceptance checker
✓ CLI commands
✓ Event logging
```

### Phase 2 — Production (1-2 недели)

```text
✓ Review integration
✓ Rework loop
✓ Escalation (cheap → normal → strong)
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

## ✅ Критерии готовности MVP

MVP готов когда:

- ✅ Architect создаёт packets из feature spec
- ✅ Worker выполняет packet через run_e2e_packet
- ✅ Tests запускаются (T0/T1/T2)
- ✅ Evidence собирается в DB
- ✅ Acceptance decision работает (FAST/NORMAL/STRICT)
- ✅ Auto-merge работает для ACCEPTED packets
- ✅ Events логируются в DB
- ✅ CLI команды работают

---

## 📊 Оценка сложности

**Простые изменения (1-2 дня):**
- Удалить Prefect dependencies
- Создать no-op prefect_compat.py
- Упростить project.yaml

**Средние изменения (3-5 дней):**
- Создать DB schema
- Реализовать NativeRuntime
- Убрать @flow/@task декораторы
- Заменить Prefect artifacts на DB

**Сложные изменения (5-7 дней):**
- Реализовать worker loop
- Реализовать state machine
- Интегрировать architect agent
- Протестировать E2E flow

**Итого:** 9-14 дней для полной миграции.

---

## 🎯 Ключевые преимущества

1. **GRACE-native** — не универсальный DAG, а packet-centric
2. **Acceptance profiles** — FAST/NORMAL/STRICT с автоклассификацией
3. **Complexity routing** — дешёвые модели для простых задач
4. **Evidence-first** — всё в DB, не артефакты
5. **Policy engine** — можно/нельзя принять без reviewer
6. **Audit trail** — каждое решение записано
7. **Нет внешних зависимостей** — не нужен Prefect server
8. **Architect-driven** — ТЗ → packets автоматически

---

## 📖 Полная спецификация

См. `GRACE_CONTROL_PLANE_SPEC.md` для детального ТЗ.
