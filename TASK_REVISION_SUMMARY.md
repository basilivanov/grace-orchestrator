# Исправление ТЗ — Сводка

**Дата:** 2026-05-31
**Статус:** ✅ Завершено

---

## 🎯 Что было сделано

Исправлены **12 критичных противоречий** в ТЗ, выявленных в code review.

---

## 📄 Созданные документы

### 1. CANONICAL_DECISIONS.md (403 строки)
**Единственный источник правды** для всех архитектурных решений.

**Содержит:**
- ✅ Package strategy (НЕ удаляем legacy code)
- ✅ 8 canonical states (DRAFT → READY → RUNNING → ACCEPTED → MERGED)
- ✅ 7 таблиц DB (features, waves, packets, packet_runs, workers, leases, events)
- ✅ API contract reference
- ✅ PacketExecutionAdapter (bridge к legacy)
- ✅ Security model (127.0.0.1, CORS localhost)
- ✅ MVP-0 scope (БЕЗ UI/Telegram/WebSocket)
- ✅ Timeline (2.5 недели)

### 2. docs/API_CONTRACT.md (468 строк)
**Canonical API endpoints** — один источник правды для API.

**Содержит:**
- ✅ Все endpoints с примерами
- ✅ Request/response formats
- ✅ Error codes
- ✅ SQLite-safe lease mechanism
- ✅ Security (localhost only)

### 3. tasks/PHASE_0_CLEANUP_REVISED.md
**Phase 0: Cleanup (2 дня)**

**Исправлено:**
- ❌ Было: удалить flows/platform/tasks
- ✅ Стало: добавить prefect_compat.py, НЕ удалять legacy code

**Задачи:**
- Task 0.1: Prefect Compatibility Layer (2 часа)
- Task 0.2: Package Structure (1 час)
- Task 0.3: Update pyproject.toml (1 час)
- Task 0.4: Dev Environment (2 часа)
- Task 0.5: Verify Legacy Code (2 часа)

### 4. tasks/PHASE_1_CORE_REVISED.md
**Phase 1: Core Infrastructure (1 неделя)**

**Исправлено:**
- ❌ Было: заглушка "см. полное содержимое в файле"
- ✅ Стало: полное детальное ТЗ с кодом

**Задачи:**
- Task #10: DB Schema (2 дня) — 7 таблиц, 8 states, SQLite-safe
- Task #11: State Machine (2 дня) — canonical transitions
- Task #22: PacketExecutionAdapter (2 дня) — bridge к legacy run_e2e_packet

### 5. tasks/PHASE_2_API_WORKER_REVISED.md
**Phase 2: API & Worker (1 неделя)**

**Исправлено:**
- ❌ Было: FOR UPDATE SKIP LOCKED (Postgres-only)
- ✅ Стало: SQLite-safe lease mechanism
- ❌ Было: неправильная сигнатура run_e2e_packet
- ✅ Стало: PacketExecutionAdapter

**Задачи:**
- Task #18: FastAPI Server (3 дня) — canonical endpoints, 127.0.0.1
- Task #21: Worker Loop (4 дня) — lease, heartbeat, adapter integration

### 6. tasks/PHASE_3_CLI_E2E_REVISED.md
**Phase 3: CLI & E2E Test (2 дня)**

**Исправлено:**
- ❌ Было: UI, Telegram, WebSocket, image viewer
- ✅ Стало: только CLI и E2E test

**Задачи:**
- Task #19: CLI (1 день) — grace packet list/get, worker start, api start
- Task #20: E2E Test (1 день) — vertical slice test

### 7. tasks/README_REVISED.md
**Главный индекс** с mapping старых задач на новые.

---

## 🔧 Исправленные противоречия

| # | Проблема | Решение |
|---|----------|---------|
| 1 | Phase 1 file — заглушка | Написано полное ТЗ с кодом |
| 2 | States разъехались (8 vs 9) | Зафиксировано 8 canonical states |
| 3 | DB schema неполная | Добавлены features/waves, 7 таблиц |
| 4 | SQLite queue — Postgres syntax | SQLite-safe lease mechanism |
| 5 | Worker — неправильная сигнатура | PacketExecutionAdapter |
| 6 | Phase 0 удаляет flows | НЕ удаляем legacy code |
| 7 | pyproject.toml — poetry | Исправлено на hatchling |
| 8 | API endpoints разъехались | Один API_CONTRACT.md |
| 9 | Security — 0.0.0.0 + CORS * | 127.0.0.1 + CORS localhost |
| 10 | MVP раздут | Убраны UI/Telegram/WebSocket |
| 11 | PacketExecutionAdapter отсутствует | Добавлена явная задача |
| 12 | Timeline 4.5 недели | Упрощено до 2.5 недель |

---

## 📊 MVP-0 Scope

### ✅ Включено

**Phase 0:** Cleanup (2 дня)
- Prefect compat layer
- Package structure
- Dev environment

**Phase 1:** Core (1 неделя)
- DB schema (7 таблиц)
- State machine (8 states)
- PacketExecutionAdapter

**Phase 2:** API & Worker (1 неделя)
- FastAPI server
- Worker loop
- Lease mechanism

**Phase 3:** CLI & E2E (2 дня)
- CLI commands
- E2E test

**Итого: 2.5 недели (17 дней)**

### ❌ Убрано в Post-MVP

- UI/Dashboard
- Telegram notifications
- WebSocket
- Image viewer
- Cancellation
- GRACE Canon checker
- Complexity router
- Multiple workers (parallel)
- Acceptance policies (только simple)

---

## 🚀 Готовность

### Для агентов

1. ✅ Прочитать **CANONICAL_DECISIONS.md**
2. ✅ Прочитать **docs/API_CONTRACT.md**
3. ✅ Начать с **tasks/PHASE_0_CLEANUP_REVISED.md**
4. ✅ Следовать задачам по порядку
5. ✅ НЕ добавлять features из "removed from MVP-0"

### Для проверки

```bash
# Проверить что всё на месте
ls -la CANONICAL_DECISIONS.md
ls -la docs/API_CONTRACT.md
ls -la tasks/PHASE_*_REVISED.md
ls -la tasks/README_REVISED.md

# Прочитать главные документы
cat CANONICAL_DECISIONS.md
cat docs/API_CONTRACT.md
cat tasks/README_REVISED.md
```

---

## 📈 Статистика

**Создано файлов:** 7
**Строк кода/документации:** ~4000
**Исправлено противоречий:** 12
**Упрощено timeline:** с 4.5 до 2.5 недель
**Убрано из MVP:** 8 features (в post-MVP)

---

## ✅ Результат

**ТЗ готово к передаче агентам!**

Все противоречия разрешены, один источник правды создан, MVP упрощён до vertical slice.

**Следующий шаг:** Начать реализацию Phase 0.

---

**Запушено в GitHub:** ✅
**Commit:** c303c3e
**Branch:** main
