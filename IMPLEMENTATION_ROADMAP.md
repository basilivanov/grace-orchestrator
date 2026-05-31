# GRACE Control Plane — Implementation Roadmap

## 📅 Общий план: 4-5 недель до MVP

---

## Phase 0: Подготовка (2-3 дня)

### Цель: Вычистить legacy, подготовить структуру

**Задачи:**
1. Удалить Prefect dependencies из pyproject.toml
2. Удалить Prefect-специфичные файлы:
   - `deploy_live.py`
   - `runtime.py`
   - `flows/live_dashboard.py`
   - `flows/packet_lifecycle.py`
3. Удалить старые briefs (`briefs/*.yaml`)
4. Создать новую структуру проекта:
   ```
   src/grace_control/
   ├── api/          # FastAPI server
   ├── core/         # Core logic
   ├── worker/       # Worker process
   ├── cli/          # Thin CLI
   ├── platform/     # Existing code (reuse)
   └── models.py     # Domain models
   ```
5. Создать `prefect_compat.py` с no-op декораторами

**Критерий готовности:**
- ✅ Нет Prefect зависимостей
- ✅ Проект запускается без ошибок
- ✅ Существующие тесты проходят

---

## Phase 1: Core Infrastructure (1.5 недели)

### Week 1, Days 1-2: Database & Models

**Task #10: DB Schema**
- Создать SQLite schema (8 таблиц)
- Иерархические ID (FEAT-X-W01-P01-ACTION-R01)
- JSON columns для structured data
- SQLAlchemy models
- Alembic migrations

**Deliverable:** Рабочая БД с миграциями

---

### Week 1, Days 3-4: State Machine & Acceptance

**Task #11: State Machine**
- 8 состояний (DRAFT → READY → RUNNING → TESTING → REVIEW → ACCEPTED/REJECTED → MERGED/FAILED)
- Ступенчатая приёмка (T0 → T1 → T2 → Canon → Reviewer)
- Early exit для экономии токенов
- State transitions с логированием

**Task #24: Acceptance Policy**
- AcceptancePolicyInterface (abstract)
- SimplePolicy (tests passed → accept)
- Поддержка FAST/NORMAL/STRICT profiles

**Deliverable:** State machine с acceptance logic

---

### Week 1, Days 4-5: Executors & Routers

**Task #22: Executor Abstraction**
- ExecutorInterface (abstract)
- APIProvider (Anthropic, Google, OpenAI, DeepSeek)
- LocalProvider (Ollama, Antigravity, vLLM)
- Escalation support (cheap → medium → strong)

**Task #13: Complexity Router**
- ComplexityRouterInterface (abstract)
- HeuristicRouter (file patterns + diff size)
- Can escalate acceptance profile

**Deliverable:** Pluggable executors и routers

---

### Week 2, Days 1-2: GRACE Canon & Testing

**Task #23: GRACE Canon Checker**
- File size limit (1000 lines)
- Function size limit (4000 tokens)
- Contracts validation (AI_HEADER, MODULE_CONTRACT, etc.)
- Semantic blocks validation
- grace-lint integration

**Task #32: Test Infrastructure**
- Test tier definitions (T0/T1/T2/T3/T4)
- Touched scope resolver
- Parallel execution (pytest-xdist)
- Structured test results (JSON)

**Deliverable:** GRACE Canon + test execution

---

### Week 2, Day 3: Logging

**Task #31: Logging Infrastructure**
- StructuredLogger с component-level config
- JsonFormatter для JSONL
- Trace ID propagation
- Debug mode
- Log rotation

**Deliverable:** Structured logging везде

---

## Phase 2: API & Worker (1 неделя)

### Week 2, Days 4-5: FastAPI Server

**Task #18: FastAPI Server**
- Routers: features, packets, workers, architect, system, artifacts
- Pydantic models для requests/responses
- WebSocket для real-time updates
- Artifact endpoints с image support
- Thumbnail generation (Pillow)

**Deliverable:** Рабочий API server

---

### Week 3, Days 1-2: Worker Loop

**Task #12: Worker Loop**
- Claim/release packets via API
- Heartbeat mechanism
- Lease management
- Интеграция с существующим run_e2e_packet()
- Retry logic с escalation

**Task #21: Worker API Client**
- Worker как API client
- Registration, heartbeat, claim, release
- Error handling

**Deliverable:** Рабочий worker

---

### Week 3, Day 3: Architect Integration

**Task #27: Architect Agent**
- Читает feature spec (YAML)
- Читает XML artifacts (requirements, technology, etc.)
- Генерирует иерархические ID
- Генерирует waves и packets
- POST /api/architect/plan endpoint

**Deliverable:** Architect создаёт packets

---

## Phase 3: UI & CLI (1 неделя)

### Week 3, Days 4-5: Artifact Viewer

**Task #19: JSON Artifacts**
- Artifact storage structure
- packet.json, result.json, agent/output.json
- tests/*.json, logs.jsonl
- Evidence manifest

**Task #29: Artifact Viewer**
- Backend: artifact endpoints, thumbnail generation
- Frontend: ScreenshotGallery, Lightbox
- JsonArtifactView, TextArtifactView
- VisualRegressionView (before/after/diff)

**Deliverable:** Artifact viewer с изображениями

---

### Week 4, Days 1-2: HTML Dashboard

**Task #30: HTML Dashboard**
- grace-ui.html (single file)
- Features list, feature detail, packet detail
- Workers status
- Real-time updates (WebSocket)
- Hierarchical ID display

**Deliverable:** Рабочий UI

---

### Week 4, Day 3: CLI Wrapper

**Task #20: CLI Wrapper**
- GraceAPIClient (httpx)
- Click commands (architect, packet, worker)
- Rich output formatting
- JSON output mode для агентов

**Deliverable:** Thin CLI

---

### Week 4, Day 4: Telegram Bot

**Task #25: Telegram Bot**
- Feature started/completed/failed
- Packet accepted/rejected/failed
- Worker died, system unhealthy
- Human-readable messages

**Deliverable:** Telegram notifications

---

### Week 4, Day 5: Init Command

**Task #26: grace init**
- Interactive wizard
- Создаёт grace/ directory
- Генерирует project.yaml
- Генерирует XML artifacts

**Deliverable:** Project initialization

---

## Phase 4: Testing & Polish (1 неделя)

### Week 5, Days 1-3: E2E Testing

**Task #17: E2E Test**
- Запустить полный цикл:
  - Start API server
  - Start worker
  - Create feature via architect
  - Worker выполняет packets
  - Tests run, evidence collected
  - Acceptance decision
  - Auto-merge
- Проверить все артефакты (JSON, logs, screenshots)
- Проверить UI (все страницы работают)
- Проверить Telegram notifications

**Deliverable:** Рабочий E2E flow

---

### Week 5, Days 4-5: Documentation & Polish

**Задачи:**
1. Обновить README.md
2. Написать QUICKSTART.md
3. Написать API.md (API documentation)
4. Написать DEVELOPMENT.md
5. Проверить все GRACE Canon compliance
6. Финальный cleanup кода
7. Финальные тесты

**Deliverable:** Готовый к использованию MVP

---

## 📊 Зависимости задач

```
Phase 0 (Cleanup)
  ↓
#10 (DB Schema)
  ↓
├─ #11 (State Machine) ──→ #12 (Worker Loop)
├─ #13 (Complexity Router)
├─ #22 (Executor Abstraction)
├─ #23 (GRACE Canon)
├─ #24 (Acceptance Policy)
├─ #31 (Logging)
└─ #32 (Test Infrastructure)
  ↓
#18 (FastAPI Server)
  ↓
├─ #19 (JSON Artifacts)
├─ #21 (Worker API Client) ──→ #12 (Worker Loop)
├─ #27 (Architect Integration)
└─ #29 (Artifact Viewer)
  ↓
├─ #20 (CLI Wrapper)
├─ #25 (Telegram Bot)
├─ #26 (grace init)
└─ #30 (HTML Dashboard)
  ↓
#17 (E2E Test)
  ↓
Documentation & Polish
```

---

## 🎯 Критические пути (Critical Path)

**Longest path (определяет минимальное время):**
```
Phase 0 (3 дня)
  ↓
#10 DB Schema (2 дня)
  ↓
#11 State Machine (2 дня)
  ↓
#12 Worker Loop (2 дня)
  ↓
#18 FastAPI Server (2 дня)
  ↓
#30 HTML Dashboard (2 дня)
  ↓
#17 E2E Test (3 дня)
  ↓
Polish (2 дня)

= 18 дней (3.5 недели)
```

**С параллельной работой:** 4-5 недель

---

## 👥 Распределение работы (если несколько человек)

### Developer 1: Backend Core
- Phase 0: Cleanup
- #10: DB Schema
- #11: State Machine
- #24: Acceptance Policy
- #31: Logging

### Developer 2: Executors & Tests
- #22: Executor Abstraction
- #13: Complexity Router
- #23: GRACE Canon
- #32: Test Infrastructure

### Developer 3: API & Worker
- #18: FastAPI Server
- #12: Worker Loop
- #21: Worker API Client
- #27: Architect Integration

### Developer 4: UI & CLI
- #19: JSON Artifacts
- #29: Artifact Viewer
- #30: HTML Dashboard
- #20: CLI Wrapper
- #25: Telegram Bot
- #26: grace init

### All: E2E Testing
- #17: E2E Test
- Documentation & Polish

**С 4 разработчиками:** 2-3 недели

---

## 📈 Прогресс tracking

### Week 1 Goals
- ✅ Phase 0 complete
- ✅ DB Schema ready
- ✅ State Machine working
- ✅ Executors pluggable

### Week 2 Goals
- ✅ GRACE Canon checking
- ✅ Test infrastructure
- ✅ Logging everywhere
- ✅ FastAPI server running

### Week 3 Goals
- ✅ Worker loop working
- ✅ Architect integration
- ✅ Artifact viewer ready

### Week 4 Goals
- ✅ HTML Dashboard working
- ✅ CLI wrapper ready
- ✅ Telegram bot sending
- ✅ grace init working

### Week 5 Goals
- ✅ E2E test passing
- ✅ Documentation complete
- ✅ MVP ready to use

---

## 🚀 Quick Start после MVP

```bash
# 1. Initialize project
cd /path/to/your/project
grace init

# 2. Start API server
grace-api serve

# 3. Start worker (другой терминал)
grace worker start

# 4. Create feature
grace architect plan my-feature.yaml

# 5. Watch progress
# - Open http://localhost:8000 (UI)
# - Or: grace packet list
# - Or: Telegram notifications

# 6. Profit! 🎉
```

---

## 📋 Checklist для MVP

### Core Functionality
- [ ] Architect создаёт packets из feature spec
- [ ] Packets имеют иерархические ID (FEAT-X-W01-P01-ACTION-R01)
- [ ] Worker выполняет packets через run_e2e_packet
- [ ] Ступенчатая приёмка работает (T0 → T1 → T2 → Canon → Reviewer)
- [ ] GRACE Canon проверки работают
- [ ] Evidence собирается в JSON
- [ ] Acceptance decision работает (FAST/NORMAL/STRICT)
- [ ] Auto-merge работает
- [ ] Retry с escalation работает

### Infrastructure
- [ ] DB schema с миграциями
- [ ] State machine с transitions
- [ ] Executor abstraction (API + local)
- [ ] Complexity router
- [ ] Acceptance policy
- [ ] Structured logging с trace_id
- [ ] Test infrastructure (T0/T1/T2)

### API & UI
- [ ] FastAPI server работает
- [ ] WebSocket real-time updates
- [ ] Artifact endpoints с thumbnails
- [ ] HTML dashboard показывает иерархию
- [ ] Artifact viewer с изображениями
- [ ] Screenshot gallery с lightbox
- [ ] Visual regression comparison

### CLI & Notifications
- [ ] CLI wrapper работает
- [ ] JSON output для агентов
- [ ] Telegram bot отправляет уведомления
- [ ] grace init создаёт проект

### Testing & Documentation
- [ ] E2E test проходит
- [ ] Все компоненты GRACE Canon compliant
- [ ] README.md обновлён
- [ ] QUICKSTART.md написан
- [ ] API.md написан

---

## 🎯 Success Metrics

**После MVP измеряем:**
- Fast path rate — % packets принятых без reviewer
- Escalation rate — % packets требующих strong executor
- Acceptance rate — % packets принятых с первой попытки
- Average packet time — среднее время выполнения
- Test tier pass rates — T0/T1/T2 pass rates

**Цели для MVP:**
- Fast path rate > 60%
- Acceptance rate > 70%
- Average packet time < 5 минут
- T0 pass rate > 95%

---

**Roadmap готов. Начинаем реализацию!** 🚀
