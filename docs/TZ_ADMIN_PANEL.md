# ТЗ: Admin Panel v2 — наблюдаемость пайплайна GRACE

**Статус:** implemented ✓
**Приоритет:** P0 — рабочая лошадка для оператора оркестратора
**Дата:** 2026-06-07

---

## Контекст

Текущая админка (`dashboard.html` 516 строк inline HTML/CSS/JS + `DashboardService`) устарела:
- Не показывает worker/model/prompt каждого run
- Не показывает стадии T0/T1/T2 (и планируемые T2_BROWSER/T3_VISUAL)
- Не показывает recovery chain (почему retry, какой decision)
- Не учитывает TZ_SESSION_RESUME (sessions chain с parent_session_id)
- Нет разделения aggregated view ↔ drill-down до raw bytes
- Timestamps в текущей админке — 12h AM/PM (нужен 24h)
- Нет elapsed time для running пакетов
- Нет mobile-варианта
- Нет planned control endpoints (resume/delete/stop)
- При ошибке пакета не видно "кто заболчил и почему" сразу в header
- Нет sizes артефактов с smart rendering (bytes vs MB)

**Решение:** выкидываем текущую админку полностью, делаем новую с нуля.

---

## Архитектурные решения

| # | Решение | Значение |
|---|---------|----------|
| 1 | Backend | расширяем существующий FastAPI, новый роутер `/api/admin/*` |
| 2 | Frontend | vanilla HTML + CSS + JS, **без** билд-шага, **без** npm, **без** React |
| 3 | Mount | `/admin` (SPA) + `/api/admin/*` (API) |
| 4 | Mobile | responsive single HTML, breakpoints 900/600 |
| 5 | Aggregated view | обзор без raw payload (counts + event_type + reason only) |
| 6 | Drill-down | табы Spec/Runs/Sessions/Evidence/Logs/Artifacts |
| 7 | "Every byte" | raw log tail + binary artifacts с hex preview |
| 8 | Read-only v1 | все control endpoints возвращают 501 с `planned: true` |
| 9 | Planned controls | resume / delete / stop — задизайнены, но stub'ы |
| 10 | Real-time | polling 5s, без WebSocket |
| 11 | Auth | существующий AuthMiddleware (localhost bypass) |
| 12 | Session chain | forward-compat с TZ_SESSION_RESUME, пустой до реализации |
| 13 | Storage model/prompt | **колонки в PacketRun** (model, command_preview, prompt) |
| 14 | Elapsed time | на каждом poll (5s), вычисляется на клиенте |
| 15 | Failure view | command + stderr tail встроены в "Blocking decision" |
| 16 | Timestamps | **24h формат везде** (HH:MM:SS или YYYY-MM-DD HH:MM:SS[.mmm]) |
| 17 | Artifacts | **per run** (evidence_path принадлежит PacketRun, не Packet) |
| 18 | Artifact sizes | байты от сервера, smart unit на клиенте через `fmtSize()` (B/KB/MB/GB) |
| 19 | Artifact rendering | image — always inline, text — inline если <1MB, binary — hex preview если <256KB, иначе Download |

---

## Throw away (удаляем)

| Файл | Почему |
|------|--------|
| `src/grace_control/ui/templates/dashboard.html` | 516 строк inline HTML/CSS/JS |
| `src/grace_control/services/dashboard_service.py` | заменяется на AdminAggregationService |
| `src/grace_control/api/routers/dashboard.py` | заменяется на admin.py |

Никаких back-compat алиасов — чистый cutover.

---

## Schema additions

### `db/schema.py` — добавить в `PacketRun`:

```python
class PacketRun(Base):
    __tablename__ = "packet_runs"

    id = Column(String, primary_key=True)
    packet_id = Column(String, nullable=False, index=True)
    run_number = Column(Integer, nullable=False)
    executor_id = Column(String)
    worker_id = Column(String, index=True)
    status = Column(String, nullable=False)
    result_json = Column(JSON)
    evidence_path = Column(String)
    started_at = Column(DateTime)
    finished_at = Column(DateTime)
    duration_ms = Column(Integer)

    # NEW (admin v2): для отображения в админке
    model = Column(String, nullable=True)            # "deepseek/deepseek-v4-flash"
    command_preview = Column(JSON, nullable=True)     # ["opencode", "run", "--model", "..."]
    prompt = Column(Text, nullable=True)              # финальный prompt text
```

### Migration: `db/migrations/0009_packetrun_admin_fields.py`

Alembic-style upgrade:
1. ALTER TABLE packet_runs ADD COLUMN model VARCHAR
2. ALTER TABLE packet_runs ADD COLUMN command_preview JSON
3. ALTER TABLE packet_runs ADD COLUMN prompt TEXT

Downgrade: drop columns.

### Population: `packet_executor.py` / `universal_cli_backend.py`

При `run_started` сохранять:
- `executor["model"]` → `run.model`
- `final_command` (после template substitution) → `run.command_preview`
- `final_prompt` (input.template рендер или packet_markdown если mode=stdin) → `run.prompt`

В `PacketService.claim` / `PacketExecutor._call_executor` прокинуть эти поля через `ExecutionResult`.

---

## Endpoint design (read-only v1)

### Read endpoints (GET)

```
GET  /api/admin/overview
  → { stats, health, recent_events, blocked, workers }
  - stats.by_state: {ready: 5, running: 1, accepted: 3, ...}
  - health: {supervisor_alive, workers_alive, code_sha, db_ok}
  - recent_events: last 20, БЕЗ payload_json (только type/entity_id/timestamp/reason)
  - blocked: list of BLOCKED_RECOVERABLE/BLOCKED_FINAL packets
GET  /api/admin/features
  → { features: [ { id, slug, title, status, waves: [ { id, slug, title, order, status, packets: [ { id, slug, title, state, attempt_count, max_attempts } ] } ] } ] }
  - ПИТАЕТ ОСНОВНОЙ ВИД OVERVIEW (drill-down feature → wave → packet)
  - id+slug КАЖДОЙ сущности — для UI (рядом с названием)
  - workers: [{id, status, current_packet_id, last_heartbeat, current_elapsed}]

GET  /api/admin/packet/{id}/detail
  → { packet, worker_id, model, started_at, elapsed_seconds, is_running,
      recovery, recommendation, sessions_summary, runs_summary, blocking_decision }
  - blocking_decision: null если state не в error/terminal
  - is_running: bool (для elapsed на клиенте)

GET  /api/admin/packet/{id}/blocking_decision  (NEW)
  → { has_blocking: bool, state, decided_by, action, reason, at,
      last_failure: { stage, summary, blocking_issues,
                      command_failures: [{command, exit_code, stderr_tail, stdout_tail}],
                      stderr_tail: последние 30 строк (если executor crash) } }
  - decided_by: "feature_recovery" | "recovery_controller" | "acceptance_pipeline" | null
  - last_failure.command_failures: список failed commands с tail

GET  /api/admin/packet/{id}/timeline?limit=200&offset=0
  → { total, events: [{timestamp, event_type, component, reason, payload}] }
  - payload: full JSON (только в drill-down, не в overview)

GET  /api/admin/packet/{id}/runs
  → { runs: [{run_id, run_number, worker_id, executor_id, model, status,
              duration_ms, started_at, finished_at, elapsed_seconds, is_running}] }

GET  /api/admin/packet/{id}/runs/{run_id}
  → { run, result_json, command_preview, model, prompt, evidence_path,
      artifacts_summary: { total_files, total_size, files: [{name, size, type}] } }
  - artifacts_summary.total_size в байтах (клиент форматирует через fmtSize)

GET  /api/admin/packet/{id}/runs/{run_id}/evidence
  → { stages: [{name, status, summary, blocking_issues, commands_summary}],
      verdict, summary, screenshots: [{path, viewport, diff_pct, kind}] }
  - stages включает T0_SCOPE_AND_LINT, T1_TARGETED_TESTS, T2_FULL_TESTS,
    T2_BROWSER_E2E (planned), T3_VISUAL_REGRESSION (planned)
  - для T2_BROWSER/T3_VISUAL: screenshots[] (пусто сейчас)
  - commands_summary: {passed: N, failed: M}

GET  /api/admin/packet/{id}/sessions
  → { sessions: [], reason: "table_missing" | "ok" }
  - forward-compat: проверяет наличие таблицы agent_sessions
  - если reason=="table_missing" — пустой список (frontend показывает баннер)

GET  /api/admin/packet/{id}/runs/{run_id}/artifacts
  → { tree: [{name, type: "file"|"dir", size, children: []}] }
  - size: int в байтах (для каждого файла)

GET  /api/admin/packet/{id}/runs/{run_id}/artifacts/file?path=...&tail=N
  → Plain text / bytes (Content-Type по расширению)
  - path-traversal safe (target внутри evidence_dir)
  - tail=N — последние N строк (для больших файлов)

GET  /api/admin/packet/{id}/runs/{run_id}/logs?stream=stderr&tail=200&filter=error
  → { lines: [...], total, truncated, source_file }
  - stream: stderr | stdout | agent (читаем JSONL воркера из worktree)
  - tail: последние N строк
  - filter: regex для подсветки/фильтрации

GET  /api/admin/feature/{id}/summary
  → { feature, waves: [{id, title, order, status, packets: [...]}] }

GET  /api/admin/search?q=...&limit=50
  → { results: [{kind: "packet"|"feature"|"run", id, title, ...}] }
  - переиспользует TraceService.search

GET  /api/admin/system/health
  → { supervisor_alive, api_alive, workers_alive, db_ok, code_sha, version }

GET  /api/admin/system/workers
  → { workers: [{id, status, current_packet_id, last_heartbeat, started_at}] }
```

### Planned control stubs (POST, возвращают 501 в v1)

```
POST /api/admin/packet/{id}/resume
  → 501 { error: "not_implemented", planned: "v2", doc: "TZ_SESSION_RESUME.md" }

POST /api/admin/packet/{id}/delete
  → 501 { error: "not_implemented", planned: "v2" }

POST /api/admin/packet/{id}/stop
  → 501 { error: "not_implemented", planned: "v2" }
```

В v1 stubs возвращают 501 + `planned: true`, чтобы frontend мог показать "Planned, not yet implemented" вместо "Unknown endpoint".

---

## Frontend structure (vanilla SPA)

### File layout

```
src/grace_control/ui/
├── templates/
│   └── admin.html           # shell page ~50 строк
└── static/
    ├── admin.css            # tokens + responsive ~200 строк
    └── admin.js             # SPA: hash routing, fetch, DOM ~450 строк
```

### `admin.html` (shell)

```html
<!doctype html>
<html lang="en" data-theme="dark">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>GRACE Admin</title>
  <link rel="stylesheet" href="/static/admin.css">
</head>
<body>
  <div id="app">
    <header class="hdr">
      <a href="#/" class="logo">GRACE</a>
      <span id="health" class="health">...</span>
      <span id="clock" class="time"></span>
    </header>
    <nav id="nav" class="nav"></nav>
    <main id="main" class="main"></main>
  </div>
  <script src="/static/admin.js"></script>
</body>
</html>
```

### Hash routes

| Hash | View | API calls |
|------|------|-----------|
| `#/` | Overview | `GET /api/admin/overview` + `GET /api/admin/features` (poll 5s) |
| `#/packet/{id}` | Packet detail (default tab: Timeline) | `GET /packet/{id}/detail` + tab |
| `#/packet/{id}/spec` | Spec tab | `GET /packet/{id}/detail` |
| `#/packet/{id}/runs` | Runs tab | `GET /packet/{id}/runs` |
| `#/packet/{id}/sessions` | Sessions tab | `GET /packet/{id}/sessions` |
| `#/packet/{id}/evidence` | Evidence tab | `GET /packet/{id}/runs/{run_id}/evidence` |
| `#/packet/{id}/logs` | Logs tab | `GET /packet/{id}/runs/{run_id}/logs` |
| `#/packet/{id}/artifacts` | Artifacts tab | `GET /packet/{id}/runs/{run_id}/artifacts` |
| `#/feature/{id}` | Feature summary | `GET /feature/{id}/summary` |
| `#/search?q=...` | Search results | `GET /search?q=...` |
| `#/system` | System health | `GET /system/health` + `/system/workers` |

### Helpers (`admin.js`)

```js
// 24h timestamp formatting
function fmtTime(iso) {
  if (!iso) return '';
  const d = new Date(iso);
  return d.toISOString().slice(11, 19);  // "14:23:45"
}

function fmtTimeMs(iso) {
  if (!iso) return '';
  const d = new Date(iso);
  return d.toISOString().slice(11, 23);  // "14:23:45.123"
}

function fmtDateTime(iso) {
  if (!iso) return '';
  return iso.replace('T', ' ').replace('Z', '').slice(0, 19);
}

function fmtElapsed(seconds) {
  if (seconds == null || seconds < 0) return '';
  const h = Math.floor(seconds / 3600);
  const m = Math.floor((seconds % 3600) / 60);
  const s = Math.floor(seconds % 60);
  return [h, m, s].map(n => String(n).padStart(2, '0')).join(':');
}

// Size formatting (smart unit selection)
const SIZE_UNITS = [
  { unit: 'GB', div: 1024 ** 3, decimals: 2 },
  { unit: 'MB', div: 1024 ** 2, decimals: 2 },
  { unit: 'KB', div: 1024,      decimals: 1 },
  { unit: 'B',  div: 1,         decimals: 0 },
];

function fmtSize(bytes) {
  if (bytes == null) return '?';
  for (const { unit, div, decimals } of SIZE_UNITS) {
    if (bytes >= div) {
      const n = bytes / div;
      return `${n.toFixed(decimals)} ${unit}`;
    }
  }
  return '0 B';
}
```

Примеры:
- `234` → `"234 B"`
- `12_345` → `"12.1 KB"`
- `5_678_901` → `"5.42 MB"`
- `1_234_567_890` → `"1.15 GB"`

### Overview view

Главное — **drill-down по основным сущностям (features → waves → packets)**, рядом с каждой — её slug.

Layout (≥1100px):
- Stats bar (full width): supervisor / workers / features / packets / running / blocked / failed
- **Левая колонка (1.8fr): Features tree**
  - Feature: `status` pill + title + `id` mono
    - Wave: `status` pill + title + `#order` + `id` mono
      - Packets table: slug | state | A
- **Правая колонка (1fr):**
  - Workers (всегда, компактно): id | status | current packet
  - Blocked (когда есть): title | A

Layout (<1100px): одна колонка, всё стекается.

Data sources:
- `GET /api/admin/overview` → stats / health / workers / blocked
- `GET /api/admin/features` → features → waves → packets (с slug)

### Packet detail view (2 columns desktop: main + sticky sidebar / single column mobile)

**Header (всегда видно, 24h формат):**
```
[Title] [State badge]   [pkt_xxxxx] [slug-name]
Worker: wkr_abc123   Model: deepseek/deepseek-v4-flash
Started: 14:23:45     Elapsed: 00:01:23 (running)   ← recompute on poll
Prompt: [view 2.4 KB]  Command: [view 1.1 KB]      ← sizes в fmtSize
```

Layout:
- ≥1100px: main column (header + tabs + tab body) + sticky right sidebar (Blocking decision)
- <1100px: всё в одной колонке, Blocking decision inline сверху

**Blocking decision (если state ∈ {REJECTED, FAILED, BLOCKED, BLOCKED_RECOVERABLE, BLOCKED_FINAL}):**
```
┌─ Blocking decision ────────────────────────────────┐
│ State: BLOCKED_FINAL                                │
│ Decision by: feature_recovery                       │  ← component
│ Action: BLOCK_FEATURE                               │  ← из result_json.recovery.action
│ Reason: max_attempts reached on coder-deepseek-flash│  ← из result_json.recovery.reason
│ At: 2026-06-07 14:23:45 (2 min ago)                 │
│ Last failure:                                       │
│   T1: failed (1/2 commands)                         │
│   - npm test -- --reporter=json (exit=1)            │
│   "FAIL src/screens/Login.test.tsx"                 │
│   ↓ command_preview:                                │
│   [opencode run --model deepseek-v4-flash ...]      │
│   ↓ stderr_tail (30 lines):                         │
│   Error: ...                                        │
│   at ...                                            │
└────────────────────────────────────────────────────┘
```

**Tab bar:** Timeline | Spec | Runs | Sessions | Evidence | Logs | Artifacts

### Tab: Timeline

Вертикальный список событий пакета:
- timestamp (fmtTime) | event_type | component | reason
- payload в `<details>` (раскрывается по клику)
- цвета: red=fail, yellow=warn, green=ok, gray=info

### Tab: Sessions (forward-compat с TZ_SESSION_RESUME)

Дерево сессий:
```
ses_001 (coder, attempt 0, completed)
├── ses_002 (coder, attempt 1, resume --session ses_001)
└── ses_003 (coder, attempt 2, fork --session ses_001 --fork, new model)
```

Если таблица agent_sessions не существует:
- Баннер: "Sessions not yet tracked (TZ_SESSION_RESUME pending)"
- В v2 (когда TZ реализован) — баннер пропадает, появляется дерево

### Tab: Evidence (T0/T1/T2 + planned T2_BROWSER/T3_VISUAL)

Список stages из `acceptance_report.stages`:
- T0_SCOPE_AND_LINT: status, scope violations
- T1_TARGETED_TESTS: status, commands_summary {passed, failed}
- T2_FULL_TESTS: status, commands_summary
- T2_BROWSER_E2E (planned): status, screenshots count, viewports
- T3_VISUAL_REGRESSION (planned): status, diff_pct, viewport, baseline path
- Для каждой стадии: blocking_issues (если есть)

### Tab: Logs

- Stream selector: stderr | stdout | agent
- Tail input: 200 (default), 500, 1000, 5000
- Filter input: regex (опц.)
- "Refresh" button (polling 5s если открыт)
- Render: monospace, подсветка совпадений regex

### Tab: Artifacts (с sizes + smart rendering)

Tree view файлов из evidence_path:
- Каждый файл показывает `size` справа от имени через `fmtSize()` (моноширинно)
- Click file → smart rendering:

| Тип | Inline | Только Download |
|-----|--------|-----------------|
| image (.png/.jpg/.svg/.gif) | всегда `<img>` | — |
| text (.log/.txt/.json/.md) | если size < 1 MB → `<pre>` | если ≥ 1 MB |
| binary (всё остальное) | если size < 256 KB → hex preview (256 байт) | если ≥ 256 KB |

```js
async function openArtifact(path, size) {
  const url = `/api/admin/packet/${pid}/runs/${runId}/artifacts/file?path=${encodeURIComponent(path)}`;
  if (isImage(path)) {
    return `<img src="${url}">`;
  }
  if (isText(path)) {
    if (size < 1024 * 1024) {
      const r = await fetch(url);
      return `<pre>${escapeHtml(await r.text())}</pre>`;
    }
    return `<a download href="${url}">Download ${fmtSize(size)}</a>`;
  }
  // binary
  if (size < 256 * 1024) {
    const r = await fetch(url);
    const buf = new Uint8Array(await r.arrayBuffer());
    return `<pre>${hexPreview(buf.slice(0, 256))}</pre>`;
  }
  return `<a download href="${url}">Download ${fmtSize(size)}</a>`;
}
```

---

## Aggregated vs raw (принцип)

| View | Что показывает | Где |
|------|---------------|-----|
| Overview | stats + health + workers + last 20 events (type only, без payload) | base / |
| Packet detail header | state, worker, model, started, elapsed, recovery recommendation | base |
| Blocking decision | state + decided_by + action + reason + last_failure (command + stderr) | base (если error) |
| Timeline tab | events с payload (только тут, в overview не показывается) | drill |
| Evidence tab | stages + blocking_issues + screenshots (когда есть) | drill |
| Logs tab | raw stderr/stdout/JSONL tail | drill |
| Artifacts tab | tree + smart rendering по size | drill |

Принцип: **base view = aggregated без payload и raw data**. Drill-down = полные данные.

---

## Mobile responsive

| Breakpoint | Layout |
|------------|--------|
| ≥900px | 3 columns desktop (240px / 1fr / 320px) |
| 600-899px | 1 column, табы сверху, гамбургер для навигации |
| <600px | 1 column, увеличенный шрифт табов, scrollable табы |

Theme tokens наследуем из текущего `dashboard.html` (dark + light), но упрощаем CSS (без кастомных scrollbar, без сложных animations).

---

## Account for TZ_SESSION_RESUME (forward-compat)

`agent_sessions` таблица ещё не создана, но TZ_SESSION_RESUME.md её описывает:
- `id, external_id, packet_id, run_id, role, executor_id, backend, attempt_number, status, parent_session_id, created_at, finished_at`

**Admin TZ делает:**
1. `GET /api/admin/packet/{id}/sessions` — пытается читать `agent_sessions` через `db.execute(text("SELECT name FROM sqlite_master WHERE type='table' AND name='agent_sessions'"))`
2. Если таблица есть → возвращает `{sessions: [...], reason: "ok"}`
3. Если нет → возвращает `{sessions: [], reason: "table_missing"}`
4. Frontend: если `reason == "table_missing"` → баннер "Pending TZ_SESSION_RESUME"
5. Когда TZ реализуют → admin начинает показывать сессии без изменений

То же для `resume_mode` в `agent_profiles.yaml` — admin показывает `executor.resume_mode` если есть.

---

## Account for TZ_FRONTEND_ACCEPTANCE (T2_BROWSER/T3_VISUAL)

Evidence tab уже умеет показывать стадии из `acceptance_report.stages`. Когда TZ_FRONTEND_ACCEPTANCE будет реализован:
- T2_BROWSER_E2E появится в stages
- Evidence tab покажет: viewport count, screenshots[], telegram_mode, dev_command, ngrok_used (если STRICT+real)
- T3_VISUAL_REGRESSION: diff_pct, baseline path, current screenshot path, diff image path
- Artifacts tab: скриншоты рендерятся как `<img>` (уже умеем, image — always inline)
- Sizes скриншотов: через `fmtSize()` (PNG обычно 100-500 KB → "234 KB")
- Verifier (после реализации multimodal): кнопка "View in verifier" — откроет trace с image refs

Никаких изменений в admin TZ не потребуется, только данные появятся.

---

## Auth & security

- Используем существующий `AuthMiddleware` (`src/grace_control/api/auth.py`)
- Localhost bypass (если `GRACE_API_AUTH_ENABLED=false` или выключено)
- Bearer token для внешних клиентов
- Path-traversal safe в `/artifacts/file` и `/logs` (target внутри evidence_dir/worktree)

---

## Затронутые файлы

### Удалить
| Файл | Причина |
|------|--------|
| `src/grace_control/ui/templates/dashboard.html` | 516 строк inline, выкидываем |
| `src/grace_control/services/dashboard_service.py` | заменяется на AdminAggregationService |
| `src/grace_control/api/routers/dashboard.py` | заменяется на admin.py |

### Новые
| Файл | Назначение |
|------|-----------|
| `db/migrations/0009_packetrun_admin_fields.py` | Alembic-style migration: model, command_preview, prompt |
| `src/grace_control/services/admin_aggregation_service.py` | композиция services в admin DTOs |
| `src/grace_control/api/routers/admin.py` | `/api/admin/*` endpoints (read + planned stubs) |
| `src/grace_control/ui/templates/admin.html` | shell page |
| `src/grace_control/ui/static/admin.css` | tokens + responsive |
| `src/grace_control/ui/static/admin.js` | vanilla SPA: hash routing, fetch, DOM, fmtSize, fmtTime |
| `tests/grace_control/test_admin_aggregation_service.py` | unit |
| `tests/grace_control/test_admin_router.py` | integration |
| `docs/TZ_ADMIN_PANEL.md` | это ТЗ |

### Изменяемые
| Файл | Изменения |
|------|----------|
| `src/grace_control/db/schema.py` | добавить `model`, `command_preview`, `prompt` в `PacketRun` |
| `src/grace_control/core/packet_operations.py` или `adapters/packet_executor.py` | заполнять новые поля при run_started |
| `src/grace_control/agent/universal_cli_backend.py` | прокидывать model/command/prompt в ExecutionResult |
| `src/grace_control/api/app_factory.py` | mount admin router, serve `/admin` и `/static/*` |

---

## Порядок реализации

### P0 (блокирующие: текущая админка устарела)
```
1. Удалить dashboard.html, dashboard_service.py, dashboard.py
2. Migration 0009: добавить колонки model, command_preview, prompt в packet_runs
3. packet_executor + universal_cli_backend: заполнять новые поля при run_started
4. AdminAggregationService: get_overview, get_packet_detail, get_packet_runs,
   get_packet_run, get_packet_evidence, get_packet_artifacts,
   get_artifact_file, get_packet_logs, get_packet_blocking_decision
5. api/routers/admin.py: read endpoints + blocking_decision endpoint
6. admin.html + admin.css + admin.js: Overview + Packet Detail (Spec/Runs/Evidence/Logs/Artifacts)
7. mount в app_factory.py
8. fmtSize, fmtTime, fmtElapsed, fmtDateTime helpers в admin.js
9. Тесты
```

### P1 (sessions, search, system)
```
10. AdminAggregationService: get_packet_sessions (с forward-compat проверкой таблицы)
11. AdminAggregationService: get_feature_summary, search, get_system_health, get_workers
12. api/routers/admin.py: добавить endpoints
13. admin.js: Sessions tab, Feature view, Search, System view
14. Planned control stubs: /resume, /delete, /stop возвращают 501
```

### P2 (polish)
```
15. Mobile responsive refinement
16. Light theme
17. Hex preview для binary artifacts (если ещё не сделано в P0)
18. Keyboard shortcuts (j/k для навигации по спискам)
```

---

## Критерии приёмки

1. `/admin` открывается в браузере, показывает Overview с stats/health/workers/recent events (без payload)
2. Клик на пакет → Packet Detail с header (state, worker_id, model, started_at, elapsed, recommendation)
3. Timestamps везде в 24h формате (`HH:MM:SS` или `YYYY-MM-DD HH:MM:SS[.mmm]`)
4. Elapsed time обновляется на каждом poll (5s), формат `HH:MM:SS`
5. Tab Spec показывает spec_json formatted
6. Tab Runs показывает список PacketRun с worker_id/executor_id/model/duration_ms/exit_code
7. Tab Evidence показывает T0/T1/T2 + (planned) T2_BROWSER/T3_VISUAL
8. Tab Logs показывает tail stderr/stdout с filter regex
9. Tab Artifacts показывает tree с size в `fmtSize()` (B/KB/MB/GB)
10. Click на image файл — inline `<img>` независимо от size
11. Click на text файл < 1 MB — inline `<pre>`; ≥ 1 MB — Download button
12. Click на binary файл < 256 KB — hex preview (256 байт); ≥ 256 KB — Download
13. Tab Sessions показывает баннер "Pending TZ_SESSION_RESUME" (когда таблица не существует)
14. Search: substring по packet id/title, feature title, run executor_id
15. Mobile (<900px): табы сверху, гамбургер, 1 column
16. Polling 5s: Overview обновляется автоматически
17. POST /resume, /delete, /stop → 501 + `planned: true`
18. Forward-compat: когда TZ_SESSION_RESUME создаст agent_sessions — Sessions tab сразу заработает
19. Forward-compat: когда TZ_FRONTEND_ACCEPTANCE создаст T2_BROWSER/T3_VISUAL — Evidence tab сразу покажет
20. При state ∈ error/terminal — Blocking decision видна в header: state, decided_by, action, reason, last_failure с command_preview + stderr_tail (30 строк)
21. Auth: localhost bypass работает (через AuthMiddleware)
22. Path-traversal safe: /artifacts/file и /logs не дают выйти за evidence_dir/worktree
23. Schema migration применена: `model`, `command_preview`, `prompt` колонки в `packet_runs`
24. При run_started эти поля заполняются в packet_executor (model=executor.model, command_preview=final_command, prompt=final_prompt)
25. Старые тесты: 478 passed / 24 pre-existing failed (без регрессий)

## Acceptance summary (2026-06-07)

- **Router**: `src/grace_control/api/routers/admin.py` — 20 endpoints (16 read + 3 planned stubs + 1 system workers).
- **Aggregation**: `src/grace_control/services/admin_aggregation_service.py` — 15 read methods composing TraceService / EventQueryService patterns.
- **SPA shell**: `src/grace_control/ui/templates/admin.html` (~17 lines).
- **SPA CSS**: `src/grace_control/ui/static/admin.css` (~470 lines, dark+light tokens, breakpoints 1100/900/600, 2-col desktop grid, sticky sidebar).
- **SPA JS**: `src/grace_control/ui/static/admin.js` (~720 lines, hash routing, polling 5s, fmtSize/fmtTime/fmtElapsed/fmtDateTime helpers, smart artifact rendering, features tree drill-down).
- **Mount**: `src/grace_control/api/app_factory.py` — admin router + `/admin` shell + `/static` mount + `/` → `/admin` 307 redirect.
- **Schema migration**: `src/grace_control/db/__init__.py:_SQLITE_COLUMN_MIGRATIONS` — 3 new ALTER TABLE for `model`/`command_preview`/`prompt`.
- **Executor population**: `src/grace_control/adapters/packet_executor.py:_route_after` — `_acc` and `_rej` paths populate new columns via `update_run_result`.
- **Tests**:
  - `tests/grace_control/services/test_admin_aggregation_service.py` — 33 unit tests (added 2: `test_features_tree_empty_returns_empty_list`, `test_features_tree_returns_features_with_waves_and_packets_with_slugs`).
  - `tests/grace_control/api/test_admin_router.py` — 29 integration tests (added 2: `test_features_tree_empty`, `test_features_tree_includes_waves_and_packets_with_slugs`).
  - `tests/grace_control/api/test_w5_app_factory.py` — replaced 4 broken dashboard tests with 3 new admin-mount tests (per "agent-written broken tests: delete, don't fix" policy).
- **Forward-compat**:
  - Sessions tab: `get_packet_sessions` checks `sqlite_master` for `agent_sessions` → `{sessions: [], reason: "table_missing"}` until TZ_SESSION_RESUME lands.
  - Evidence tab: `get_packet_evidence` reads `acceptance_report.stages` — T2_BROWSER_E2E/T3_VISUAL_REGRESSION will appear automatically when TZ_FRONTEND_ACCEPTANCE lands.
- **UX**:
  - Overview: drill-down по основным сущностям (features → waves → packets), Workers всегда видно, Blocked когда есть
  - Каждая сущность показывает свой slug рядом с ID
  - Packet detail: 2 columns (main + sticky sidebar) ≥1100px, Blocking decision приклеен справа
- **Test results**: `pytest tests/grace_control/ -q` → 482 passed / 24 pre-existing failed (matches baseline, zero regressions).

---

## Открытые вопросы (закрыто)

| # | Вопрос | Решение |
|---|--------|---------|
| 1 | Frontend render approach? | **Vanilla JS SPA, hash routing** |
| 2 | Real-time updates? | **Polling 5s** |
| 3 | Raw JSONL log access? | **JSONL tail через endpoint** |
| 4 | Mount path? | **`/admin` + `/api/admin/*`** |
| 5 | Mobile variant? | **Responsive single HTML, breakpoints 900/600** |
| 6 | Throw away current admin? | **Да, полный cutover** |
| 7 | Read-only или с controls? | **Read-only v1, controls как 501 stubs** |
| 8 | Account for TZ_SESSION_RESUME? | **Forward-compat с проверкой таблицы** |
| 9 | Account for TZ_FRONTEND_ACCEPTANCE? | **Forward-compat, стадии появляются автоматически** |
| 10 | Storage model/prompt/command? | **Колонки в PacketRun** |
| 11 | Elapsed time update? | **На каждом poll (5s)** |
| 12 | Failure view content? | **command + stderr tail в Blocking decision** |
| 13 | Timestamp format? | **24h везде (HH:MM:SS[.mmm])** |
| 14 | Artifact sizes? | **Байты от сервера, fmtSize на клиенте** |
| 15 | Smart artifact rendering? | **Image=always inline, text<1MB, binary<256KB hex** |

---

## P3 — HTMX refactor + calm UI + GRACE pipeline (2026-06-07)

**Why:** vanilla SPA admin (`admin.js` ~720 строк hash routing + fetch + ручная DOM-конструкция + ручной polling) оказался overengineered. HTMX даёт server-rendered HTML с минимальным JS, естественным browser back/forward, и progressive enhancement (работает без JS).

**Срез:** frontend полностью переписан с vanilla SPA на HTMX + server-rendered partials. Backend (read endpoints, aggregation service) остаётся как есть. Новая data shape: derived `ui_state` / `state_severity` / `stage` / `duration_seconds` / `started_at` / `display_title`.

### 3.1 Архитектурные решения HTMX

| # | Решение | Значение |
|---|---------|----------|
| 20 | Frontend | **HTMX** (`htmx.org` 1.9+), **без** билд-шага, **без** npm, **без** React, **без** SPA routing |
| 21 | Server-rendered | Jinja2 templates + FastAPI endpoints возвращают HTML partials |
| 22 | Navigation | `<a href>` fallback + `hx-get` для HTMX. URL всегда `/admin?feature_id=…&wave_id=…&packet_id=…&filter=…&tab=…` |
| 23 | HTMX swap | `hx-swap="outerHTML"`. Каждый partial возвращает **свой корневой wrapper** (чтобы outerHTML swap не ломал grid context) |
| 24 | `hx-push-url` | **всегда** указывает на shell URL (`/admin?…`), **никогда** на `/admin/_partial/…` |
| 25 | Polling | `hx-trigger="load, every 5s"` на `_stats.html` (только stats bar) — остальное не poll'ится |
| 26 | Server | расширяем существующий FastAPI, новый роутер `/admin/_partial/…` (HTML partials) |
| 27 | Layout | **3-col при ≥1440px** (master / timeline / detail), **2-col при ≥1100px** (master / detail, timeline tab'ом), **1-col при ≤768px** (стекается, mobile-friendly) |
| 28 | Click routing | URL-state driven: feature_id + wave_id + packet_id в query string → back/forward работает из коробки |
| 29 | Display layer | **5 levels of severity** (CSS tokens): `ok` / `ok-soft` / `muted` / `attention` / `critical` (бэкенд state strings не меняются) |
| 30 | Calm UI | **No raw state pills** в master pane — только severity dot + meta `N waves · M packets · K needs attention` |
| 31 | Status never color-only | каждый badge имеет **text + title tooltip** (a11y + скриншот-тестируемость) |
| 32 | 24h time | `HH:MM:SS` (`fmt_time_short`), `HH:MM:SS.mmm` (`fmt_time_ms`), duration `"2m 16s"` (`fmt_duration`) |
| 33 | Sizes | `fmtSize()` — B/KB/MB/GB smart unit |
| 34 | Forward-compat | TZ_SESSION_RESUME, TZ_FRONTEND_ACCEPTANCE — Evidence/Sessions tabs уже описаны в P0 |

### 3.2 Display layer (`admin_template_filters.py`)

| Filter | Возвращает | Используется для |
|--------|------------|------------------|
| `ui_state(raw_state)` | enum: `READY / RUNNING / PASSED / FAILED / BLOCKED / ATTENTION / IDLE` | все badge'ы и pill'ы |
| `state_label(ui_state)` | человекочитаемый: `"Running"`, `"Reviewer rejected"`, `"Idle"` | текст badge'а |
| `state_severity(ui_state)` | `ok / ok-soft / muted / attention / critical` | CSS class на badge + border-left |
| `is_attention(ui_state)` | `bool` | фильтр `attention`, meta-счётчики, лейблы в detail |
| `raw_state(...)` | строка | маленький metadata блок в detail-pane (raw: rejected) |
| `fmt_duration(seconds)` | `"2m 16s"` / `"1h 5m"` / `"58s"` | duration cell в packet card |
| `fmt_time_short(iso)` | `"07:01:44"` | started cell в packet card |
| `safe_str(s)` | `""` для None | защита от `None.title` |
| `display_title(title, kind)` | `{title, is_placeholder, original, kind}` | **fallback для short/technical titles** — `"t"` → `Untitled feature`, original хранится как slug |
| `shell_url(feature_id, wave_id, packet_id, tab, filter, search, expanded_features, expanded_waves)` | `"/admin?feature_id=…&wave_id=…"` | **Jinja global** — единая точка построения shell URL |
| `ui_tab_label(tab_key)` | `"Spec"`, `"Attempts"`, `"Agent sessions"`, `"Evidence"`, `"Logs"`, `"Artifacts"`, `"Events"` | human-friendly tab labels |

**Mapping table (raw → ui_state):**

| Raw state | UI state | Severity | Label |
|-----------|----------|----------|-------|
| `draft` | `IDLE` | `muted` | `Idle` |
| `not_started` | `IDLE` | `muted` | `Not started` |
| `ready` | `READY` | `ok-soft` | `Ready` |
| `claimed` | `RUNNING` | `attention` | `Claimed` |
| `running` | `RUNNING` | `attention` | `Running` |
| `accepted` | `PASSED` | `ok` | `Accepted` |
| `merged` | `PASSED` | `ok` | `Merged` |
| `rejected` | `FAILED` | `critical` | `Reviewer rejected` |
| `failed` | `FAILED` | `critical` | `Failed` |
| `blocked` | `BLOCKED` | `critical` | `Blocked` |
| `blocked_recoverable` | `BLOCKED` | `attention` | `Blocked (recoverable)` |
| `blocked_final` | `BLOCKED` | `critical` | `Blocked (final)` |
| `degraded` | `ATTENTION` | `attention` | `Degraded` |

### 3.3 GRACE pipeline view

**9 stages** (расположены в порядке выполнения):

| # | Stage | Откуда данные |
|---|-------|---------------|
| 1 | `Materialized` | packet существует в DB |
| 2 | `Executor selected` | `claim` event (executor/worker picked) |
| 3 | `Coder run` | last PacketRun.status (running/done/failed) |
| 4 | `T0 — Scope & lint` | `evidence.stages[T0_SCOPE_AND_LINT]` (NORMAL profile: skipped) |
| 5 | `T1 — Targeted tests` | `evidence.stages[T1_TARGETED_TESTS]` (NORMAL: skipped) |
| 6 | `T2 — Full tests` | `evidence.stages[T2_FULL_TESTS]` (NORMAL: skipped) |
| 7 | `Evidence verifier` | `verifier:applied` event с `verdict: pass` |
| 8 | `Reviewer gate` | `release:accepted` (PASS) или `release:rejected` (FAIL с reason) |
| 9 | `Merge` | `merge:done` event |

**Status per stage:** `done / running / failed / skipped / pending` (определяется по derived logic).

**Service helper:** `_derive_pipeline(packet_id, db) → List[Stage]`

| Helper | Возвращает |
|--------|------------|
| `_stage_coder_run(pkt, last_run)` | `{key, label, status, meta}` |
| `_stage_acceptance(pkt, acceptance_report, profile)` | T0/T1/T2 stages с учётом профиля |
| `_stage_verifier(events)` | verifier stage |
| `_stage_reviewer(events, last_run)` | reviewer gate (PASS/FAIL/SKIP) |
| `_stage_merge(events, packet)` | merge stage |

**UI:** `.pipeline-view` — CSS grid `repeat(auto-fit, minmax(180px, 1fr))`, каждый stage = `.stage.stage-{status}` card с label + status text + duration.

**Pipeline clicked → switches active tab** (e.g. click `T1 — Targeted tests` → Evidence tab).

### 3.4 Layout density & fallback titles

**`display_title(title, kind)` filter** — placeholder detection:

```python
_PLACEHOLDER_TITLES = {"t", "d", "w1", "p1", "p2", "w3", "foo", "bar", "baz", "abc", "test"}
_PLACEHOLDER_RE = re.compile(r"^[a-z]?\d{0,2}$|^[a-z]{1,2}$")

def _is_placeholder(title: str) -> bool:
    if not title or len(title) < 3: return True
    if title.lower() in _PLACEHOLDER_TITLES: return True
    if _PLACEHOLDER_RE.match(title.lower()): return True
    return False
```

**Если placeholder:** возвращает `{title: "Untitled feature", is_placeholder: True, original: "t", kind: "feature"}`. Original сохраняется в `slug: t` метаданных.

**Packet stage derivation** (`_derive_packet_stage`):

| State | Last run | Stage |
|-------|----------|-------|
| `draft` / `not_started` | — | `materialized` |
| `claimed` / `running` | running | `coder` |
| `accepted` | passed | `verifier` |
| `merged` | — | `merge` |
| `rejected` / `failed` | failed | `reviewer` |
| `blocked` | — | `reviewer` |

**Packet card grid (4 cells):**

```
attempts: 3/3      | stage: Reviewer gate
started: 07:01:44  | duration: 1m 03s
```

**Wave details section** (правая колонка при `selected_wave_id`):

| Section | Content |
|---------|---------|
| Header | `Selected wave` label + title (fallback) + Wave #N + status badge + raw state + slug |
| Summary | 5 cells: total / rejected-failed / running / blocked / done |
| Wave progress | 4 stage rows: Materialized / Coder run / Reviewer gate / Merge — `reached/total` + horizontal bar (`width: %`) + severity (ok/attention/muted) |
| Packets in this wave | extended cards (4-cell grid + status badge) |

### 3.5 File layout (после HTMX refactor)

```
src/grace_control/ui/
├── templates/
│   └── admin/
│       ├── console.html          # shell page (3-pane grid)
│       ├── _master.html          # master tree (left column)
│       ├── _timeline.html        # feature timeline (middle column)
│       ├── _detail.html          # detail pane (right column)
│       ├── _tab.html             # tab body
│       └── _stats.html           # stats bar (polled)
└── static/
    └── admin.css                 # ~1500 строк: tokens, severity, pipeline, layout, responsive
```

### 3.6 HTMX partial contract

| Endpoint | Возвращает | Wrapper class | Container (in shell) |
|----------|------------|---------------|---------------------|
| `GET /admin/_partial/master?feature_id=…&filter=…&search=…` | HTML partial | `.master-tree` (`id="master-tree"`) | `#master-pane` (mounted in shell) |
| `GET /admin/_partial/timeline?feature_id=…&filter=…&search=…` | HTML partial | `.console-middle` (`id="timeline-pane"`) | `#timeline-pane` |
| `GET /admin/_partial/detail?feature_id=…&wave_id=…&packet_id=…` | HTML partial | `.console-detail` (`id="detail-pane"`) | `#detail-pane` |
| `GET /admin/_partial/tab?packet_id=…&tab=…` | HTML partial | `#packet-tab-content` | `#packet-tab-content` |
| `GET /admin/_partial/stats` | HTML partial | `#stats-bar-container` | `#stats-bar-container` (`hx-trigger="load, every 5s"`) |

**Правило:** partial = его собственный корневой wrapper, swap = `outerHTML` заменяет на этот же wrapper (grid context сохраняется).

### 3.7 URL state model

| Param | Scope | Set by | Notes |
|-------|-------|--------|-------|
| `feature_id` | always | master click, header, "back to features" | Обязателен для non-empty view |
| `wave_id` | optional | wave card click | опускается в URL когда `packet_id` установлен (packet_id = "the only packet matters") |
| `packet_id` | optional | packet card click, breadcrumb | при установке wave_id опускается |
| `filter` | optional | filter chips (`all` / `attention` / `running` / `failed` / `passed`) | default: `all` |
| `search` | optional | search box | substring filter по title/slug/id |
| `tab` | optional | tab click, pipeline stage click | `events` (default) / `spec` / `attempts` / `sessions` / `evidence` / `logs` / `artifacts` |
| `expanded_features` | optional | master tree expansion | comma-separated feature ids |
| `expanded_waves` | optional | master tree expansion | comma-separated wave ids |

**`shell_url(feature_id, wave_id, packet_id, tab, filter, search, expanded_features, expanded_waves)`** — Jinja global, единственный способ построить URL.

**Pre-computed `click_url`** — каждый feature/wave/packet/tab/chip имеет `click_url` в Python DTO (не в Jinja — Jinja list comprehension не поддерживается).

### 3.8 Click bubbling fix (wave/packet cards)

**Проблема:** клик на packet row внутри wave card бабблит на parent `<a>` или `<div hx-get>`, открывая wave details вместо packet details.

**Решение:**
- Wave = `<div class="ft-wave" hx-get="…wave_id=…">`
- Packet внутри wave = `<div class="ft-pkt" hx-on:click="event.stopPropagation()" hx-get="…packet_id=…">`
- Аналогично для master tree (`.tn-packet` stopPropagation, `.tn-wave-head` отдельно hx-get)

`<a>` внутри `<a>` — invalid HTML → используем `<div>` + `event.stopPropagation()`.

### 3.9 CSS severity tokens

```css
--sev-ok: #2da44e;
--sev-ok-soft: #9bc4a4;
--sev-muted: #8b949e;
--sev-attn: #d29922;
--sev-attn-soft: #d2a36b;
--sev-crit: #cf222e;
--sev-crit-soft: #d97780;
--sev-crit-bg: rgba(207, 34, 46, 0.08);
--sev-attn-bg: rgba(210, 153, 34, 0.10);
```

**Применение:**
- `.severity-{ok,ok-soft,muted,attn,attn-soft,crit}` → `border-left: 3px solid var(--sev-*)` + background tint
- `.badge.severity-*` → цвет текста
- `.stage.stage-{done,failed,running,skipped,pending}` → pipeline stage colors

### 3.10 Tab labels (P3)

| Tab key | Label | Tab key | Label |
|---------|-------|---------|-------|
| `events` | Events | `evidence` | Evidence |
| `spec` | Spec | `logs` | Logs |
| `attempts` | Attempts | `artifacts` | Artifacts |
| `sessions` | Agent sessions | | |

`ui_tab_label()` Jinja filter — единая точка перевода.

### 3.11 Acceptance summary (2026-06-07, P3)

- **HTMX контракт**: все partials self-wrapping; `hx-swap="outerHTML"` сохраняет grid context
- **Shell URL**: `shell_url()` Jinja global, pre-computed `click_url` per object
- **Calm UI**: 5 severity levels (CSS tokens), `ui_state/state_label/state_severity/is_attention` filters
- **GRACE pipeline view**: 9 stages derived from events + evidence + acceptance, CSS grid
- **Feature → Wave → Packet navigation**: URL state, wave details mode, click bubbling fix
- **Layout density**: `display_title` filter (placeholder fallback), packet grid (4 cells), wave progress (4 bars)
- **CSS**: ~1500 строк; responsive breakpoints 1440 / 1100 / 768 / 390
- **Templates**:
  - `console.html` — shell
  - `_master.html` — master tree с `display_title` fallback
  - `_timeline.html` — feature banner + structured wave/packet cards
  - `_detail.html` — wave details (header + summary + progress + packet list) + packet details (header + meta + pipeline + tabs)
  - `_tab.html` — tab body
  - `_stats.html` — stats bar (polled 5s)
- **Tests** (40+ новых):
  - `tests/ui/test_admin_ui_htmx_layout.py` — 9 тестов
  - `tests/ui/test_admin_ui_calm_display.py` — 14 тестов
  - `tests/ui/test_admin_ui_wave_selection.py` — 14 тестов
  - `tests/ui/test_admin_ui_layout_density.py` — 17 тестов
  - `tests/grace_control/services/test_admin_aggregation_service.py` — 44 теста (+3 wave_detail)
- **Test results**: `pytest tests/grace_control/ tests/ui -q` → **546 passed / 25 pre-existing failed** (без регрессий)

### 3.12 Operator UX fixes (по feedback, P3)

| # | Feedback | Fix |
|---|----------|-----|
| 1 | "Сейчас потерял смысловой слой пайплайна. Он показывает технические transition-события" | Новый **GRACE pipeline view** (9 семантических стадий) вместо сырых event'ов в packet detail header |
| 2 | "Операторский pipeline: что именно делал GRACE, кто работал, сколько заняло" | Pipeline view с executor, model, duration per stage |
| 3 | "Табы timeline / spec / runs … по факту не работают" | Tab state в URL + partial contract; tabs работают при любом packet click |
| 4 | "Tabs must never push /admin/_partial/tab?… as the visible URL" | `hx-push-url` указывает на shell URL, не на partial URL |
| 5 | "t / d / 1 wave · 1 packet" — placeholder titles | `display_title` filter: "Untitled feature", original в slug |
| 6 | "Структура появилась, а 'карточки работы' ещё выглядят как сырые строки из БД" | Structured `.ft-wave-*` / `.ft-pkt-grid` rows вместо flat string concatenation |
| 7 | "Синее выделение верхнего блока непонятно" | `Selected feature` явный label |
| 8 | "Справа при выборе волны слишком пусто" | Wave details с Summary (5 cells) + Wave progress (4 bars) + extended packet list |
| 9 | "Сделать fallback labels" | `display_title` filter с kind-specific fallback ("Untitled feature" / "Untitled wave" / "Untitled packet") |
| 10 | "T0/T1/T2 stages отсутствуют для NORMAL профиля" | Stages **всегда** shown, помечены `skipped` для NORMAL |
