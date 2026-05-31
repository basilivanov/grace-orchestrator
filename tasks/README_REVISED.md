# GRACE Control Plane - Task Specifications (REVISED)

**Версия:** 2.0 (исправлены противоречия)
**Дата:** 2026-05-31

**ВАЖНО:** Следуйте CANONICAL_DECISIONS.md — единственному источнику правды!

---

## 📋 Overview

Этот документ содержит исправленные ТЗ для MVP-0 vertical slice.

**Цель:** Минимальный рабочий Control Plane за 2.5 недели.

---

## 🎯 MVP-0 Scope

### Что ВКЛЮЧЕНО в MVP-0

✅ **Phase 0:** Cleanup (2 дня)
- Prefect compatibility layer
- Package structure
- Dev environment

✅ **Phase 1:** Core Infrastructure (1 неделя)
- DB schema (7 таблиц, 8 states)
- State machine
- PacketExecutionAdapter

✅ **Phase 2:** API & Worker (1 неделя)
- FastAPI server (canonical endpoints)
- Worker loop (lease mechanism)

✅ **Phase 3:** CLI & E2E Test (2 дня)
- CLI commands
- E2E test

**Итого: 2.5 недели**

### Что НЕ ВКЛЮЧЕНО в MVP-0

❌ UI/Dashboard
❌ Telegram notifications
❌ WebSocket
❌ Image viewer
❌ Cancellation
❌ GRACE Canon checker
❌ Complexity router
❌ Multiple workers (parallel)
❌ Acceptance policies (только simple)

---

## 📁 Revised Task Files

### Phase 0: Cleanup & Preparation
**Файл:** `tasks/PHASE_0_CLEANUP_REVISED.md`

**Задачи:**
- Task 0.1: Add Prefect Compatibility Layer (2 часа)
- Task 0.2: Create grace_control Package Structure (1 час)
- Task 0.3: Update pyproject.toml (1 час)
- Task 0.4: Setup Development Environment (2 часа)
- Task 0.5: Verify Existing Code Works (2 часа)

**Длительность:** 2 дня

**Критично:** НЕ удаляем flows/, platform/, tasks/!

---

### Phase 1: Core Infrastructure
**Файл:** `tasks/PHASE_1_CORE_REVISED.md`

**Задачи:**
- Task #10: Design & Implement DB Schema (2 дня)
  - 7 таблиц: features, waves, packets, packet_runs, workers, leases, events
  - 8 canonical states
  - SQLite-safe (no FOR UPDATE SKIP LOCKED)

- Task #11: Implement Packet State Machine (2 дня)
  - 8 states: DRAFT, READY, RUNNING, ACCEPTED, MERGED, REJECTED, FAILED, CANCELLED
  - Valid transitions
  - Terminal states

- Task #22: Implement PacketExecutionAdapter (2 дня)
  - Bridge к legacy run_e2e_packet
  - Materialize packet file
  - Parse result
  - Save evidence

**Длительность:** 1 неделя (6 дней)

---

### Phase 2: API & Worker
**Файл:** `tasks/PHASE_2_API_WORKER_REVISED.md`

**Задачи:**
- Task #18: Implement FastAPI Server (3 дня)
  - Canonical API endpoints (см. docs/API_CONTRACT.md)
  - Features, Packets, Workers, Architect routers
  - Health check
  - CORS localhost only
  - Bind 127.0.0.1 (NOT 0.0.0.0)

- Task #21: Implement Worker Loop (4 дня)
  - WorkerAPIClient
  - Worker loop
  - Heartbeat mechanism
  - Claim/release packets
  - PacketExecutionAdapter integration

**Длительность:** 1 неделя (7 дней)

---

### Phase 3: CLI & E2E Test
**Файл:** `tasks/PHASE_3_CLI_E2E_REVISED.md`

**Задачи:**
- Task #19: Implement CLI (1 день)
  - grace packet list/get
  - grace worker start
  - grace api start
  - grace health
  - Rich formatting

- Task #20: E2E Test (1 день)
  - Full vertical slice test
  - Verification script

**Длительность:** 2 дня

---

## 📊 Timeline

```
Week 1:
  Day 1-2: Phase 0 (Cleanup)
  Day 3-5: Phase 1 Task #10 (DB Schema)

Week 2:
  Day 1-2: Phase 1 Task #11 (State Machine)
  Day 3-4: Phase 1 Task #22 (PacketExecutionAdapter)
  Day 5: Phase 2 Task #18 start (FastAPI)

Week 3:
  Day 1-2: Phase 2 Task #18 finish (FastAPI)
  Day 3-5: Phase 2 Task #21 (Worker)

Week 4:
  Day 1: Phase 3 Task #19 (CLI)
  Day 2: Phase 3 Task #20 (E2E Test)
  Day 3: Buffer/Polish
```

**Total: 2.5 weeks (17 days)**

---

## 🔗 Key Documents

### Must Read Before Starting

1. **CANONICAL_DECISIONS.md** — единственный источник правды
   - Package strategy
   - Canonical states (8)
   - DB schema (7 таблиц)
   - Execution flow
   - MVP scope
   - Security model

2. **docs/API_CONTRACT.md** — canonical API endpoints
   - All endpoints
   - Request/response formats
   - Error codes
   - Rate limits (post-MVP)

3. **Phase task files** — детальные инструкции
   - PHASE_0_CLEANUP_REVISED.md
   - PHASE_1_CORE_REVISED.md
   - PHASE_2_API_WORKER_REVISED.md
   - PHASE_3_CLI_E2E_REVISED.md

---

## ✅ Исправленные противоречия

### Что было исправлено

1. ✅ **Phase 1 file** — был заглушкой, теперь полное ТЗ
2. ✅ **States** — зафиксировано 8 canonical states
3. ✅ **DB schema** — добавлены features/waves, 7 таблиц
4. ✅ **SQLite queue** — убран FOR UPDATE SKIP LOCKED
5. ✅ **Worker signature** — добавлен PacketExecutionAdapter
6. ✅ **Phase 0** — НЕ удаляем flows/platform/tasks
7. ✅ **pyproject.toml** — hatchling, не poetry
8. ✅ **API contract** — один источник правды
9. ✅ **Security** — bind 127.0.0.1, CORS localhost
10. ✅ **MVP scope** — убраны UI/Telegram/WebSocket
11. ✅ **PacketExecutionAdapter** — явная задача
12. ✅ **Timeline** — 2.5 недели вместо 4.5

---

## 🚫 Deprecated Files

Следующие файлы устарели, используйте REVISED версии:

- ❌ `tasks/PHASE_0_CLEANUP.md` → ✅ `PHASE_0_CLEANUP_REVISED.md`
- ❌ `tasks/PHASE_1_CORE_INFRASTRUCTURE.md` → ✅ `PHASE_1_CORE_REVISED.md`
- ❌ `tasks/PHASE_1_REMAINING_TASKS.md` → ✅ `PHASE_1_CORE_REVISED.md`
- ❌ `tasks/PHASE_2_API_WORKER.md` → ✅ `PHASE_2_API_WORKER_REVISED.md`
- ❌ `tasks/PHASE_2_REMAINING_TASKS.md` → ✅ `PHASE_2_API_WORKER_REVISED.md`
- ❌ `tasks/PHASE_3_UI_CLI_PART1.md` → ✅ `PHASE_3_CLI_E2E_REVISED.md`
- ❌ `tasks/PHASE_3_UI_CLI_PART2.md` → ✅ `PHASE_3_CLI_E2E_REVISED.md`

---

## 📝 Task Mapping

### Old → New

| Old Task | New Task | File |
|----------|----------|------|
| Task #10 | Task #10 | PHASE_1_CORE_REVISED.md |
| Task #11 | Task #11 | PHASE_1_CORE_REVISED.md |
| Task #22 | Task #22 | PHASE_1_CORE_REVISED.md |
| Task #18 | Task #18 | PHASE_2_API_WORKER_REVISED.md |
| Task #21 | Task #21 | PHASE_2_API_WORKER_REVISED.md |
| Task #19 | Task #19 | PHASE_3_CLI_E2E_REVISED.md |
| Task #20 | Task #20 | PHASE_3_CLI_E2E_REVISED.md |

### Removed from MVP-0

- ❌ Task #13: Complexity Router → Post-MVP
- ❌ Task #23: GRACE Canon Checker → Post-MVP
- ❌ Task #24: Acceptance Policies → Post-MVP (только simple)
- ❌ Task #25: Telegram Bot → Post-MVP
- ❌ Task #26: grace init → Post-MVP
- ❌ Task #27: Architect Integration → Simplified in Task #18
- ❌ Task #29: Artifact Viewer → Post-MVP
- ❌ Task #30: HTML Dashboard → Post-MVP
- ❌ Task #31: Logging → Simplified in Task #19
- ❌ Task #32: Test Infrastructure → Simplified in Task #20
- ❌ Task #33: Cancellation → Post-MVP
- ❌ Task #34: Health Checks → Simplified in Task #18

---

## 🎯 Success Criteria

### MVP-0 считается готовым когда:

1. ✅ API server запускается: `grace api start`
2. ✅ Worker запускается: `grace worker start`
3. ✅ CLI работает: `grace packet list`
4. ✅ E2E test проходит: `pytest tests/test_e2e_mvp0.py`
5. ✅ Vertical slice работает:
   - Architect создаёт plan
   - Worker claims packet
   - Worker executes packet (через PacketExecutionAdapter)
   - Packet state = ACCEPTED
   - Evidence сохраняется
   - Auto-merge (если ACCEPTED)

---

## 🚀 Getting Started

### Для агентов

1. Прочитать **CANONICAL_DECISIONS.md**
2. Прочитать **docs/API_CONTRACT.md**
3. Начать с **Phase 0** (PHASE_0_CLEANUP_REVISED.md)
4. Следовать задачам по порядку
5. НЕ добавлять features из "removed from MVP-0"
6. НЕ удалять legacy code (flows/, platform/, tasks/)

### Для людей

```bash
# 1. Прочитать документы
cat CANONICAL_DECISIONS.md
cat docs/API_CONTRACT.md

# 2. Начать Phase 0
cd /tmp/grace-orchestrator-export
cat tasks/PHASE_0_CLEANUP_REVISED.md

# 3. Следовать инструкциям
```

---

## 📞 Questions?

Если что-то неясно:
1. Проверьте CANONICAL_DECISIONS.md
2. Проверьте docs/API_CONTRACT.md
3. Проверьте соответствующий PHASE_*_REVISED.md файл

Если противоречие найдено:
1. CANONICAL_DECISIONS.md всегда прав
2. Обновите task file
3. Сообщите о противоречии

---

**Готово к реализации! 🚀**
