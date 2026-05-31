# GRACE Control Plane — Task Specifications (REVISED)

**Версия:** 3.0 (синхронизировано с CANONICAL_DECISIONS.md)
**Дата:** 2026-05-31

**Единственный источник правды:** [CANONICAL_DECISIONS.md](../CANONICAL_DECISIONS.md)

Все старые (не-REVISED) task-файлы удалены. Используйте только REVISED версии.

---

##  MVP-0 Scope

**Цель:** Минимальный рабочий Control Plane за 2.5 недели.

### Что ВКЛЮЧЕНО

- **Phase 0:** Cleanup — Prefect compat layer, package structure, dev env (2 дня)
- **Phase 1:** Core Infrastructure — DB (7 таблиц, 8 states), state machine, PacketExecutionAdapter (1 неделя)
- **Phase 2:** API & Worker — FastAPI server, worker loop с lease mechanism (1 неделя)
- **Phase 3:** CLI & E2E Test — CLI команды, vertical slice E2E test (2 дня)

### Что НЕ ВКЛЮЧЕНО (Post-MVP)

- UI/Dashboard
- Telegram notifications
- WebSocket
- Image viewer
- Packet cancellation
- GRACE Canon checker
- Complexity router
- Multiple workers (parallel)
- Acceptance policies (только simple)

---

##  Task Files

### Phase 0: Cleanup & Preparation
**Файл:** [PHASE_0_CLEANUP_REVISED.md](PHASE_0_CLEANUP_REVISED.md) — 2 дня

| Task | Описание | Приоритет |
|------|----------|-----------|
| 0.1 | Prefect Compatibility Layer (prefect_compat.py) | Критично |
| 0.2 | grace_control Package Structure | Критично |
| 0.3 | Update pyproject.toml | Критично |
| 0.4 | Setup Development Environment | Средний |
| 0.5 | Verify Existing Code Works | Критично |

### Phase 1: Core Infrastructure
**Файл:** [PHASE_1_CORE_REVISED.md](PHASE_1_CORE_REVISED.md) — 1 неделя

| Task | Описание | Приоритет |
|------|----------|-----------|
| #10 | Design & Implement DB Schema (7 таблиц, 8 states) | Критично |
| #11 | Implement Packet State Machine | Критично |
| #22 | Implement PacketExecutionAdapter (bridge к legacy) | Критично |

### Phase 2: API & Worker
**Файл:** [PHASE_2_API_WORKER_REVISED.md](PHASE_2_API_WORKER_REVISED.md) — 1 неделя

| Task | Описание | Приоритет |
|------|----------|-----------|
| #18 | Implement FastAPI Server (canonical endpoints) | Критично |
| #21 | Implement Worker Loop (lease mechanism + adapter) | Критично |

### Phase 3: CLI & E2E Test
**Файл:** [PHASE_3_CLI_E2E_REVISED.md](PHASE_3_CLI_E2E_REVISED.md) — 2 дня

| Task | Описание | Приоритет |
|------|----------|-----------|
| #19 | Implement CLI (grace команды) | Критично |
| #20 | E2E Test (vertical slice) | Критично |

### Phase 4: Polish & Documentation (Post-MVP buffer)
**Файл:** [PHASE_4_TESTING_POLISH_REVISED.md](PHASE_4_TESTING_POLISH_REVISED.md) — 3 дня

| Task | Описание | Приоритет |
|------|----------|-----------|
| #17 | Advanced E2E Testing (retry, edge cases) | Высокий |
| — | Documentation Updates | Средний |
| — | Code Review & Polish | Средний |

---

##  Сводная статистика

| Фаза | Длительность | Задач |
|------|-------------|-------|
| Phase 0 | 2 дня | 5 |
| Phase 1 | 1 неделя | 3 |
| Phase 2 | 1 неделя | 2 |
| Phase 3 | 2 дня | 2 |
| Phase 4 | 3 дня | 1 + docs |
| **Итого MVP-0** | **2.5 недели** | **12 задач** |

---

##  Timeline

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

Week 4 (buffer):
  Day 1: Phase 3 Task #19 (CLI)
  Day 2: Phase 3 Task #20 (E2E Test)
  Day 3: Phase 4 (Polish)
```

---

## 🎯 Критерии готовности MVP-0

- ✅ API server запускается: `grace api start`
- ✅ Worker запускается: `grace worker start`
- ✅ CLI работает: `grace packet list`
- ✅ E2E test проходит: `pytest tests/test_e2e_mvp0.py`
- ✅ Vertical slice: architect → worker → execute → accept → evidence

---

## 🔗 Ключевые документы

1. **CANONICAL_DECISIONS.md** — единственный источник правды
2. **docs/API_CONTRACT.md** — canonical API endpoints
3. **FINAL_DECISIONS.md** — исторический справочник решений

---

## 🚀 Как использовать

1. Прочитать CANONICAL_DECISIONS.md
2. Прочитать docs/API_CONTRACT.md
3. Начать с Phase 0 (PHASE_0_CLEANUP_REVISED.md)
4. Следовать задачам по порядку
5. НЕ добавлять features из «НЕ в MVP-0»
6. НЕ удалять legacy code (flows/, platform/, tasks/)

---

**Готово к реализации MVP-0!**
