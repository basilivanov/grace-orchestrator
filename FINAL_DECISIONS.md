# GRACE Control Plane — Final Decisions

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
- Можно расширить до merge conflict handling позже

### 4. Reviewer Trigger
**Решение:** По acceptance profile
- FAST → reviewer не нужен
- NORMAL → reviewer опционально (по policy)
- STRICT → reviewer обязательно

### 5. Rework Loop
**Решение:** Автоматический retry с feedback от reviewer
- Reviewer отклонил → создаётся новый run с feedback
- Coder agent видит feedback и исправляет
- Максимум 3 попытки, потом escalate к человеку

### 6. Evidence Storage
**Решение:** Всё на диске, DB хранит только пути
- JSON artifacts: result.json, agent/output.json, tests/*.json
- Logs: structured JSONL
- DB: только metadata + пути к файлам
- MD файлы: только если debug mode enabled

### 7. Worker Assignment
**Решение:** First-come-first-served
- Worker просит packet → получает первый READY из очереди
- Простая очередь без умного распределения
- Можно расширить до capability-based позже

### 8. Timeout Handling
**Решение:** Heartbeat-based
- Worker отправляет heartbeat каждые 30 секунд
- Нет heartbeat 5 минут → считаем зависшим
- Packet → READY для retry на другом worker

### 9. Merge Strategy
**Решение:** Автоматически после ACCEPTED
- Packet → ACCEPTED → auto-merge → MERGED
- Используем существующий git_mutation_gate.py
- Если merge conflict → packet → NEEDS_REWORK

### 10. Feature Completion
**Решение:** Все packets MERGED = feature COMPLETED
- Feature имеет N packets
- Все N → MERGED → Feature → COMPLETED
- Можно добавить optional packets позже

### 11. Cost Tracking
**Решение:** Не считаем в MVP
- Модели могут быть локальные (Ollama, Antigravity)
- Не все провайдеры возвращают token count
- Можно добавить опционально для аналитики позже

### 12. Notifications
**Решение:** WebSocket + Telegram bot
- WebSocket: real-time updates в UI
- Telegram: уведомления о важных событиях
  - Feature started/completed/failed
  - Packet accepted/rejected/failed
  - Worker died, system unhealthy

### 13. Rollback
**Решение:** Manual git revert (не в MVP)
- Вы делаете git revert вручную
- Система не участвует
- Можно добавить grace packet rollback позже

### 14. Multi-project Support
**Решение:** Один проект в MVP
- Один project.yaml
- Одна БД
- Простая архитектура
- Multi-project можно добавить позже

### 15. Authentication
**Решение:** Нет auth в MVP
- API открыт на localhost
- Только вы используете
- Можно добавить token auth позже

---

## 🆕 Дополнительные решения

### 16. Executor Abstraction
**Решение:** Поддержка API + локальных моделей
```yaml
executors:
  items:
    # API-based
    - id: claude-opus-api
      type: anthropic
      model: claude-opus-4-8
      api_key_env: ANTHROPIC_API_KEY
    
    # Command-based (локальные)
    - id: antigravity-claude
      type: command
      command: "antigravity --model claude-opus-4-8 --non-interactive"
```

### 17. GRACE Canon Integration
**Решение:** Strict GRACE canon в acceptance pipeline
- File size limit: 1000 lines
- Function size limit: 4000 tokens
- Contracts required: AI_HEADER, MODULE_CONTRACT, FUNCTION_CONTRACT
- Semantic blocks: START/END pairs
- grace-lint integration

### 18. Ступенчатая приёмка (Staged Acceptance)
**Решение:** Pipeline с early exit для экономии токенов
```
T0 (lint + GRACE canon) → fail? → REJECT
  ↓ pass
T1 (touched tests) → fail? → REJECT
  ↓ pass
T2 (full tests, if NORMAL/STRICT) → fail? → REJECT
  ↓ pass
Complexity check → может повысить profile
  ↓
Reviewer (if STRICT) → reject? → REJECT with feedback
  ↓ accept
ACCEPTED
```

### 19. Универсальность (Project-agnostic)
**Решение:** GRACE Control Plane адаптируется под любой проект
- project.yaml с project-specific настройками
- Понимает где логи, тесты, структура проекта
- grace init создаёт конфигурацию для нового проекта

### 20. XML Artifacts
**Решение:** Architect читает XML документы
- requirements.xml — системные требования
- technology.xml — технологический стек
- development-plan.xml — план разработки
- knowledge-graph.xml — семантическая карта кода
- verification-matrix.xml — матрица верификации

### 21. Code Contracts
**Решение:** Каждый файл должен иметь контракты
- AI_HEADER — роль модуля
- MODULE_CONTRACT — контракт модуля
- MODULE_MAP — карта модуля
- FUNCTION_CONTRACT — контракт функции
- START/END semantic blocks

### 22. Hierarchical IDs
**Решение:** Человекочитаемые иерархические ID
```
Feature:  FEAT-USER-AUTH
Wave:     FEAT-USER-AUTH-W01-FOUNDATION
Packet:   FEAT-USER-AUTH-W01-P01-CREATE-JWT-UTILS
Run:      FEAT-USER-AUTH-W01-P01-CREATE-JWT-UTILS-R01
```

**Преимущества:**
- ✅ Читаемо: сразу понятно что это
- ✅ Иерархия: видно feature → wave → packet → run
- ✅ Сортировка: естественная по алфавиту
- ✅ UI-friendly: можно показать дерево

---

## 🏗️ Архитектура

### API-First
```
FastAPI Server (центральная точка)
  ↓
Core Control Plane (state machine, router, checker)
  ↓
SQLite/Postgres DB
  ↓
Клиенты: Web UI, CLI (thin wrapper), Agents
```

### AI-First Data Model
- **Primary format:** JSON (machine-readable)
- **Markdown:** Только для debug mode
- **UI:** Парсит JSON и показывает красиво
- **Agents:** Читают/пишут JSON напрямую

### Packet vs Run
- **Packet:** Спецификация задачи (ЧТО делать)
- **Run:** Попытка выполнения (КАК делали)
- Packet может иметь несколько runs
- Если успех с первой попытки: Packet ≈ Run

### Wave Grouping
- **Wave:** Логическая группа packets
- Waves выполняются последовательно (W01 → W02 → W03)
- Packets внутри wave — параллельно (если нет конфликтов)
- Checkpoints после каждой wave

---

## 📋 Что переиспользуем (70%)

✅ Packet execution engine (run_e2e_packet, run_managed_packet)
✅ Worktree management
✅ Agent launcher (расширим под разные провайдеры)
✅ Git operations (git_mutation_gate)
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

## ❌ Что удаляем

❌ Всё что связано с Prefect
❌ Старые briefs
❌ Сложные verification profiles

---

## 📅 План реализации

### Phase 0: Подготовка (2-3 дня)
- Удалить Prefect dependencies
- Вычистить legacy код
- Создать новую структуру проекта

### Phase 1: Core с абстракциями (1 неделя)
- DB schema с иерархическими ID
- Executor abstraction
- Acceptance policy abstraction
- Complexity router abstraction
- State machine с ступенчатой приёмкой

### Phase 2: API + Worker (1 неделя)
- FastAPI server
- Worker loop (переиспользует существующий execution engine)
- Интеграция с существующим кодом

### Phase 3: CLI + Telegram (3-4 дня)
- Thin CLI wrapper
- Telegram bot для уведомлений
- grace init command

### Phase 4: Testing (3-4 дня)
- E2E тесты
- Реальный feature test
- GRACE Canon compliance

**Итого: 3-4 недели до рабочего MVP**

---

## 🎯 Критерии готовности MVP

MVP готов когда:

✅ Architect создаёт packets из feature spec
✅ Packets имеют человекочитаемые иерархические ID
✅ Worker выполняет packet через существующий run_e2e_packet
✅ Ступенчатая приёмка работает (T0 → T1 → T2 → Canon → Reviewer)
✅ GRACE Canon проверки работают
✅ Evidence собирается в JSON формате
✅ Acceptance decision работает (FAST/NORMAL/STRICT)
✅ Auto-merge работает для ACCEPTED packets
✅ Events логируются в DB
✅ CLI команды работают
✅ Telegram уведомления работают
✅ UI показывает иерархию (feature → wave → packet → run)

---

## 📚 Документы

1. **GRACE_CONTROL_PLANE_SPEC.md** — полная спецификация (1647 строк)
2. **GRACE_CONTROL_PLANE_SUMMARY.md** — краткая выжимка
3. **GRACE_API_FIRST_ARCHITECTURE.md** — API-first архитектура
4. **GRACE_AI_FIRST_DATA_MODEL.md** — AI-first data model
5. **FINAL_DECISIONS.md** — этот документ (все решения)

---

**Все решения приняты. Готовы к реализации.**
