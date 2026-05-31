# GRACE Control Plane — Task Reference (REVISED)

**Версия:** 3.0 (синхронизировано)
**Дата:** 2026-05-31

Этот файл — краткий справочник. Основной индекс задач — [tasks/README.md](README.md).

Все старые task-файлы удалены. Актуальны только REVISED версии.

---

##  Актуальные Task-файлы

| Файл | Фаза | Задач |
|------|------|-------|
| [PHASE_0_CLEANUP_REVISED.md](PHASE_0_CLEANUP_REVISED.md) | Cleanup | 5 |
| [PHASE_1_CORE_REVISED.md](PHASE_1_CORE_REVISED.md) | Core Infrastructure | 3 |
| [PHASE_2_API_WORKER_REVISED.md](PHASE_2_API_WORKER_REVISED.md) | API & Worker | 2 |
| [PHASE_3_CLI_E2E_REVISED.md](PHASE_3_CLI_E2E_REVISED.md) | CLI & E2E Test | 2 |
| [PHASE_4_TESTING_POLISH_REVISED.md](PHASE_4_TESTING_POLISH_REVISED.md) | Polish | 1+docs |

---

##  Удалённые файлы (больше не актуальны)

Следующие файлы удалены — их содержание заменено REVISED версиями:

- `PHASE_0_CLEANUP.md` → `PHASE_0_CLEANUP_REVISED.md`
- `PHASE_1_CORE_INFRASTRUCTURE.md` → `PHASE_1_CORE_REVISED.md`
- `PHASE_1_REMAINING_TASKS.md` → `PHASE_1_CORE_REVISED.md`
- `PHASE_1_TASK_13_COMPLEXITY_ROUTER.md` → Post-MVP
- `PHASE_1_TASK_32_TEST_INFRASTRUCTURE.md` → упрощено в Phase 3
- `PHASE_2_API_WORKER.md` → `PHASE_2_API_WORKER_REVISED.md`
- `PHASE_2_REMAINING_TASKS.md` → `PHASE_2_API_WORKER_REVISED.md`
- `PHASE_3_UI_CLI_PART1.md` → `PHASE_3_CLI_E2E_REVISED.md`
- `PHASE_3_UI_CLI_PART2.md` → `PHASE_3_CLI_E2E_REVISED.md`
- `PHASE_4_TESTING_POLISH.md` → `PHASE_4_TESTING_POLISH_REVISED.md`

---

## 🔗 Ключевые документы

1. **CANONICAL_DECISIONS.md** — единственный источник правды (приоритет)
2. **docs/API_CONTRACT.md** — канонические API endpoints
3. **FINAL_DECISIONS.md** — исторический справочник решений
4. **tasks/README.md** — основной индекс задач

---

##  Правила для реализации

1. CANONICAL_DECISIONS.md всегда прав
2. НЕ добавляем features из «НЕ в MVP-0»
3. НЕ удаляем legacy code (flows/, platform/, tasks/)
4. Используем REVISED task files
5. Старые файлы удалены — не ссылаться на них

---

**Готово к реализации!**
