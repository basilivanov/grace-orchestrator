# ТЗ: Session Resume — переиспользование LLM-сессий в GRACE пайплайне

**Статус:** pending implementation (ТЗ готово, см. фазы ниже)
**Приоритет:** P1
**Дата:** 2026-06-07 (обновлено 2026-06-07 — добавлены admin UI + retention integration)
**Связанные TZ:** TZ_RETENTION_POLICY.md (cleanup `.opencode/` + worktree → branch deletion), TZ_ADMIN_PANEL.md (admin UI for session chains)

---

## Проблема

Каждый запуск LLM-агента (coder, architect, verifier, reviewer) создаёт
**новую сессию**. Агент заново читает кодовую базу, заново строит контекст,
заново понимает задачу. При retry/recovery это означает:

- ~50% токенов тратится на повторное чтение того же кода
- Агент не видит свои предыдущие попытки и ошибки acceptance
- Прогретый кэш модели (KV-cache на стороне провайдера) теряется
- Время cold start × N попыток

### Дополнительная проблема (2026-06-07)

Сессии opencode хранятся в `.opencode/` внутри worktree. При cleanup worktree
(по `TZ_RETENTION_POLICY.md` Phase 1) **все сессии теряются** — нет cross-reference
между LLM-сессией и packet_id в DB. Оператор не может:
- посмотреть цепочку сессий пакета
- понять, какая модель работала на каком attempt
- сделать pause/resume долгой задачи между перезапусками worker'а

## Решение

Ввести **session resume** — при повторных запусках агента на том же пакете
передавать `session_id` предыдущей сессии. LLM продолжает разговор с полным
контекстом предыдущей попытки.

**Дополнительно:** централизованное хранение session metadata в `agent_sessions`
таблице — даёт cross-reference packet ↔ session, видимость в admin UI, и
защиту от потери при cleanup worktree (сессия в БД переживает cleanup).

## Матрица ролей

| Роль | Resume | Режим | Обоснование |
|------|--------|-------|-------------|
| **Coder (retry same)** | ДА | `--session <id>` | Та же задача, та же модель. Видит ошибки acceptance, экономит контекст |
| **Coder (switch model)** | ДА (fork) | `--session <id> --fork` | Другая модель, но полезно видеть что предыдущий coder делал. Fork = readonly копия |
| **Architect (repack)** | ДА | `--session <id>` | Перепланирование. Видит все предыдущие попытки, что работало и что нет |
| **Architect (new, attempt 7+)** | НЕТ | новая сессия | Задумано как fresh eyes — без bias |
| **Architect (initial)** | НЕТ | новая сессия | Первое планирование — чистый контекст |
| **Verifier** | **НЕТ** | новая сессия | Должен быть беспристрастным. Resume создаёт confirmation bias |
| **Reviewer** | **НЕТ** | новая сессия | Независимая проверка. Свежий контекст = объективная оценка |
| **Context Collector** | НЕТ | новая сессия | Одноразовый scan |

## Архитектура: таблица `agent_sessions`

### Новая таблица в `db/schema.py`

```python
class AgentSession(Base):
    """Tracks LLM sessions for resume/fork across attempts."""

    __tablename__ = "agent_sessions"

    id = Column(String, primary_key=True)           # internal UID (ses_XXXX)
    external_id = Column(String, nullable=True)      # session_id from opencode/agy
    packet_id = Column(String, nullable=False, index=True)
    run_id = Column(String, nullable=True, index=True)  # PacketRun.id
    role = Column(String, nullable=False)             # coder | architect | verifier | reviewer
    executor_id = Column(String, nullable=True)       # agent profile ID
    backend = Column(String, nullable=False)          # opencode | agy
    attempt_number = Column(Integer, nullable=False)
    status = Column(String, nullable=False, default="active")  # active | completed | failed | forked
    parent_session_id = Column(String, nullable=True) # for forks — points to original
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    finished_at = Column(DateTime, nullable=True)
```

### Поле `resume_mode` в agent_profiles.yaml

```yaml
agents:
  coder-deepseek-flash:
    backend: cli
    inject_dir: true
    resume_mode: on_retry        # always | on_retry | on_fork | never
    resume_flag: "--session"     # CLI flag для session resume
    fork_flag: "--fork"          # CLI flag для fork (switch model)
    command:
      - opencode
      - run
      - "--model"
      - "{model}"
      - ...

  verifier-cheap:
    backend: cli
    resume_mode: never           # verifier всегда свежая сессия
    command:
      - opencode
      - run
      - ...

  coder_agy:
    backend: cli
    resume_mode: on_retry
    resume_flag: "--conversation" # agy использует другой флаг
    command:
      - agy
      - ...
```

Значения `resume_mode`:
- `always` — всегда resume если есть предыдущая сессия для этого пакета+роли
- `on_retry` — resume только при RETRY_SAME_CODER (тот же executor_id)
- `on_fork` — fork при смене модели (SWITCH_CODER), resume при retry
- `never` — всегда новая сессия (verifier, reviewer, new architect)

### Флаги CLI

| Backend | Resume | Fork |
|---------|--------|------|
| opencode | `--session <external_id>` | `--session <external_id> --fork` |
| agy | `--conversation <external_id>` | не поддерживает fork — fallback на новую сессию |

---

## Изменения по файлам

### 1. `src/grace_control/db/schema.py` — новая таблица

Добавить класс `AgentSession` (см. выше).

### 2. `src/grace_control/config/agent_profiles.yaml` — поля resume

Добавить в каждый профиль:
- `resume_mode`: `on_retry` для coders, `always` для architect-premium, `never` для verifier/reviewer
- `resume_flag`: `"--session"` для opencode, `"--conversation"` для agy
- `fork_flag`: `"--fork"` для opencode (опционально)

### 3. `src/grace_control/services/agent_run_service.py` — инъекция resume flags

```python
async def run(self, executor: dict, *, packet_id: str, ...,
              resume_session_id: str | None = None,
              fork: bool = False) -> dict[str, Any]:
    ...
    # Session resume injection
    resume_mode = executor.get("resume_mode", "never")
    if resume_session_id and resume_mode != "never":
        resume_flag = executor.get("resume_flag", "--session")
        command.append(resume_flag)
        command.append(resume_session_id)
        if fork:
            fork_flag = executor.get("fork_flag")
            if fork_flag:
                command.append(fork_flag)
    ...
    # После run — парсить session_id из stdout/результата
    result_session_id = _extract_session_id(result.stdout, backend_type)
    return {
        ...,
        "session_id": result_session_id,
    }
```

### 4. `src/grace_control/services/session_store.py` — новый файл

```python
class SessionStore:
    """CRUD for agent_sessions table."""

    def save(self, packet_id: str, run_id: str, role: str,
             executor_id: str, backend: str, attempt: int,
             external_id: str, parent_session_id: str | None = None) -> str:
        """Persist a session record. Returns internal session ID."""

    def find_latest(self, packet_id: str, role: str,
                    executor_id: str | None = None) -> AgentSession | None:
        """Find the most recent active/completed session for resume."""

    def find_for_fork(self, packet_id: str, role: str) -> AgentSession | None:
        """Find any completed session for fork (can be different executor_id)."""

    def mark_completed(self, session_id: str) -> None: ...
    def mark_failed(self, session_id: str) -> None: ...
```

### 5. `src/grace_control/adapters/packet_executor.py` — передача session context

В `_call_executor`:

```python
# Resolve resume session
from grace_control.services.session_store import SessionStore
store = SessionStore()
resume_session_id = None
fork = False

resume_mode = executor.get("resume_mode", "never")
if resume_mode in ("always", "on_retry", "on_fork") and attempt > 0:
    if resume_mode == "on_retry":
        # Same executor_id — direct resume
        prev = store.find_latest(pid, "coder", executor_id=executor.get("executor_id"))
        if prev:
            resume_session_id = prev.external_id
    elif resume_mode == "on_fork":
        # Different executor — fork previous session
        prev = store.find_for_fork(pid, "coder")
        if prev:
            resume_session_id = prev.external_id
            fork = True
    elif resume_mode == "always":
        prev = store.find_latest(pid, executor.get("role", "coder"))
        if prev:
            resume_session_id = prev.external_id
```

В `_call_executor` передать `resume_session_id` и `fork` в `AgentRunService.run()`.

После успешного run — сохранить session:

```python
if result_session_id := out.get("session_id"):
    store.save(
        packet_id=pid,
        run_id=run_id,
        role=executor.get("role", "coder"),
        executor_id=executor.get("executor_id", ""),
        backend=executor.get("backend", "cli"),
        attempt=attempt,
        external_id=result_session_id,
        parent_session_id=resume_session_id if fork else None,
    )
```

### 6. `src/grace_control/core/recovery_controller.py` — hint в RecoveryDecision

В `RecoveryDecision` добавить:

```python
class RecoveryDecision(BaseModel):
    ...
    resume_session_id: str | None = None  # session to resume/fork
    fork_session: bool = False             # True = fork, False = resume
```

В `_apply_decision`:
- `RETRY_SAME_CODER` → `store.find_latest()` → `resume_session_id`
- `SWITCH_CODER` → `store.find_for_fork()` → `resume_session_id` + `fork=True`
- `ARCHITECT_REPACK` → `store.find_latest(role="architect")` → `resume_session_id`

Передавать через `spec_json.recovery.resume_session_id`.

### 7. `src/grace_control/agent/universal_cli_backend.py` — пробросить resume

Передать `resume_session_id` и `fork` из `ExecutionRequest.spec` в
`AgentRunService.run()`.

### 8. `src/grace_control/agent/backend.py` — расширить ExecutionRequest

```python
@dataclass
class ExecutionRequest:
    ...
    resume_session_id: str | None = None
    fork_session: bool = False
```

---

## Парсинг session_id из вывода

### opencode

opencode выводит session_id в structured output (JSON mode):
```json
{"session_id": "ses_abc123", ...}
```

Или в default mode — в первых строках:
```
Session: ses_abc123
```

Функция `_extract_session_id(stdout, backend)`:
- Для `opencode`: regex `Session:\s*(ses_\w+)` или JSON parse
- Для `agy`: regex `Conversation ID:\s*(\S+)` или аналог

### Fallback

Если session_id не удалось извлечь — логируем warning, продолжаем без resume.
Отсутствие session_id не должно ломать пайплайн.

---

## Пайплайн с resume — полный lifecycle

```
Packet ready → Worker claims

  attempt=0: Coder run (new session)
    → session_id = "ses_001" saved to agent_sessions
    → Acceptance T0/T1/T2 → FAIL

  Recovery: RETRY_SAME_CODER (odd attempt)
    → find_latest(packet, coder, same executor) → ses_001
    → resume_mode=on_retry → inject --session ses_001

  attempt=1: Coder run (RESUME ses_001)
    → LLM sees: previous code + acceptance errors
    → session_id = "ses_001" (same session continued)
    → Acceptance T0/T1/T2 → FAIL

  Recovery: RUN_VERIFIER (even attempt)
    → Verifier run (NEW session, resume_mode=never)
    → verdict: REWORK_TO_CODER → SWITCH_CODER

  Recovery: SWITCH_CODER
    → find_for_fork(packet, coder) → ses_001
    → new executor (e.g. coder-sonnet instead of coder-deepseek-flash)
    → resume_mode=on_fork → inject --session ses_001 --fork

  attempt=2: Coder run (FORK ses_001, new model)
    → LLM sees: readonly copy of previous attempts
    → session_id = "ses_002" (new forked session)
    → Acceptance → PASS → Merge
```

---

## Порядок реализации

```
Phase 1: Schema + Store (можно без CLI интеграции)
  1. AgentSession в db/schema.py
  2. SessionStore в services/session_store.py
  3. resume_mode/resume_flag/fork_flag в agent_profiles.yaml

Phase 2: CLI Integration
  4. AgentRunService — resume_session_id parameter + flag injection
  5. _extract_session_id() — парсинг session_id из stdout
  6. UniversalCliAgentBackend — пробросить resume fields

Phase 3: Pipeline Wiring
  7. PacketExecutionAdapter — session lookup + save
  8. RecoveryDecision — resume_session_id + fork_session fields
  9. RecoveryController — session resolution при retry/switch/repack

Phase 4: Observability
  10. grace trace — показывать session chains
  11. API endpoint: GET /api/sessions/{packet_id} — история сессий пакета
```

---

## Затронутые файлы

| Файл | Изменение |
|------|-----------|
| `src/grace_control/db/schema.py` | Новый класс `AgentSession` |
| `src/grace_control/services/session_store.py` | **Новый файл** — CRUD для agent_sessions |
| `src/grace_control/services/agent_run_service.py` | Параметр `resume_session_id`, инъекция CLI flags, парсинг session_id из stdout |
| `src/grace_control/config/agent_profiles.yaml` | Поля `resume_mode`, `resume_flag`, `fork_flag` в каждом профиле |
| `src/grace_control/adapters/packet_executor.py` | Session lookup перед run, session save после run |
| `src/grace_control/agent/backend.py` | Поля `resume_session_id`, `fork_session` в `ExecutionRequest` |
| `src/grace_control/agent/universal_cli_backend.py` | Пробросить resume из request в AgentRunService |
| `src/grace_control/core/feature_recovery.py` | Поля `resume_session_id`, `fork_session` в `RecoveryDecision` |
| `src/grace_control/core/recovery_controller.py` | Session resolution при формировании decision |
| `src/grace_control/api/routers/trace.py` | Session chain в trace output |
| `src/grace_control/api/routers/admin_ui.py` | `GET /admin/_partial/sessions` partial (см. §Admin UI) |
| `src/grace_control/services/admin_aggregation_service.py` | `get_packet_sessions()` method |
| `src/grace_control/ui/templates/admin/_tab.html` | Sessions tab content (cross-ref) |
| `src/grace_control/ui/static/admin.css` | Session chain styles |

---

## Admin UI (2026-06-07, новый раздел)

### Tab "Agent sessions" в packet detail

`ui_tab_label("sessions")` → "Agent sessions" (уже есть по TZ_ADMIN_PANEL §3.10).

**Содержимое tab:**

| Column | Source |
|--------|--------|
| `ses_001` (id) | `agent_sessions.id` |
| role | `agent_sessions.role` |
| executor_id | `agent_sessions.executor_id` |
| attempt_number | `agent_sessions.attempt_number` |
| status | `agent_sessions.status` (active / completed / failed / forked) |
| created_at | `agent_sessions.created_at` (HH:MM:SS) |
| duration | `finished_at - created_at` (fmt_duration) |
| fork_of | `agent_sessions.parent_session_id` (если есть) |
| link | `agent_sessions.external_id` (deep-link to opencode, если возможно) |

**Visual chain:**

```
ses_001 (coder-deepseek-flash, attempt 0, completed)
   └── ses_002 (coder-deepseek-flash, attempt 1, completed) [resume]
         └── ses_003 (coder-sonnet, attempt 2, active) [fork]
```

**Если таблица `agent_sessions` не существует** (миграция не применена):
- Banner: "Sessions not yet tracked (TZ_SESSION_RESUME pending)"
- (Уже реализовано в `get_packet_sessions` через `sqlite_master` check, см. TZ_ADMIN_PANEL §Account for TZ_SESSION_RESUME)

### Endpoint

```
GET /api/admin/packet/{id}/sessions
  → { sessions: [...], reason: "ok" | "table_missing" }
  → (уже описан в TZ_ADMIN_PANEL.md §Account for TZ_SESSION_RESUME)
```

**Изменение:** теперь `sessions` это список dict'ов с полями:
```json
[
  {
    "id": "ses_001",
    "external_id": "ses_abc123",
    "role": "coder",
    "executor_id": "coder-deepseek-flash",
    "attempt_number": 0,
    "status": "completed",
    "parent_session_id": null,
    "created_at": "2026-06-07T10:00:00",
    "finished_at": "2026-06-07T10:05:00",
    "duration_seconds": 300,
    "fork_of": null
  },
  {
    "id": "ses_002",
    "external_id": "ses_def456",
    "role": "coder",
    "executor_id": "coder-deepseek-flash",
    "attempt_number": 1,
    "status": "completed",
    "parent_session_id": "ses_001",
    "fork_of": "ses_001",
    "created_at": "2026-06-07T10:10:00",
    "finished_at": "2026-06-07T10:18:00",
    "duration_seconds": 480
  }
]
```

---

## Retention integration (2026-06-07, новый раздел)

### Связь с TZ_RETENTION_POLICY.md

**Проблема:** при cleanup worktree (по retention policy) `.opencode/` сессии теряются.
**Решение:** session metadata хранится в `agent_sessions` таблице → **не теряется** при cleanup worktree. Это даёт:
- Cross-reference packet ↔ session в admin
- Возможность resume при следующем attempt (если `external_id` сохранён)
- Audit trail: кто какую модель запускал на каком attempt

### `.opencode/` cleanup — НЕ НУЖЕН отдельный

С `.opencode/` session storage:
- LLM-контекст всё равно в DB opencode (SQLite в `~/.local/share/opencode/storage/` или `~/.opencode/opencode.db`)
- При cleanup worktree теряется только **локальная копия**, opencode DB на хосте остаётся
- Session resume через `--session <external_id>` работает напрямую с opencode DB
- Поэтому **отдельный cleanup `.opencode/` НЕ нужен** — opencode сам управляет своей DB (через retention config, см. OpenCode PR #16730)

### Retention для `agent_sessions` (БД-таблица)

| State пакета | Поведение |
|--------------|-----------|
| Active (RUNNING) | Записи остаются |
| MERGED | Записи **остаются** (audit trail + возможен future resume) |
| REJECTED / FAILED | Записи **остаются** (для анализа) |
| BLOCKED_FINAL | Записи **остаются** (пока не удалили пакет) |
| Пакет удалён вручную (SQL) | Каскад `ON DELETE CASCADE` для `agent_sessions` (по `packet_id`) |

**TTL на записи в `agent_sessions` НЕ вводим** (по решению оператора, см. TZ_RETENTION_POLICY §Не-цели).

---

## Порядок реализации (детализированный)

### Phase 1: Schema + Store (1-2 дня)

**Файлы:**
- `src/grace_control/db/schema.py` — добавить `AgentSession` класс
- `src/grace_control/db/migrations/00XX_agent_sessions.py` — Alembic migration (если используется) или `db/__init__.py:_SQLITE_COLUMN_MIGRATIONS` (если inline) + CREATE TABLE
- `src/grace_control/services/session_store.py` — `SessionStore` CRUD
- `src/grace_control/config/agent_profiles.yaml` — добавить `resume_mode`, `resume_flag`, `fork_flag` в каждый профиль

**Тесты:**
- `tests/grace_control/db/test_agent_session_schema.py` — миграция применяется
- `tests/grace_control/services/test_session_store.py` — save/find_latest/find_for_fork/mark_completed

### Phase 2: CLI Integration (2-3 дня)

**Файлы:**
- `src/grace_control/agent/backend.py` — `ExecutionRequest.resume_session_id`, `fork_session`
- `src/grace_control/agent/universal_cli_backend.py` — пробросить в `AgentRunService`
- `src/grace_control/services/agent_run_service.py` — параметры, инъекция CLI flags, `_extract_session_id()`
- `src/grace_control/config/agent_profiles.yaml` — конкретные флаги для opencode/agy

**Парсинг session_id:**
```python
# src/grace_control/services/agent_run_service.py
import re
import json

_SESSION_PATTERNS = {
    "opencode": [
        re.compile(r'"session_id":\s*"(ses_\w+)"'),
        re.compile(r'Session:\s*(ses_\w+)'),
    ],
    "agy": [
        re.compile(r'Conversation ID:\s*(\S+)'),
    ],
}

def _extract_session_id(stdout: str, backend: str) -> str | None:
    for pat in _SESSION_PATTERNS.get(backend, []):
        m = pat.search(stdout)
        if m:
            return m.group(1)
    # Try JSON parse
    try:
        data = json.loads(stdout)
        if isinstance(data, dict) and "session_id" in data:
            return data["session_id"]
    except (json.JSONDecodeError, TypeError):
        pass
    return None
```

**Тесты:**
- `tests/grace_control/services/test_agent_run_service.py` — resume flags в command
- `tests/grace_control/services/test_session_id_extraction.py` — все regex паттерны

### Phase 3: Pipeline Wiring (2-3 дня)

**Файлы:**
- `src/grace_control/adapters/packet_executor.py:_call_executor` — session lookup перед run, save после run
- `src/grace_control/core/feature_recovery.py` — `RecoveryDecision.resume_session_id`, `fork_session`
- `src/grace_control/core/recovery_controller.py` — `_apply_decision` вызывает `SessionStore`:
  - `RETRY_SAME_CODER` → `find_latest(role="coder", executor_id=same)` → `resume_session_id`
  - `SWITCH_CODER` → `find_for_fork(role="coder")` → `resume_session_id` + `fork=True`
  - `ARCHITECT_REPACK` → `find_latest(role="architect")` → `resume_session_id`

**Тесты:**
- `tests/grace_control/core/test_recovery_with_resume.py` — RETRY передаёт session
- `tests/grace_control/core/test_recovery_with_fork.py` — SWITCH передаёт session + fork=True
- `tests/grace_control/adapters/test_packet_executor_session.py` — lookup + save

### Phase 4: Admin UI (1-2 дня)

**Файлы:**
- `src/grace_control/services/admin_aggregation_service.py` — `get_packet_sessions(packet_id)`:
  - Проверить наличие таблицы `agent_sessions` через `sqlite_master` (forward-compat)
  - Если есть → query `SELECT * FROM agent_sessions WHERE packet_id=? ORDER BY created_at`
  - Если нет → `{sessions: [], reason: "table_missing"}`
- `src/grace_control/api/routers/admin_ui.py` — endpoint `GET /api/admin/packet/{id}/sessions` (уже описан в TZ_ADMIN_PANEL)
- `src/grace_control/ui/templates/admin/_tab.html` — Sessions tab content
- `src/grace_control/ui/static/admin.css` — session chain styles (`.session-chain`, `.session-node`, `.session-fork-arrow`)

**Тесты:**
- `tests/grace_control/services/test_admin_aggregation_sessions.py` — get_packet_sessions
- `tests/ui/test_admin_ui_sessions_tab.py` — рендеринг цепочки, banner если table_missing

### Phase 5: Observability + polish (1 день)

**Файлы:**
- `src/grace_control/api/routers/trace.py` — добавить session chain в `grace trace --packet <id>`
- `src/grace_control/services/trace_service.py` — `get_session_chain(packet_id)` → список сессий с fork arrows
- CLI: `grace trace --session <external_id>` — показать packet context для данной сессии

**Тесты:**
- `tests/grace_control/api/test_trace_with_sessions.py` — trace выводит chain

---

## Метрики успеха

| Метрика | Без resume | С resume | Как измерить |
|---------|-----------|----------|--------------|
| Токены на retry (coder) | 100% (полный контекст) | ~40% (delta + acceptance errors) | `agent_sessions.prompt_tokens_total` aggregate |
| Время cold start | ~15-30s | ~5s (прогретый KV-cache) | `agent_sessions.duration_seconds` first attempt |
| Качество retry | Не знает что пробовал | Видит ошибки, не повторяет | acceptance pass rate per attempt_number |
| Recovery chain visibility | Только в logs | Admin UI + grace trace | feature flag `session_resume_enabled` |

**KPI для включения (gradual rollout):**
- 1000 пакетов в `agent_sessions` таблице
- ≥30% coder attempts используют resume
- Acceptance pass rate (attempt 2+): ≥2x vs control group

---

## Риски (обновлено 2026-06-07)

| Риск | Вероятность | Митигация |
|------|-------------|-----------|
| opencode/agy меняют формат session_id | Medium | Regex с fallback, graceful degradation (без resume) |
| Слишком длинный контекст при 5+ resume | Medium | Лимит на глубину resume chain (configurable, default 5) |
| Resume на другой worktree | Low | Session привязана к packet_id, worktree создаётся для того же пакета |
| Fork не поддерживается бэкендом | Low | Fallback на новую сессию, log warning |
| OpenCode session потеряна (`.opencode/` cleanup) | Low | Resume через `external_id` в opencode DB, не через `.opencode/` |
| `agent_sessions` migration не применена | Medium | Forward-compat через `sqlite_master` check (уже есть) |

---

## Критерии приёмки

1. При `RETRY_SAME_CODER` — coder получает `--session <id>` и продолжает предыдущую сессию
2. При `SWITCH_CODER` — новый coder получает `--session <id> --fork` и видит историю предыдущего
3. При `ARCHITECT_REPACK` — architect получает `--session <id>` с контекстом всех попыток
4. Verifier и reviewer **всегда** запускаются с новой сессией (resume_mode=never)
5. Architect с attempt >= 7 (NEW_ARCHITECT) запускается с новой сессией
6. Если session_id не удалось извлечь — пайплайн работает как раньше (graceful fallback)
7. `agent_sessions` таблица заполняется при каждом запуске агента
8. `grace trace --packet <id>` показывает цепочку сессий
9. Все существующие тесты проходят (resume — opt-in, не ломает default path)

---

## Ожидаемый эффект

| Метрика | Без resume | С resume |
|---------|-----------|----------|
| Токены на retry (coder) | 100% (полный контекст) | ~40% (только delta + acceptance errors) |
| Время cold start | ~15-30s | ~5s (прогретый KV-cache) |
| Качество retry | Агент не знает что пробовал | Агент видит ошибки, не повторяет |
| Качество architect repack | Заново читает все файлы | Видит все N попыток и их результаты |

## Риски

| Риск | Митигация |
|------|-----------|
| opencode/agy меняют формат session_id | Regex с fallback, graceful degradation |
| Слишком длинный контекст при 5+ resume | Лимит на глубину resume chain (configurable) |
| Resume на другой worktree | Session привязана к packet_id, worktree создаётся для того же пакета |
| Fork не поддерживается бэкендом | Fallback на новую сессию, log warning |
