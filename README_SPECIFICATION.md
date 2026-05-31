# GRACE Control Plane — Complete Specification Summary

**СТАТУС: HISTORICAL / DEPRECATED.** Этот документ описывает первоначальную архитектуру (v1) с UI, WebSocket, Telegram и 4.5-недельным планом.

**Актуальный канон → [CANONICAL_DECISIONS.md](CANONICAL_DECISIONS.md).**
**Актуальные ТЗ → [tasks/README.md](tasks/README.md).**

Ниже — оригинальный текст для исторической справки. НЕ использовать для реализации MVP-0.

## 📚 Документация (7 основных документов)

### 1. **GRACE_CONTROL_PLANE_SPEC.md** (42 KB)
Полная детальная спецификация системы.

### 2. **GRACE_CONTROL_PLANE_SUMMARY.md** (11 KB)
Краткая выжимка основных концепций.

### 3. **GRACE_API_FIRST_ARCHITECTURE.md** (22 KB)
API-first архитектура с FastAPI.

### 4. **GRACE_AI_FIRST_DATA_MODEL.md** (19 KB)
AI-first data model (JSON primary, MD для debug).

### 5. **FINAL_DECISIONS.md** (12 KB)
Все 22 архитектурных решения.

### 6. **LOGGING_AND_TESTING_STRATEGY.md** (20 KB)
Стратегия логирования и тестирования.

### 7. **IMPLEMENTATION_ROADMAP.md** (12 KB)
План реализации на 4-5 недель.

---

## 🎯 Ключевые решения

### Архитектура
✅ **API-first:** FastAPI server + thin CLI wrapper
✅ **AI-first data:** JSON primary, MD только для debug
✅ **Packet vs Run:** Packet = спецификация, Run = попытка выполнения
✅ **Wave grouping:** Логическая группировка packets
✅ **Hierarchical IDs:** FEAT-X-W01-P01-ACTION-R01

### Execution
✅ **Retry:** Новый run_id для каждой попытки (max 3)
✅ **Escalation:** Список executors с fallback (cheap → medium → strong)
✅ **Conflicts:** Запретить параллельное выполнение конфликтующих packets
✅ **Timeout:** Heartbeat-based (5 минут без heartbeat = завис)
✅ **Merge:** Автоматически после ACCEPTED

### Acceptance
✅ **Ступенчатая приёмка:** T0 → T1 → T2 → Canon → Reviewer (early exit)
✅ **Reviewer trigger:** По acceptance profile (FAST/NORMAL/STRICT)
✅ **Rework:** Автоматический retry с feedback
✅ **GRACE Canon:** File/function limits, contracts, semantic blocks

### Infrastructure
✅ **Executors:** API (Anthropic, Google, OpenAI) + Local (Ollama, Antigravity)
✅ **Evidence:** Всё на диске (JSON), DB хранит пути
✅ **Logging:** Structured JSONL с trace_id propagation
✅ **Testing:** 4 tiers (T0: lint/canon, T1: touched, T2: full, T3: integration, T4: visual)

### UI & Notifications
✅ **UI:** Simple HTML dashboard с artifact viewer
✅ **Screenshots:** Thumbnails + lightbox + visual regression
✅ **Notifications:** WebSocket + Telegram bot
✅ **CLI:** Thin wrapper над API с JSON output для агентов

### Other
✅ **Cost tracking:** Не считаем (модели могут быть локальные)
✅ **Rollback:** Manual git revert (не в MVP)
✅ **Multi-project:** Один проект в MVP
✅ **Auth:** Нет auth в MVP

---

## 🏗️ Архитектура

```
┌─────────────────────────────────────────────────────────┐
│                  FastAPI Server                          │
│  - REST API (все операции)                              │
│  - WebSocket (real-time updates)                        │
│  - Artifact endpoints (с thumbnails)                    │
└─────────────────────────────────────────────────────────┘
                         ↓
┌─────────────────────────────────────────────────────────┐
│               Core Control Plane                         │
│  - State machine (ступенчатая приёмка)                 │
│  - Executor abstraction (API + local)                   │
│  - Complexity router                                     │
│  - Acceptance policy                                     │
│  - GRACE Canon checker                                   │
└─────────────────────────────────────────────────────────┘
                         ↓
┌─────────────────────────────────────────────────────────┐
│              SQLite/Postgres DB                          │
│  - Иерархические ID                                     │
│  - JSON columns для structured data                     │
└─────────────────────────────────────────────────────────┘

Клиенты:
┌──────────────┐  ┌──────────────┐  ┌──────────────┐
│  Web UI      │  │  CLI (thin)  │  │  Agents      │
│  (HTML+JS)   │  │  (wrapper)   │  │  (API calls) │
└──────────────┘  └──────────────┘  └──────────────┘
```

---

## 📊 Иерархия сущностей

```
Feature (FEAT-USER-AUTH)
  ↓
Wave (W01-FOUNDATION)
  ↓
Packet (P01-CREATE-JWT-UTILS) ← спецификация задачи
  ↓
Run (R01, R02, R03) ← попытки выполнения
```

**Полный ID:**
```
FEAT-USER-AUTH-W01-P01-CREATE-JWT-UTILS-R01
```

---

## 🔄 Ступенчатая приёмка (экономия токенов)

```
T0 (Lint + GRACE Canon) → fail? → REJECT
  ↓ pass
T1 (Touched scope tests) → fail? → REJECT
  ↓ pass
T2 (Full unit tests, if NORMAL/STRICT) → fail? → REJECT
  ↓ pass
Complexity check → может повысить profile
  ↓
Reviewer (if STRICT) → reject? → REJECT with feedback
  ↓ accept
ACCEPTED → Auto-merge → MERGED
```

**Экономия:** Не запускаем дорогие проверки если дешёвые упали.

---

## 📦 Что переиспользуем (70%)

✅ Packet execution engine (`run_e2e_packet`, `run_managed_packet`)
✅ Worktree management
✅ Agent launcher (расширим под разные провайдеры)
✅ Git operations (`git_mutation_gate`)
✅ Domain models
✅ Policy engine (как базу)
✅ Evidence collection (адаптируем под JSON)

## 🆕 Что пишем заново (30%)

🆕 FastAPI server
🆕 DB schema + SQLAlchemy models
🆕 Worker loop (как API client)
🆕 State machine с ступенчатой приёмкой
🆕 CLI (thin wrapper)
🆕 Telegram bot
🆕 Executor abstraction
🆕 GRACE Canon checker
🆕 Acceptance policy abstraction
🆕 HTML dashboard
🆕 Artifact viewer с изображениями

## ❌ Что удаляем

❌ Всё что связано с Prefect
❌ Старые briefs
❌ Сложные verification profiles

---

## 📅 Roadmap (4-5 недель)

### Phase 0: Подготовка (2-3 дня)
- Удалить Prefect dependencies
- Вычистить legacy код
- Создать новую структуру

### Phase 1: Core Infrastructure (1.5 недели)
- DB schema с иерархическими ID
- State machine с ступенчатой приёмкой
- Executor abstraction (API + local)
- Complexity router
- Acceptance policy
- GRACE Canon checker
- Test infrastructure (T0/T1/T2/T3/T4)
- Structured logging

### Phase 2: API & Worker (1 неделя)
- FastAPI server с artifact endpoints
- Worker loop (API client)
- Architect integration

### Phase 3: UI & CLI (1 неделя)
- JSON artifacts storage
- Artifact viewer (с изображениями)
- HTML dashboard
- CLI wrapper
- Telegram bot
- grace init command

### Phase 4: Testing & Polish (1 неделя)
- E2E testing
- Documentation
- GRACE Canon compliance
- Final polish

---

## 📋 Задачи (22 tasks)

### Core (8 tasks)
- #10: DB schema
- #11: State machine
- #13: Complexity router
- #22: Executor abstraction
- #23: GRACE Canon checker
- #24: Acceptance policy
- #31: Logging infrastructure
- #32: Test infrastructure

### API & Worker (4 tasks)
- #18: FastAPI server
- #12: Worker loop
- #21: Worker API client
- #27: Architect integration

### UI & CLI (6 tasks)
- #19: JSON artifacts
- #29: Artifact viewer
- #30: HTML dashboard
- #20: CLI wrapper
- #25: Telegram bot
- #26: grace init

### Testing (1 task)
- #17: E2E test

### Documentation (1 task)
- #28: Final spec ✅ (completed)

---

## 🎯 MVP Checklist

### Core Functionality
- [ ] Architect создаёт packets из feature spec
- [ ] Packets имеют иерархические ID
- [ ] Worker выполняет packets
- [ ] Ступенчатая приёмка работает
- [ ] GRACE Canon проверки работают
- [ ] Evidence собирается в JSON
- [ ] Acceptance decision работает
- [ ] Auto-merge работает
- [ ] Retry с escalation работает

### Infrastructure
- [ ] DB schema с миграциями
- [ ] State machine с transitions
- [ ] Executor abstraction
- [ ] Structured logging с trace_id
- [ ] Test infrastructure

### API & UI
- [ ] FastAPI server работает
- [ ] WebSocket real-time updates
- [ ] HTML dashboard показывает иерархию
- [ ] Artifact viewer с изображениями
- [ ] Screenshot gallery с lightbox

### CLI & Notifications
- [ ] CLI wrapper работает
- [ ] Telegram bot отправляет уведомления
- [ ] grace init создаёт проект

### Testing
- [ ] E2E test проходит
- [ ] Все компоненты GRACE Canon compliant
- [ ] Documentation complete

---

## 🚀 Quick Start (после MVP)

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

## 📈 Success Metrics

**Цели для MVP:**
- Fast path rate > 60% (packets принятые без reviewer)
- Acceptance rate > 70% (packets принятые с первой попытки)
- Average packet time < 5 минут
- T0 pass rate > 95%

---

## 📚 Все документы

1. **GRACE_CONTROL_PLANE_SPEC.md** — полная спецификация
2. **GRACE_CONTROL_PLANE_SUMMARY.md** — краткая выжимка
3. **GRACE_API_FIRST_ARCHITECTURE.md** — API-first архитектура
4. **GRACE_AI_FIRST_DATA_MODEL.md** — AI-first data model
5. **FINAL_DECISIONS.md** — все 22 решения
6. **LOGGING_AND_TESTING_STRATEGY.md** — логирование и тестирование
7. **IMPLEMENTATION_ROADMAP.md** — план реализации
8. **THIS_DOCUMENT.md** — этот summary

---

## ✅ Статус

**Спецификация:** ✅ Полностью готова
**Решения:** ✅ Все 22 приняты
**Roadmap:** ✅ Детальный план на 4-5 недель
**Задачи:** ✅ 22 tasks созданы с зависимостями

**Готовы к реализации!** 🚀

---

## 🎯 Следующий шаг

**Начать реализацию с Phase 0:**
1. Удалить Prefect dependencies
2. Вычистить legacy код
3. Создать новую структуру проекта

**Или:**
- Уточнить детали спецификации
- Обсудить приоритеты
- Распределить задачи между разработчиками

**Что выбираете?**
