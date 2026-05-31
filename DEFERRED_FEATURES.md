# GRACE Control Plane — Deferred Features

## 📋 Функции отложенные на следующие волны

Эти функции **НЕ входят в MVP**, но будут добавлены в следующих волнах разработки.

---

## Wave 2: Essential Operations (после MVP)

### 1. Packet Cancellation ✅ Добавляем в MVP
**Приоритет:** Критично
**Время:** 1 день

**Функциональность:**
```bash
grace packet cancel PKT-001
# Останавливает выполнение, rollback изменений
```

**Что нужно:**
- API endpoint: `POST /api/packets/{packet_id}/cancel`
- Worker проверяет cancellation flag
- Graceful shutdown текущей операции
- Cleanup worktree
- State: RUNNING → CANCELLED

---

### 2. Health Checks ✅ Добавляем в MVP
**Приоритет:** Критично
**Время:** 1 день

**Функциональность:**
```bash
GET /api/health
→ {
  "status": "healthy",
  "workers": {
    "active": 3,
    "idle": 1,
    "dead": 0
  },
  "queue_depth": 5,
  "executors": {
    "claude-opus-api": "healthy",
    "gemini-flash-api": "degraded"
  },
  "db": "healthy",
  "disk_space_gb": 45.2
}
```

**Что проверяем:**
- Workers alive (heartbeat)
- Executors reachable (ping)
- DB connection
- Disk space
- Queue depth

---

### 3. Conflict Resolution (Automatic Rebase)
**Приоритет:** Высокий
**Время:** 2 дня

**Проблема:**
```
Packet A изменил src/auth/jwt.py → merged
Packet B тоже изменил src/auth/jwt.py → outdated
```

**Решение:**
```
Packet B → NEEDS_REBASE
  ↓
Автоматический rebase на новый main
  ↓
Retry execution
```

**Что нужно:**
- Detect outdated packets (base commit != current main)
- Automatic git rebase
- Conflict detection
- If conflicts → NEEDS_MANUAL_REBASE (escalate к вам)
- If no conflicts → retry

---

### 4. Human Review Queue
**Приоритет:** Высокий
**Время:** 2 дня

**Функциональность:**
```
Reviewer agent отклонил packet
  ↓
Packet → NEEDS_HUMAN_REVIEW
  ↓
Вы смотрите в UI
  ↓
[Approve] → retry | [Reject] → FAILED
```

**UI:**
```
┌─────────────────────────────────────────────────┐
│ Human Review Queue (3)                          │
├─────────────────────────────────────────────────┤
│                                                 │
│ 📦 PKT-001 (rejected by reviewer)              │
│    Reason: "Missing error handling"            │
│    [View Code] [Approve] [Reject]              │
│                                                 │
│ 📦 PKT-005 (3 failed attempts)                 │
│    Reason: "Tests keep failing"                │
│    [View Code] [Approve] [Reject]              │
│                                                 │
└─────────────────────────────────────────────────┘
```

---

### 5. Audit Trail API
**Приоритет:** Средний
**Время:** 1 день

**Функциональность:**
```bash
GET /api/audit?entity=packet&entity_id=PKT-001
→ Все события для этого packet

GET /api/audit?entity=feature&entity_id=FEAT-001
→ Все события для feature

GET /api/audit?user=architect&action=create
→ Все создания от architect
```

**События:**
- packet_created, packet_claimed, packet_accepted, packet_rejected
- state_transition, merge_completed
- worker_started, worker_died
- executor_called, executor_failed

---

## Wave 3: Advanced Features

### 6. Dry Run Mode
**Приоритет:** Средний
**Время:** 2 дня

**Функциональность:**
```bash
grace packet run PKT-001 --dry-run
# Показывает что будет сделано, но не делает

grace architect plan feature.yaml --dry-run
# Показывает какие packets будут созданы
```

**Что показывает:**
- Какие файлы будут изменены
- Какие тесты будут запущены
- Какие проверки будут выполнены
- Estimated duration
- Estimated cost (если считаем)

---

### 7. Webhook Notifications
**Приоритет:** Средний
**Время:** 1 день

**Функциональность:**
```yaml
notifications:
  webhooks:
    - url: https://hooks.slack.com/services/...
      events: [packet_accepted, packet_failed, feature_completed]
      headers:
        Authorization: "Bearer token"
    
    - url: https://discord.com/api/webhooks/...
      events: [packet_failed]
```

**Payload:**
```json
{
  "event": "packet_accepted",
  "timestamp": "2026-05-31T10:05:00Z",
  "packet_id": "FEAT-X-W01-P01-CREATE-JWT-UTILS",
  "feature_id": "FEAT-X",
  "attempt": 2,
  "duration_ms": 45000
}
```

---

### 8. Feature Dependencies
**Приоритет:** Низкий
**Время:** 2 дня

**Функциональность:**
```yaml
features:
  - id: FEAT-USER-AUTH
    status: IN_PROGRESS
  
  - id: FEAT-ADMIN-PANEL
    depends_on: [FEAT-USER-AUTH]
    status: BLOCKED  # Ждёт пока USER-AUTH завершится
```

**Логика:**
- Feature B не начинается пока Feature A не завершена
- UI показывает dependency graph
- Architect учитывает dependencies при планировании

---

### 9. Packet Priority
**Приоритет:** Низкий
**Время:** 1 день

**Функциональность:**
```yaml
packet:
  priority: high  # high | normal | low
```

**Логика:**
- Worker берёт сначала high priority packets
- Hotfixes получают high priority
- Обычные packets — normal
- Cleanup/refactoring — low

---

### 10. Worker Capabilities
**Приоритет:** Низкий
**Время:** 2 дня

**Функциональность:**
```yaml
worker:
  capabilities:
    - python
    - typescript
    - docker
    - playwright

packet:
  required_capabilities:
    - typescript
    - playwright
```

**Логика:**
- Worker claim только packets с matching capabilities
- Architect учитывает capabilities при создании packets

---

## Wave 4: Production Features

### 11. Rate Limiting
**Приоритет:** Средний
**Время:** 2 дня

**Функциональность:**
```yaml
executors:
  - id: claude-opus-api
    rate_limit:
      requests_per_minute: 50
      tokens_per_minute: 100000
      concurrent_requests: 5
```

**Логика:**
- Executor queue с rate limiting
- Backoff при достижении лимита
- Retry с exponential backoff

---

### 12. Resource Limits
**Приоритет:** Низкий
**Время:** 2 дня

**Функциональность:**
```yaml
packet:
  resources:
    memory_mb: 4096
    cpu_cores: 2
    timeout_minutes: 30
    disk_gb: 10

worker:
  resources:
    memory_mb: 8192
    cpu_cores: 4
    disk_gb: 100
```

**Логика:**
- Worker claim только packets с достаточными ресурсами
- Monitoring resource usage
- Kill packet если превышает лимиты

---

### 13. Cost Budget
**Приоритет:** Низкий
**Время:** 2 дня

**Функциональность:**
```yaml
feature:
  budget:
    max_cost_usd: 10.00
    current_cost_usd: 7.50
    remaining_usd: 2.50
    alert_threshold_usd: 8.00
```

**Логика:**
- Считаем tokens для API executors
- Останавливаем feature при превышении бюджета
- Уведомление при достижении threshold

---

### 14. Evidence Retention
**Приоритет:** Низкий
**Время:** 1 день

**Функциональность:**
```yaml
evidence:
  retention:
    keep_days: 30              # По умолчанию
    keep_successful: 7         # Успешные packets
    keep_failed: 30            # Failed packets дольше
    keep_screenshots: 14       # Скриншоты
    compress_after_days: 7     # Сжимать старые
```

**Логика:**
- Cron job чистит старые артефакты
- Сжимает старые логи (gzip)
- Оставляет metadata в DB

---

### 15. Scheduled Execution
**Приоритет:** Низкий
**Время:** 1 день

**Функциональность:**
```yaml
packet:
  schedule:
    start_after: "2026-06-01T00:00:00Z"
    start_before: "2026-06-01T06:00:00Z"
```

**Логика:**
- Packet создаётся, но не выполняется
- State: SCHEDULED
- Cron job проверяет scheduled packets
- Переводит в READY в нужное время

---

## Wave 5: Advanced Operations

### 16. Packet Templates
**Приоритет:** Низкий
**Время:** 2 дня

**Функциональность:**
```yaml
templates:
  - name: crud-entity
    description: "Add CRUD operations for entity"
    variables:
      - name: entity
        type: string
    packets:
      - title: "Add {entity} model"
        scope: "src/models/{entity}.py"
      - title: "Add {entity} API endpoints"
        scope: "src/api/{entity}.py"
      - title: "Add {entity} tests"
        scope: "tests/test_{entity}.py"
```

**Usage:**
```bash
grace template apply crud-entity --var entity=Product
# Создаёт 3 packets для Product CRUD
```

---

### 17. Packet Cloning
**Приоритет:** Низкий
**Время:** 1 день

**Функциональность:**
```bash
grace packet clone PKT-001 --change "scope=src/admin/"
# Клонирует PKT-001 с изменённым scope
```

---

### 18. Rollback Automation
**Приоритет:** Средний
**Время:** 2 дня

**Функциональность:**
```bash
grace packet rollback PKT-001
# Создаёт revert commit

grace feature rollback FEAT-001
# Откатывает все packets из feature
```

---

### 19. Partial Success
**Приоритет:** Низкий
**Время:** 3 дня

**Функциональность:**
- Packet изменил 5 файлов
- 4 OK, 1 failed
- Можно принять 4, отклонить 1
- Создаётся новый packet для failed файла

**Сложно реализовать, низкий приоритет**

---

### 20. Multi-tenant / Multi-project
**Приоритет:** Низкий
**Время:** 1 неделя

**Функциональность:**
- Несколько проектов на одном Control Plane
- Изоляция данных
- Разные workers для разных проектов
- Authentication & authorization

**Большая фича, только если нужно**

---

## 🚫 НЕ делаем (пока)

### Self-improvement (Оркестратор пилит сам себя)
**Решение:** Отложено

**Почему:**
- Усложняет MVP
- Нужны дополнительные safety checks
- Можно добавить позже как отдельную волну

**Когда добавим:**
- После MVP
- Когда оркестратор стабилен
- Когда есть хорошее покрытие тестами

**Что нужно для self-improvement:**
- Self-improvement mode в project.yaml
- Backup mechanism перед изменениями
- Safety checks (forbidden files)
- Require tests + reviewer
- Manual merge (не auto)
- Restart mechanism

**Оценка:** +3 дня к реализации

---

## 📊 Приоритизация

### ✅ Добавляем в MVP (2 дня)
1. Packet cancellation (1 день)
2. Health checks (1 день)

### 🟡 Wave 2 — Essential Operations (1 неделя)
3. Conflict resolution (2 дня)
4. Human review queue (2 дня)
5. Audit trail API (1 день)

### 🟢 Wave 3 — Advanced Features (1 неделя)
6. Dry run mode (2 дня)
7. Webhook notifications (1 день)
8. Feature dependencies (2 дня)
9. Packet priority (1 день)
10. Worker capabilities (2 дня)

### 🔵 Wave 4 — Production Features (1 неделя)
11. Rate limiting (2 дня)
12. Resource limits (2 дня)
13. Cost budget (2 дня)
14. Evidence retention (1 день)
15. Scheduled execution (1 день)

### 🟣 Wave 5 — Advanced Operations (1.5 недели)
16. Packet templates (2 дня)
17. Packet cloning (1 день)
18. Rollback automation (2 дня)
19. Partial success (3 дня)
20. Multi-tenant (1 неделя)

### 🚫 Не делаем пока
- Self-improvement

---

## 📅 Обновлённый Roadmap

### MVP (4.5 недели)
- Phase 0: Cleanup (3 дня)
- Phase 1: Core (1.5 недели)
- Phase 2: API & Worker (1 неделя)
- Phase 3: UI & CLI (1 неделя)
- **Phase 3.5: Cancellation + Health (2 дня)** ← новое
- Phase 4: Testing (1 неделя)

### Post-MVP
- Wave 2: Essential Operations (1 неделя)
- Wave 3: Advanced Features (1 неделя)
- Wave 4: Production Features (1 неделя)
- Wave 5: Advanced Operations (1.5 недели)

---

## ✅ Итого

**MVP:** 4.5 недели (было 4 недели, +2 дня на cancellation + health)

**Все остальные фичи:** Отложены на следующие волны

**Self-improvement:** Отложено, можно добавить позже
