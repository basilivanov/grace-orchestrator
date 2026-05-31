# GRACE Control Plane — Final Decisions

**Статус:** Исторический документ. Канонические решения см. в CANONICAL_DECISIONS.md.

Этот документ сохранён как справочник принятых архитектурных решений. Единственный источник правды для реализации — **CANONICAL_DECISIONS.md**.

---

## ✅ Все архитектурные решения приняты

### 1. Retry Strategy
**Решение:** Каждая попытка = новый run_id
- Packet = спецификация задачи (что делать)
- Run = попытка выполнения (как делали)
- Packet может иметь несколько runs (R01, R02, R03)
- Полная история всех попыток сохраняется

### 2. Escalation Strategy
**Решение:** Список executors с fallback (cheap → medium → strong)
```yaml
roles:
  coder:
    executors:
      - gemini-flash-api      # Attempt 1: cheap
      - gemini-pro-api        # Attempt 2: medium
      - claude-opus-api       # Attempt 3: strong
```

### 3. Conflict Resolution
**Решение:** Запретить параллельное выполнение конфликтующих packets
- Если два packets трогают один файл → второй ждёт
- Простая реализация для MVP

### 4. Reviewer Trigger
**Решение:** По acceptance profile
- FAST → reviewer не нужен
- NORMAL → reviewer опционально
- STRICT → reviewer обязательно

### 5. Rework Loop
**Решение:** Автоматический retry с feedback от reviewer
- Максимум 3 попытки, потом escalate к человеку

### 6. Evidence Storage
**Решение:** Всё на диске, DB хранит только пути
- JSON artifacts, structured JSONL логи
- DB: только metadata + пути к файлам

### 7. Worker Assignment
**Решение:** First-come-first-served
- SQLite-safe lease mechanism (без FOR UPDATE SKIP LOCKED)

### 8. Timeout Handling
**Решение:** Heartbeat-based (30s интервал, 5 мин таймаут)

### 9. Merge Strategy
**Решение:** Автоматически после ACCEPTED → переиспользуем git_mutation_gate.py

### 10. Feature Completion
**Решение:** Все packets MERGED = feature COMPLETED

### 11. Cost Tracking
**Решение:** Не считаем в MVP (post-MVP feature)

### 12. Notifications
**Решение:** WebSocket + Telegram → **Post-MVP** (не в MVP-0)

### 13. Rollback
**Решение:** Manual git revert → **Post-MVP**

### 14. Multi-project Support
**Решение:** Один проект в MVP

### 15. Authentication
**Решение:** Нет auth в MVP (localhost only, bind 127.0.0.1)

---

## 🆕 Дополнительные решения

### 16. Executor Abstraction
**Решение:** Поддержка API + локальных моделей (добавлено в post-MVP)

### 17. GRACE Canon Integration
**Решение:** Strict GRACE canon → **Post-MVP** (MVP использует basic проверки)

### 18. Ступенчатая приёмка (Staged Acceptance)
**Решение:** Pipeline с early exit (T0 → T1 → T2 → Canon → Reviewer)
В MVP-0: simplified до basic accept/reject.

### 19. Универсальность (Project-agnostic)
**Решение:** GRACE Control Plane адаптируется под любой проект через project.yaml

### 20. XML Artifacts
**Решение:** Architect читает XML документы (requirements.xml, technology.xml, etc.)

### 21. Code Contracts
**Решение:** AI_HEADER + MODULE_CONTRACT → **Post-MVP** проверка

### 22. Hierarchical IDs
**Решение:** Человекочитаемые иерархические ID (FEAT-X-W01-P01-ACTION-R01)

---

## 🏗️ Архитектура (MVP-0)

```
FastAPI Server (grace_control/api/)
  ↓
Core Control Plane (grace_control/core/) — state machine, DB
  ↓
PacketExecutionAdapter (grace_control/adapters/) — мост к legacy
  ↓
Legacy Execution Engine (prefect_grace/platform/) — переиспользуем
  ↓
SQLite DB (7 таблиц, 8 состояний)
```

### Что переиспользуем из legacy (~70%)
- Packet execution engine (run_e2e_packet, run_managed_packet)
- Worktree management
- Agent launcher (codex_launcher)
- Git operations (git_mutation_gate)
- Domain models, evidence collection

### Что пишем заново (~30%)
- FastAPI server
- DB schema + SQLAlchemy models
- Worker loop (как API client с lease mechanism)
- State machine (8 canonical states)
- CLI (grace_control.cli)
- PacketExecutionAdapter (bridge)

### Что НЕ удаляем из legacy
- flows/ — все Prefect-потоки
- platform/ — execution engine
- tasks/ — agent launchers, utilities
- Добавляем prefect_compat.py для no-op режима

---

## 📅 План реализации (канонический)

См. **CANONICAL_DECISIONS.md** и REVISED task files.

**Phase 0:** Cleanup (2 дня)
**Phase 1:** Core Infrastructure — DB, state machine, adapter (1 неделя)
**Phase 2:** API + Worker (1 неделя)
**Phase 3:** CLI + E2E Test (2 дня)

**Итого: 2.5 недели до MVP-0**

### Post-MVP waves
- Wave 1: Retry + Cancellation (3 дня)
- Wave 2: UI + Telegram (1 неделя)
- Wave 3: GRACE Canon + Complexity Router (1 неделя)
- Wave 4: Parallel execution + Multiple workers (1 неделя)

---

## 🎯 Критерии готовности MVP-0

MVP-0 готов когда:

✅ API server запускается: `grace api start`
✅ Worker запускается: `grace worker start`
✅ CLI работает: `grace packet list`
✅ E2E test проходит: `pytest tests/test_e2e_mvp0.py`
✅ Vertical slice работает:
   - Architect создаёт packets из feature spec
   - Worker claims + executes packet через PacketExecutionAdapter
   - Packet state = ACCEPTED
   - Evidence сохраняется

### НЕ в MVP-0
- ❌ UI/Dashboard, Telegram, WebSocket
- ❌ Cancellation, image viewer
- ❌ GRACE Canon checker, Complexity router
- ❌ Multiple workers, parallel execution

---

## 📚 Документы

1. **CANONICAL_DECISIONS.md** — единственный источник правды (приоритет)
2. **docs/API_CONTRACT.md** — канонические API endpoints
3. **tasks/README_REVISED.md** — индекс REVISED task-файлов
4. Реализация: PHASE_0_CLEANUP_REVISED.md, PHASE_1_CORE_REVISED.md, PHASE_2_API_WORKER_REVISED.md, PHASE_3_CLI_E2E_REVISED.md

---

**Исторический документ. Актуальные решения — CANONICAL_DECISIONS.md.**
