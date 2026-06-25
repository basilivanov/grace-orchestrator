# ТЗ: GRACE Mission Control — Pipeline Observability v2

**Документ:** Техническое задание на доработку админ-панели grace-orchestrator
**Версия:** Draft v1.0
**Дата:** 2026-06-25
**Заказчик:** basilivanov
**Репозиторий:** https://github.com/basilivanov/grace-orchestrator

---

## Содержание

1. [История документа и контекст](#1-история-документа-и-контекст)
2. [Цели и не-цели](#2-цели-и-не-цели)
3. [Стек технологий (не меняем)](#3-стек-технологий-не-меняем)
4. [Глоссарий стадий пайплайна](#4-глоссарий-стадий-пайплайна)
5. [Существующее состояние админки](#5-существующее-состояние-админки)
6. [Архитектурные решения](#6-архитектурные-решения)
7. [Схема данных — изменения](#7-схема-данных--изменения)
8. [Сбор данных о стадиях (instrumentation)](#8-сбор-данных-о-стадиях-instrumentation)
9. [API endpoints — новые и изменяемые](#9-api-endpoints--новые-и-изменяемые)
10. [WebSocket события — расширение](#10-websocket-события--расширение)
11. [UI: Главный экран — Feature Pipeline Gantt](#11-ui-главный-экран--feature-pipeline-gantt)
12. [UI: Детализация пакета — Stage Timeline](#12-ui-детализация-пакета--stage-timeline)
13. [UI: Агрегированные логи](#13-ui-агрегированные-логи)
14. [UI: Артефакты по стадиям](#14-ui-артефакты-по-стадиям)
15. [UI: Метрики P50/P95](#15-ui-метрики-p50p95)
16. [UI: Контрольные действия](#16-ui-контрольные-действия)
17. [UI: Recovery chain visualization](#17-ui-recovery-chain-visualization)
18. [UI: Workers и Supervisor](#18-ui-workers-и-supervisor)
19. [Mobile layout](#19-mobile-layout)
20. [Тесты](#20-тесты)
21. [План реализации — эпики](#21-план-реализации--эпики)
22. [Риски и открытые вопросы](#22-риски-и-открытые-вопросы)
23. [Приложения](#23-приложения)

---

## 1. История документа и контекст

Этот документ описывает следующий шаг развития операторской консоли (админки) оркестратора `grace-orchestrator`. Он не отменяет предыдущие ТЗ, а надстраивается над ними: предыдущие документы фиксируют информационную модель, навигацию и базовый набор вкладок для пакета. Это ТЗ фокусируется на одном конкретном пробеле — сквозной наблюдаемости пайплайна стадий от `context-builder` до `merge`, с реальными таймингами, агрегированными логами, артефактами по стадиям и контрольными действиями.

### 1.1. Предшествующие документы

В репозитории уже есть несколько ТЗ и task-тикетов, связанных с админкой. Это ТЗ опирается на их решения и не повторяет их. Перед началом работ рекомендуется перечитать следующие файлы:

| Документ | Статус | Что фиксирует |
|---|---|---|
| `TZ_MISSION_CONTROL.md` | Concept | High-level миссия админки: drill-down от features к packets, обзор проблемных мест, mobile layout. Определяет базовый набор вкладок Overview/Runs/Artifacts/Events/Spec. |
| `docs/TZ_ADMIN_PANEL.md` | Implemented ✓ | Реализованная Admin Panel v2: HTMX SPA на `/admin`, JSON API на `/api/admin/*`, таблицы `PacketRun` с `model`/`command_preview`/`prompt`, blocking decision view, planned control stubs (501). |
| `docs/work/TZ_ADMIN_UI_PIPELINE_STAGE_CARDS_NOT_LOG.md` | Implemented ✓ | Stage cards вместо log-стрим в pipeline view. Карточки стадий с цветовой кодировкой по статусу. |
| `docs/work/TZ_ADMIN_UI_PIPELINE_WIDE_STACKED_CARDS.md` | Implemented ✓ | Wide stacked cards layout для pipeline. Вертикальный стек карточек стадий во всю ширину панели. |
| `docs/work/TZ_ADMIN_UI_PIPELINE_STAGE_BLOCKS_FINAL.md` | Implemented ✓ | Финальный layout stage blocks. Текущий вид пайплайна в продакшене. |
| `docs/work/TZ_ADMIN_UI_VERTICAL_PIPELINE_TIMELINE.md` | Implemented ✓ | Вертикальный timeline для пакета с timeline-точками по стадиям. |
| `docs/work/TZ_ADMIN_UI_PACKET_VISIBILITY_AND_TIMING.md` | Implemented ✓ | Видимость packet timing — `started_at`, elapsed для running пакетов, 24h timestamps. |
| `docs/TZ_FRONTEND_ACCEPTANCE.md` | Implemented ✓ | Frontend acceptance tests для админки: JS syntax check, HTML template smoke, API contract, Playwright, mobile viewports. |

### 1.2. Что уже реализовано

На момент написания этого ТЗ в админке уже есть:

- Server-rendered HTMX-консоль на `/admin` с master–detail layout (features tree слева, timeline + detail справа).
- JSON API на `/api/admin/*` с endpoints `overview` / `features` / `packet detail` / `timeline` / `runs` / `sessions` / `evidence` / `artifacts` / `logs` / `search` / `system`.
- Polling 5s через HTMX `hx-trigger`.
- WebSocket на `/ws`, который бродкастит `recovery_update` и `state_change` события.
- Восемь вкладок в packet detail — `timeline`/`spec`/`runs`/`sessions`/`evidence`/`logs`/`artifacts`/`diagnostics`.
- Таблица `FeaturePlanningRun` с метриками по planning stages.
- Таблица `AgentSession` с историей сессий агента.
- Метод `_derive_pipeline()` в `AdminAggregationService`, который возвращает структуру стадий с timing-данными.

### 1.3. Какие пробелы закрывает это ТЗ

Несмотря на существующую реализацию, оператор не может ответить на ключевые вопросы просто посмотрев на админку. Это ТЗ закрывает следующие пробелы:

- **Сколько времени идёт каждая стадия пакета прямо сейчас?** Сейчас оператор видит только elapsed для всего пакета, но не для отдельных стадий `context-builder`/`architect`/`coder`/`verifier`/`reviewer`.
- **Как выглядит пайплайн пакета как timeline, а не как набор карточек?** Сейчас стадии показываются как stage cards без временной оси — непонятно, что шло параллельно, что долго, что вернулось.
- **Что произошло в логах всех подсистем по конкретному пакету?** Сейчас логи — это только `stderr` воркера. Нет серверных логов, supervisor-а, agent runtime JSONL, recovery controller-а, склеенных по `trace_id`.
- **Какие артефакты у каждой стадии?** Сейчас `artifacts` — это дерево `evidence_dir` без группировки по стадии. Непонятно, какой файл от `context-builder`-а, какой от `verifier`-а.
- **Почему пакет вернулся с verifier в coder и сколько попыток было?** Сейчас возвраты видны только как event в timeline. Нет явной визуализации loop-ов и причин recovery-decision-ов.
- **Какие типичные тайминги у verifier-а за неделю?** Нет метрик P50/P95 по типам стадий — нельзя понять, является ли текущий прогон аномальным.
- **Можно ли остановить зависший worker или перезапустить только verifier?** Сейчас все control endpoints возвращают 501 (planned stubs).

> **Принцип:** это ТЗ не переписывает админку с нуля. Оно добавляет новую секцию `Pipeline` в packet detail, новый экран Feature Gantt, новую вкладку Aggregated Logs, новый экран Metrics, и реализует контрольные endpoints. Существующие вкладки и layouts остаются как есть.

---

## 2. Цели и не-цели

### 2.1. Цели

После реализации ТЗ оператор оркестратора должен уметь следующее — без обращения к лог-файлам на сервере, без SQL-запросов к БД, без чтения исходного кода:

- **G1. Видеть реальный pipeline пакета.** Открыть packet detail и увидеть горизонтальный timeline с барами всех стадий — `context-builder`, `architect`, `materialize`, `coder`, `T0`, `T1`, `T2`, `verifier`, `reviewer`, `merge` — на единой оси времени с 24h timestamps. Running стадия подсвечена, finished — серая с длительностью, failed — красная.
- **G2. Видеть время каждой стадии.** Для каждой стадии видеть `started_at`, `finished_at`, `duration` (HH:MM:SS), и для running стадии — elapsed с автообновлением через WebSocket. Для сравнения — рядом P50 этого типа стадии за последние 24 часа.
- **G3. Видеть возвраты между стадиями.** Если пакет вернулся с verifier в coder или с reviewer в architect — видеть явную стрелку назад с подписью причины (например, «evidence missing T1») и round-номером попытки. Recovery chain вынесен в отдельную секцию с таблицей всех recovery decisions.
- **G4. Видеть агрегированные логи.** Во вкладке Aggregated Logs видеть единый scroll-поток из семи источников: server (FastAPI/uvicorn), supervisor (process_supervisor), worker stdout, worker stderr, agent runtime (JSONL из opencode), recovery controller, DB events. Склеенные по `trace_id`, с фильтрами по source/level/regex и real-time режимом через WebSocket.
- **G5. Видеть артефакты по стадиям.** Во вкладке Artifacts файлы сгруппированы по стадии, которая их произвела. Клик по файлу — smart rendering: image inline, text <1MB в `<pre>`, binary <256KB hex preview, иначе Download. Рядом — ссылка на логи стадии.
- **G6. Видеть метрики по типам стадий.** На отдельном экране Metrics — P50/P95/avg/max/count по каждому `stage_key` за период 24h/7d/30d, гистограмма распределения, тренд-линия, avg tokens/cost per stage, idle/wait time (claim→start), success rate, heatmap stage × hour для поиска bottleneck-ов.
- **G7. Управлять процессом.** Кнопки Retry (для BLOCKED_RECOVERABLE), Cancel (для running), Stop worker (для зависших), Re-run stage (только verifier/reviewer для дебага), Dev-replay (воспроизвести стадию по trace_id). Каждое действие — с confirm dialog и audit log.
- **G8. Видеть Overview Gantt для фичи.** На главном экране для выбранной фичи видеть Gantt-таймлайн всех её пакетов и стадий. Zoom 1h/6h/24h/7d. Один взгляд — какая часть фичи сейчас активна, что долго, что вернулось.

### 2.2. Не-цели

Чтобы сохранить scope и не превратить доработку в переписывание системы, следующее явно исключено из этого ТЗ:

- **✗ Не меняем стек технологий.** FastAPI + Jinja2 + HTMX + vanilla JS + SQLite/SQLAlchemy + WebSocket остаются. Никаких React/Vue/Svelte, никакого npm/build-шага, никакого TypeScript.
- **✗ Не переписываем существующую админку.** Текущие вкладки `timeline`/`spec`/`runs`/`sessions`/`evidence`/`logs`/`artifacts`/`diagnostics` остаются как есть. Новые секции добавляются рядом, не заменяют.
- **✗ Не меняем state machine пакета.** 10 состояний (`DRAFT`/`READY`/`RUNNING`/`ACCEPTED`/`MERGED`/`REJECTED`/`BLOCKED`/`FAILED`/`CANCELLED`/`BLOCKED_RECOVERABLE`/`BLOCKED_FINAL`) и переходы между ними остаются. Контрольные действия используют существующие transitions.
- **✗ Не трогаем существующие API endpoints.** Все текущие `/api/admin/*` endpoints остаются с теми же сигнатурами. Новые добавляются, существующие не ломаются.
- **✗ Не меняем формат EXECUTION_PACKET и GRACE methodology.** Канон, методология, формат пакетов — за пределами этого ТЗ.
- **✗ Не делаем multi-tenant / RBAC.** Auth остаётся на текущем `AuthMiddleware` (localhost bypass). Роли и права — отдельное ТЗ.
- **✗ Не делаем alerting / notifications.** Уведомления в Telegram/email/Slack — отдельное ТЗ. Здесь только отображение.
- **✗ Не делаем ML-аномалии.** Метрики P50/P95 — это базовая статистика. ML-поиск аномалий — за пределами этого ТЗ.

---

## 3. Стек технологий (не меняем)

Этот раздел фиксирует стек, в котором должна быть реализована доработка. Стек взят из `pyproject.toml`, `docker/requirements.txt` и существующего кода админки. Любое отклонение от стека требует отдельного согласования с заказчиком.

### 3.1. Backend

| Компонент | Технология | Версия | Где используется |
|---|---|---|---|
| Web framework | FastAPI | ≥0.110 | Все API роутеры в `src/grace_control/api/routers/` |
| ASGI server | Uvicorn | ≥0.30 | `scripts/run_api.py`, `deploy/grace-orchestrator.service` |
| Шаблонизатор | Jinja2 | via FastAPI | `src/grace_control/ui/templates/admin/` |
| ORM | SQLAlchemy 2.x | ≥2.0 | `src/grace_control/db/schema.py` |
| БД (default) | SQLite | 3.x | через `grace_control/db/__init__.py:get_db` |
| БД (опционально) | PostgreSQL | ≥14 | через `DATABASE_URL` env (задел в `schema.py`) |
| Валидация | Pydantic v2 | ≥2.7 | контракты в `adapters/`, `core/` |
| WebSocket | FastAPI WebSocket | — | `src/grace_control/api/routers/ws.py` + `ws_broadcast.py` |
| YAML | PyYAML | ≥6.0 | fixtures/, scenarios, EXECUTION_PACKET |
| LLM SDK | anthropic | ≥0.18 | `src/grace_control/core/llm_runner.py` |
| Python | CPython | ≥3.11 | `requires-python` в `pyproject.toml` |

### 3.2. Frontend

| Компонент | Технология | Где |
|---|---|---|
| HTML рендеринг | Jinja2 server-side | `src/grace_control/ui/templates/admin/*.html` |
| Interactivity | HTMX 1.x (через CDN) | `hx-get` / `hx-post` / `hx-trigger` на partials |
| JavaScript | Vanilla JS (без сборки) | `src/grace_control/ui/static/admin.js` + встроенные `<script>` |
| CSS | Ванильный CSS, без Tailwind | `src/grace_control/ui/static/css/*.css` |
| Иконки | Inline SVG / emoji | — |
| Шрифты | System fonts + Noto Sans для CJK fallback | — |
| Realtime | Native WebSocket API | `ws.py` → `ws_broadcast.handle_websocket` |
| Polling fallback | HTMX `hx-trigger=every 5s` | stats / master / detail partials |

> Ключевое ограничение: **запрещено** добавлять любые npm-зависимости, build-шаги (webpack/vite/rollup), CSS-препроцессоры (SASS/LESS), TypeScript, JSX. Весь новый фронтенд-код — это Jinja2-шаблоны, vanilla JS в `<script>` или в отдельных `.js`-файлах под `static/`, и vanilla CSS. Это позволяет деплоить админку как часть Python-пакета без отдельного CI для фронтенда.

### 3.3. Realtime и polling

В админке уже есть два канала обновлений: WebSocket `/ws` для push-событий (`state_change`, `recovery_update`) и HTMX polling для partial-обновлений (`hx-trigger=every 5s` на stats/master/timeline). Это ТЗ расширяет оба канала: WebSocket получает новые event types для stage updates и log streaming, polling остаётся как fallback для клиентов с неработающим WS. Никаких SSE и long-polling не добавляется — это усложнило бы стек без выигрыша.

---

## 4. Глоссарий стадий пайплайна

Pipeline пакета в оркестраторе состоит из последовательности стадий. Этот раздел фиксирует канонический список стадий, их ключи в коде, что они делают, какие артефакты производят, где хранится состояние, и какие переходы возможны. Все визуализации в этом ТЗ (Gantt, Stage Timeline, Recovery Chain, Metrics) оперируют именно этим набором стадий.

### 4.1. Канонический список стадий

| # | Stage key | Label | Что делает | Артефакты | Где state |
|---|---|---|---|---|---|
| 1 | `context_builder` | Context Builder | Stage 0. Собирает контекст для архитектора: читает CANON, существующие срезы кода, графи зависимостей, спецификацию фичи. Готовит workspace для architect. | `context_bundle.json`, `scope_manifest.json` | `FeaturePlanningRun(stage='context_builder')` |
| 2 | `architect` | Architect | Запускает LLM-агента для генерации плана: декомпозиция фичи на волны, волны на пакеты, спецификация каждого пакета. Использует `architect_prompt.md`. | `plan.json` (волны + пакеты), `EXECUTION_PACKET.md` для каждого пакета | `FeaturePlanningRun(stage='architect')` |
| 3 | `materialize` | Materialize | Материализует планы архитектора в БД: создаёт `Wave` и `Packet` строки, записывает `spec_json`. С этого момента пакеты готовы к исполнению. | — (только DB записи) | `FeaturePlanningRun(stage='materialize')` + `Packet.created_at` |
| 4 | `executor` | Executor (claim) | Worker забирает пакет из очереди (claim + lease fencing). Резолвится executor по `executor_selector`. Создаётся `PacketRun`. | lease row, `PacketRun` row | `PacketRun.started_at`, `Lease` table |
| 5 | `coder` | Coder | Основная стадия исполнения. Запускает opencode/agent runtime с `coder_prompt.md`. Агент читает EXECUTION_PACKET, делает изменения в worktree, коммитит. | `stdout.log`, `stderr.log`, `agent.jsonl` (JSONL events), git diff, commit | `PacketRun` (duration_ms, model, command_preview, prompt), `AgentSession(role='coder')` |
| 6 | `t0_scope_lint` | T0 Scope & Lint | Acceptor стадия T0: проверка scope (что изменения только в разрешённых файлах) + линтер (eslint, ruff, mypy). NORMAL profile — встроена в coder, STRICT — отдельный прогон. | `scope_violations.json`, `lint_report.json` | `Event(event_type='acceptance_stage')`, `result_json.stages[T0_SCOPE_AND_LINT]` |
| 7 | `t1_unit_tests` | T1 Unit Tests | Acceptor стадия T1: targeted unit-тесты изменённых файлов. Запускает `npm test` / `pytest` для конкретных test-файлов. | `test_report.json` (passed/failed/skipped) | `result_json.stages[T1_UNIT_TESTS]` |
| 8 | `t2_e2e_smoke` | T2 E2E / Smoke | Acceptor стадия T2: smoke или e2e тесты. Playwright для фронтенда, API smoke для бэкенда. | `playwright_report.json`, screenshots | `result_json.stages[T2_E2E_OR_SMOKE]` |
| 9 | `t3_visual` (planned) | T3 Visual Regression | Планируемая стадия T3: визуальная регрессия через `visual_baseline_manager`. Сравнение скриншотов с baseline, `diff_pct`. | `visual_diff.png`, `baseline.json` | `result_json.stages[T3_VISUAL_REGRESSION]` (зарезервировано) |
| 10 | `verifier` | Evidence Verifier | STRICT profile: LLM-агент `verifier_prompt.md` проверяет evidence (логи, тесты, diff) на достаточность и корректность. Может вернуть в coder (evidence missing) или принять. | `verifier_decision.json` (verdict, blocking_issues) | `Event(event_type='verifier_*')`, `AgentSession(role='verifier')` |
| 11 | `reviewer` | Reviewer Gate | STRICT profile: LLM-агент `reviewer_prompt.md` проверяет безопасность изменений (self-improvement guard), соответствие канону, риски. Может вернуть в architect (scope drift) или принять. | `reviewer_decision.json` (verdict, risk_class, rollback_plan) | `Event(event_type='reviewer_*')`, `AgentSession(role='reviewer')` |
| 12 | `merge` | Merge | Финальная стадия: `MergeService.merge_packet`. Git merge worktree branch в main, push, обновление `Packet.state=MERGED`. Commit SHA сохраняется. | `merge_commit_sha`, git log | `Packet.state=merged`, `Event(event_type='packet_merged')` |

### 4.2. Возможные переходы (state machine стадий)

Стадии выполняются последовательно, но с возможными возвратами (loops) по решению verifier, reviewer или recovery_controller. Канонический flow:

```
context_builder → architect → materialize
  → executor → coder
    → t0_scope_lint → t1_unit_tests → t2_e2e_smoke (→ t3_visual)
      → verifier
        ↘ если FAIL → coder       (loop, round N+1, reason='evidence missing')
        ↘ если FAIL → architect   (loop, reason='scope impossible')
      → reviewer
        ↘ если FAIL → coder       (loop, reason='rework needed')
        ↘ если FAIL → architect   (loop, reason='scope drift')
        ↘ если FAIL → BLOCKED_FINAL (reason='unsafe self-improvement')
      → merge → MERGED
```

Возвраты — это не retry всего пакета, а целенаправленный возврат в конкретную стадию с сохранением контекста (`AgentSession.parent_session_id` для resume/fork). Каждый возврат увеличивает `loop_round` в `stage_runs` (см. §7) и логируется в `Event` table с `event_type` из `recovery_*` (см. `ws_broadcast.RECOVERY_EVENTS`).

### 4.3. Профили приёмки (acceptance_profile)

Состав стадий T0/T1/T2/T3 и запуск verifier/reviewer зависит от `acceptance_profile` пакета. Профиль хранится в `Packet.acceptance_profile` и определяет, какие стадии будут запущены:

| Профиль | T0 | T1 | T2 | T3 | Verifier | Reviewer | Когда |
|---|---|---|---|---|---|---|---|
| FAST | в coder | в coder | skip | skip | skip | skip | Тривиальные изменения, smoke-only |
| NORMAL | в coder | в coder | smoke | skip | skip | skip | Боевой режим по умолчанию |
| STRICT | отдельно | отдельно | e2e | opt | run | run | Self-improvement, risky changes |

Админка должна показывать профиль пакета в header-е и подсвечивать skipped стадии серым с пометкой «not in profile (NORMAL)», чтобы оператор не искал логи verifier-а там, где его не было.

---

## 5. Существующее состояние админки

Этот раздел описывает, что уже есть в админке на момент написания ТЗ. Цель — зафиксировать baseline, чтобы доработки не дублировали существующий функционал и могли опереться на уже существующие структуры данных.

### 5.1. Layout и навигация

Админка живёт на `/admin` и рендерится серверно через Jinja2. Layout — master–detail: слева дерево features → waves → packets (с возможностью expand/collapse), справа — детали выбранной сущности. На верхнем уровне — stats bar с counts по состояниям пакетов, health-индикатор, кнопка maintenance. Внутри packet detail — восемь вкладок: `timeline`/`spec`/`runs`/`sessions`/`evidence`/`logs`/`artifacts`/`diagnostics`. HTMX обновляет partials без полной перезагрузки страницы, URL синхронизируется через `hx-push-url`.

### 5.2. Существующие API endpoints (`/api/admin/*`)

Полный список реализованных endpoints, на которые опирается это ТЗ:

| Method | Path | Что возвращает | Статус |
|---|---|---|---|
| GET | `/api/admin/overview` | stats / health / recent_events / blocked / workers | ok |
| GET | `/api/admin/features` | features tree: features → waves → packets (с slug, state, attempt_count) | ok |
| GET | `/api/admin/packet/{id}/detail` | packet + worker + model + started/elapsed + recovery + runs + sessions + blocking + pipeline | ok |
| GET | `/api/admin/packet/{id}/blocking_decision` | has_blocking, decided_by, action, reason, last_failure с stderr tail | ok |
| GET | `/api/admin/packet/{id}/timeline` | events list (timestamp, event_type, component, reason, payload) | ok |
| GET | `/api/admin/packet/{id}/runs` | список PacketRun с run_id/number/worker/executor/model/status/duration | ok |
| GET | `/api/admin/packet/{id}/runs/{run_id}` | один run с result_json, command_preview, model, prompt, artifacts_summary | ok |
| GET | `/api/admin/packet/{id}/runs/{run_id}/evidence` | acceptance stages (T0/T1/T2 + planned T2_BROWSER/T3_VISUAL), verdict, screenshots | ok |
| GET | `/api/admin/packet/{id}/sessions` | agent_sessions chain (role, attempt, parent_session_id, status) | ok |
| GET | `/api/admin/packet/{id}/runs/{run_id}/artifacts` | tree файлов из evidence_dir с size и type | ok |
| GET | `/api/admin/packet/{id}/runs/{run_id}/artifacts/file` | содержимое файла (image/text/binary) с path-traversal защитой | ok |
| GET | `/api/admin/packet/{id}/runs/{run_id}/logs` | stderr/stdout/agent log lines с tail и regex-фильтром | ok |
| GET | `/api/admin/feature/{id}/summary` | feature + waves + packets | ok |
| GET | `/api/admin/search` | поиск packets/features по q | ok |
| GET | `/api/admin/system/health` | supervisor_alive / api_alive / workers_alive / db_ok / code_sha | ok |
| GET | `/api/admin/system/logs` | последние N строк из `/tmp/api*.log` (server logs) | ok |
| GET | `/api/admin/system/workers` | список workers с current_packet_id / last_heartbeat / started_at | ok |
| POST | `/api/admin/feature/{id}/archive` | archive feature | ok |
| POST | `/api/admin/feature/{id}/unarchive` | unarchive feature | ok |
| POST | `/api/admin/packet/{id}/resume` | PLANNED STUB → 501 | stub |
| POST | `/api/admin/packet/{id}/delete` | PLANNED STUB → 501 | stub |
| POST | `/api/admin/packet/{id}/stop` | PLANNED STUB → 501 | stub |

### 5.3. Существующая структура pipeline в API

Важное наблюдение: метод `AdminAggregationService._derive_pipeline()` уже возвращает структуру стадий с timing-данными в поле `packet.pipeline`. На вызов `GET /api/admin/packet/{id}/detail` ответ содержит:

```json
"pipeline": {
  "stages": [
    {"key":"context_builder","label":"Context Builder",
     "status":"done","started_at":"...","finished_at":"...",
     "duration_ms":1234,"meta":"","target_tab":"spec"},
    {"key":"architect","label":"Architect", ...},
    {"key":"materialized","label":"Materialize", ...},
    {"key":"executor","label":"Executor", ...},
    {"key":"coder_run","label":"Coder run", ...},
    {"key":"t0","label":"T0 scope/lint", ...},
    {"key":"t1","label":"T1 tests", ...},
    {"key":"t2","label":"T2 smoke/e2e", ...},
    {"key":"verifier","label":"Evidence verifier", ...},
    {"key":"reviewer","label":"Reviewer", ...},
    {"key":"merge","label":"Merge", ...}
  ],
  "has_started": true,
  "has_acceptance_data": true,
  "has_reviewer": false
}
```

Проблема: эти данные уже есть в API, но UI показывает их как стек карточек без временной оси. Это ТЗ меняет именно UI — переводит карточки в Gantt-таймлайн с реальной осью времени (см. §12). Данные в `_derive_pipeline` также расширяются: добавляются `loop_round`, `parent_stage_run_id`, `log_links`, `artifact_links`, `model`, `worker`, `tokens`, `cost` (см. §7, §8).

### 5.4. WebSocket — что уже бродкастится

В `src/grace_control/api/ws_broadcast.py` уже реализована базовая бродкаст-логика. Подписка — через `/ws`, без фильтрации на серверной стороне (клиент фильтрует сам). Сейчас бродкастятся:

- `state_change` — любое изменение `Packet.state` (через `broadcast_event`).
- `recovery_update` — любое событие из `RECOVERY_EVENTS` frozenset (`recovery_classified`, `recovery_decision_made`, `recovery_retry_same_coder`, `recovery_switch_coder`, `recovery_return_to_architect`, `recovery_escalate_architect`, `recovery_retry_verifier`, `recovery_retry_reviewer`, `recovery_retry_merge`, `recovery_block_feature`, `recovery_no_action`, `recovery_apply_failed`).
- `state_change` со `state='cancelled'` — через `broadcast_packet_cancel`.
- `state_change` со `state='merged'` — через `broadcast_packet_merge`.

Этого недостаточно для real-time обновления stage timeline: нет событий `stage_started` / `stage_finished` / `stage_log_line` / `stage_artifact_added` / `stage_returned`. Раздел §10 описывает расширение.

---

## 6. Архитектурные решения

Этот раздел фиксирует ключевые архитектурные решения и их обоснование. Каждое решение имеет номер, краткую формулировку, обоснование «почему так, а не иначе», и ссылку на разделы, где оно детализируется. Решения окончательные — изменение любого из них требует отдельного согласования.

| # | Решение | Обоснование | См. § |
|---|---|---|---|
| A1 | Pipeline визуализация = Gantt-таймлайн с горизонтальными барами по оси времени | Карточки стадий (текущий UI) не показывают параллельность и длительность. Gantt даёт одну картину «когда что началось и сколько длилось», легко видеть bottleneck-и и возвраты. Альтернатива — vertical swimlane (Kanban-style) — не показывает время. | §11, §12 |
| A2 | Агрегированные логи = склейка 7 источников с фильтром по `trace_id`, без новой БД-таблицы для логов | Логи уже пишутся в файлы (`api*.log`, worker stdout/stderr, agent JSONL). Создание таблицы `log_lines` в SQLite дало бы O(N) рост БД и плохо искалось. Склейка на лету из файлов с tail-limit + фильтр по trace_id — дёшево и достаточно для оператора. | §13 |
| A3 | Realtime = расширение существующего `/ws` новыми event types | WebSocket уже есть, инфраструктура бродкаста работает. SSE потребовал бы второго канала. Long-polling хуже по latency. Никаких новых транспортов не добавляем. | §10 |
| A4 | Контроль = реализация существующих 501-stub-ов + 3 новых endpoints | Endpoints resume/delete/stop уже спроектированы в `TZ_ADMIN_PANEL.md` и возвращают 501. Их нужно реализовать, а не плодить новые. Дополнительно — `rerun-stage`, `stop-worker`, `dev-replay` (последний уже есть как роутер, нужно выставить в UI). | §9, §16 |
| A5 | Метрики = материализация в таблицу `stage_metrics` с пересчётом по cron | Подсчёт P50/P95 на лету для 1000+ `stage_runs` — это O(N log N) при каждом запросе. Материализация раз в минуту/час даёт O(1) чтение и O(N) запись в фоне. SQLite это переварит. | §7, §15 |
| A6 | Возвраты = явные transitions со стрелкой назад + `loop_round` в `stage_runs` | Альтернатива — показывать возвраты как «Attempt 2» в runs. Но тогда теряется причинно-следственная связь (почему вернулись, кто решил). Явная стрелка + `loop_round` сохраняют и историю, и причину. | §12, §17 |
| A7 | Instrumentation = декораторы/обёртки вокруг существующих функций, без переписывания | Вносить timing-логику в каждую стадию вручную — дублирование и риск забыть. Декоратор `@stage('coder')` вокруг `PacketExecutionAdapter.execute()` автоматически пишет `stage_runs` и эмитит WS events. | §8 |
| A8 | Mobile = responsive single-page, breakpoint 900/600 | Соответствует `TZ_MISSION_CONTROL`. На <900px Gantt уходит в горизонтальный скролл, дерево features сворачивается в drawer. На <600px tabs уходят в bottom navigation. | §19 |
| A9 | Backward compatibility = новые поля в API опциональны, старые клиенты не ломаются | Все новые поля в `/api/admin/packet/{id}/detail` добавляются в существующий JSON. Старые поля не меняют семантику. Это позволяет катить доработку инкрементально. | §9 |
| A10 | Миграции БД = idempotent Alembic-style, как в `db/migrations/` | В репо уже есть migrations (см. `tests/grace_control/db/test_migrations.py`). Новые таблицы добавляются через тот же механизм. SQLite не поддерживает все `ALTER`, но `ADD COLUMN` — да. | §7 |

### 6.1. Принципы проектирования UI

Помимо архитектурных решений, фиксируем принципы для всех новых UI-компонентов:

- **Overview first, drill-down on click.** На любом экране сначала общая картина (Gantt всех пакетов, или список всех стадий), клик по элементу → детали. Не показываем сразу raw payload.
- **24h timestamps везде.** Все времена — в формате `HH:MM:SS` или `YYYY-MM-DD HH:MM:SS`. Никакого 12h AM/PM. Для ms-точности — `HH:MM:SS.mmm` в monospace.
- **Real-time без перезагрузки.** Running стадии обновляются через WebSocket без polling. Если WS упал — fallback на polling 5s с индикатором «offline, retrying».
- **Calm color palette.** Базовые цвета: gray (pending), blue (running), green (done), red (failed), yellow (skipped). Никаких ярких неоновых цветов. Фон — белый/светло-серый.
- **Compact over spacious.** Оператор смотрит на админку часами. Компактные rows, мелкие mono IDs, минимум воздуха. Не «кокпит» с большими плитками, а «таблица оператора».
- **Monospace для IDs и timestamps.** `packet_id`, `run_id`, `trace_id`, timestamps — в DejaVu Sans Mono, размер 9-10pt. Заголовки и описания — в Noto Sans, 11pt.
- **Action confirmations.** Любое контрольное действие (retry/cancel/stop/rerun) — с confirm dialog, показывающим что произойдёт и какой packet/run будет затронут.

---

## 7. Схема данных — изменения

Этот раздел описывает новые таблицы и расширения существующих. Все миграции идемпотентны и совместимы с SQLite (`ADD COLUMN`, `CREATE TABLE IF NOT EXISTS`). Существующие таблицы (`Feature`, `Wave`, `Packet`, `PacketRun`, `Worker`, `Lease`, `Event`, `SelfEvolutionSession`, `FeaturePlanningRun`, `AgentSession`) не меняют схему — только добавляются новые.

### 7.1. Новая таблица: `stage_runs`

Главная новая сущность. Одна строка — один запуск одной стадии одного пакета. Если пакет вернулся с verifier в coder, будет две строки с `stage_key='coder'` и разными `loop_round`. Это даёт честную историю всех прогонов всех стадий, с таймингами, метаданными и связями с `parent_session_id`.

```python
class StageRun(Base):
    __tablename__ = "stage_runs"

    id = Column(String, primary_key=True)        # srun_XXXX
    packet_id = Column(String, nullable=False, index=True)
    run_id = Column(String, nullable=True, index=True)  # PacketRun.id
    feature_id = Column(String, nullable=False, index=True)
    wave_id = Column(String, nullable=False, index=True)

    # Stage identity
    stage_key = Column(String, nullable=False, index=True)
    # context_builder|architect|materialize|executor|coder|
    # t0_scope_lint|t1_unit_tests|t2_e2e_smoke|t3_visual|
    # verifier|reviewer|merge
    attempt_number = Column(Integer, nullable=False, default=1)
    loop_round = Column(Integer, nullable=False, default=1)
    parent_stage_run_id = Column(String, nullable=True)  # для возвратов

    # Timing
    started_at = Column(DateTime, nullable=True)
    finished_at = Column(DateTime, nullable=True)
    duration_ms = Column(Integer, nullable=True)
    last_heartbeat = Column(DateTime, nullable=True)

    # Status
    status = Column(String, nullable=False, default="pending")
    # pending|running|done|failed|skipped|cancelled
    error = Column(Text, nullable=True)

    # Executor info
    executor_id = Column(String, nullable=True)
    worker_id = Column(String, nullable=True)
    model = Column(String, nullable=True)
    prompt_hash = Column(String, nullable=True)  # sha256 of prompt
    command_preview = Column(JSON, nullable=True)

    # LLM cost (для LLM-стадий: architect/coder/verifier/reviewer)
    tokens_in = Column(Integer, nullable=True)
    tokens_out = Column(Integer, nullable=True)
    cost_usd = Column(Numeric(10, 6), nullable=True)

    # Artifacts
    stdout_path = Column(String, nullable=True)
    stderr_path = Column(String, nullable=True)
    result_path = Column(String, nullable=True)  # evidence/decision json
    artifacts_dir = Column(String, nullable=True)  # директория с артефактами

    # Trace и recovery
    trace_id = Column(String, nullable=True, index=True)
    recovery_reason = Column(Text, nullable=True)
    # причина возврата, если loop_round > 1

    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow,
                        onupdate=datetime.utcnow)
```

### 7.2. Новая таблица: `stage_metrics`

Агрегаты по типам стадий за период. Материализуется по cron (см. §15). Одна строка — один `(stage_key, period_kind, period_start)` с подсчитанными статистиками.

```python
class StageMetric(Base):
    __tablename__ = "stage_metrics"

    id = Column(Integer, primary_key=True, autoincrement=True)
    stage_key = Column(String, nullable=False, index=True)
    period_kind = Column(String, nullable=False)  # 24h|7d|30d
    period_start = Column(DateTime, nullable=False, index=True)
    period_end = Column(DateTime, nullable=False)

    count = Column(Integer, nullable=False)
    p50_ms = Column(Integer, nullable=True)
    p95_ms = Column(Integer, nullable=True)
    avg_ms = Column(Integer, nullable=True)
    max_ms = Column(Integer, nullable=True)
    min_ms = Column(Integer, nullable=True)

    success_count = Column(Integer, nullable=False, default=0)
    failure_count = Column(Integer, nullable=False, default=0)
    success_rate = Column(Numeric(5, 4), nullable=True)

    # LLM cost (для LLM-стадий)
    avg_tokens_in = Column(Integer, nullable=True)
    avg_tokens_out = Column(Integer, nullable=True)
    avg_cost_usd = Column(Numeric(10, 6), nullable=True)
    total_cost_usd = Column(Numeric(10, 6), nullable=True)

    # Idle time: claim → start, для executor/coder стадий
    avg_idle_seconds = Column(Integer, nullable=True)

    computed_at = Column(DateTime, default=datetime.utcnow)

    __table_args__ = (
        UniqueConstraint("stage_key", "period_kind", "period_start",
                         name="uq_stage_metrics_period"),
    )
```

### 7.3. Расширение `PacketRun`

Добавляем поля для LLM cost (для подсчёта метрик). Существующие поля `model` / `command_preview` / `prompt` уже добавлены в `TZ_ADMIN_PANEL.md` и реализованы — их не трогаем.

```python
# Добавить в PacketRun:
tokens_in = Column(Integer, nullable=True)
tokens_out = Column(Integer, nullable=True)
cost_usd = Column(Numeric(10, 6), nullable=True)

# Эти поля заполняются в packet_executor.py при получении
# результата от agent runtime — agent уже возвращает usage в JSONL events.
```

### 7.4. Миграции

Миграции оформляются в стиле `db/migrations/00XX_*.py` (см. существующий `tests/grace_control/db/test_migrations.py`). Каждая миграция идемпотентна (`CREATE TABLE IF NOT EXISTS`, `ADD COLUMN` если ещё нет).

```python
# db/migrations/0010_stage_runs.py
def upgrade(db):
    db.execute("""
        CREATE TABLE IF NOT EXISTS stage_runs (
            id TEXT PRIMARY KEY,
            packet_id TEXT NOT NULL,
            run_id TEXT,
            feature_id TEXT NOT NULL,
            wave_id TEXT NOT NULL,
            stage_key TEXT NOT NULL,
            attempt_number INTEGER NOT NULL DEFAULT 1,
            loop_round INTEGER NOT NULL DEFAULT 1,
            parent_stage_run_id TEXT,
            started_at DATETIME,
            finished_at DATETIME,
            duration_ms INTEGER,
            last_heartbeat DATETIME,
            status TEXT NOT NULL DEFAULT 'pending',
            error TEXT,
            executor_id TEXT,
            worker_id TEXT,
            model TEXT,
            prompt_hash TEXT,
            command_preview JSON,
            tokens_in INTEGER,
            tokens_out INTEGER,
            cost_usd NUMERIC(10,6),
            stdout_path TEXT,
            stderr_path TEXT,
            result_path TEXT,
            artifacts_dir TEXT,
            trace_id TEXT,
            recovery_reason TEXT,
            created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
            updated_at DATETIME DEFAULT CURRENT_TIMESTAMP
        )
    """)
    db.execute("CREATE INDEX IF NOT EXISTS ix_stage_runs_packet ON stage_runs(packet_id)")
    db.execute("CREATE INDEX IF NOT EXISTS ix_stage_runs_stage ON stage_runs(stage_key)")
    db.execute("CREATE INDEX IF NOT EXISTS ix_stage_runs_status ON stage_runs(status)")
    db.execute("CREATE INDEX IF NOT EXISTS ix_stage_runs_trace ON stage_runs(trace_id)")

def downgrade(db):
    db.execute("DROP TABLE IF EXISTS stage_runs")
```

---

## 8. Сбор данных о стадиях (instrumentation)

Чтобы Gantt и Stage Timeline показывали честные данные, нужно инструментировать каждую стадию — создавать `StageRun` запись, эмитить WS events, сохранять артефакты с привязкой к стадии. Этот раздел описывает, где и как это делается. Принцип — декоратор/обёртка вокруг существующих функций, без переписывания их логики.

### 8.1. Декоратор `@stage()`

В новом модуле `src/grace_control/core/stage_instrumentation.py` определяется декоратор, который оборачивает функцию стадии. Декоратор:

- Создаёт `StageRun` строку со `status='running'`, `started_at=now()` перед вызовом.
- Эмитит WS event `stage_started` через `ws_broadcast.broadcast_event`.
- После успешного завершения — обновляет `StageRun`: `status='done'`, `finished_at`, `duration_ms`; эмитит `stage_finished`.
- При исключении — `status='failed'`, `error=traceback`; эмитит `stage_finished` со `status='failed'`.
- Опционально — periodic heartbeat через `last_heartbeat` (для long-running стадий).
- Сохраняет `executor_id`, `worker_id`, `model`, `prompt_hash`, `tokens`, `cost` если они переданы в kwargs.

```python
# src/grace_control/core/stage_instrumentation.py
from functools import wraps
from datetime import datetime, timezone
import traceback, hashlib, asyncio

from grace_control.db import get_db
from grace_control.db.schema import StageRun, Packet
from grace_control.api.ws_broadcast import broadcast_event
from grace_control.core.uid import generate_uid


def stage(stage_key: str, llm: bool = False):
    """Декоратор стадии пайплайна."""
    def deco(fn):
        is_async = asyncio.iscoroutinefunction(fn)

        @wraps(fn)
        async def wrapper(*args, packet_id: str, **kwargs):
            run = _start_stage(
                packet_id=packet_id,
                stage_key=stage_key,
                executor_id=kwargs.get("executor_id"),
                worker_id=kwargs.get("worker_id"),
                model=kwargs.get("model"),
                prompt=kwargs.get("prompt"),
                command_preview=kwargs.get("command_preview"),
            )
            await broadcast_event("stage_started", {
                "packet_id": packet_id,
                "stage_key": stage_key,
                "stage_run_id": run.id,
                "started_at": run.started_at.isoformat() + "Z",
            })
            try:
                result = await fn(*args, packet_id=packet_id, **kwargs)
                _finish_stage(run, status="done",
                              tokens_in=result.get("tokens_in") if llm else None,
                              tokens_out=result.get("tokens_out") if llm else None,
                              cost_usd=result.get("cost_usd") if llm else None,
                              result_path=result.get("result_path"),
                              artifacts_dir=result.get("artifacts_dir"))
                await broadcast_event("stage_finished", {
                    "packet_id": packet_id,
                    "stage_key": stage_key,
                    "stage_run_id": run.id,
                    "status": "done",
                    "duration_ms": run.duration_ms,
                })
                return result
            except Exception as e:
                _finish_stage(run, status="failed", error=traceback.format_exc())
                await broadcast_event("stage_finished", {
                    "packet_id": packet_id,
                    "stage_key": stage_key,
                    "stage_run_id": run.id,
                    "status": "failed",
                    "error": str(e),
                })
                raise

        return wrapper
    return deco
```

### 8.2. Где инструментировать (точечные изменения)

Точки внедрения декоратора. Каждая строка — функция, которая оборачивается, её текущий файл, что `stage_runs` запись будет содержать:

| Stage key | Функция для обёртки | Файл | Артефакты стадии |
|---|---|---|---|
| `context_builder` | `FeaturePlanningService.run_context_builder()` | `src/grace_control/services/feature_planning_service.py` | `context_bundle.json`, `scope_manifest.json` |
| `architect` | `FeaturePlanningService.run_architect()` | `src/grace_control/services/feature_planning_service.py` | `plan.json`, `EXECUTION_PACKET.md` (per packet) |
| `materialize` | `PacketMaterializer.materialize()` | `src/grace_control/services/packet_materializer.py` | — (только DB-записи) |
| `executor` | `PacketService.claim()` | `src/grace_control/services/packet_service.py` | lease row |
| `coder` | `PacketExecutionAdapter.execute()` | `src/grace_control/adapters/packet_executor.py` | `stdout.log`, `stderr.log`, `agent.jsonl`, git diff, commit |
| `t0_scope_lint` | `acceptance_pipeline.run_t0()` | `src/grace_control/core/acceptance_pipeline.py` | `scope_violations.json`, `lint_report.json` |
| `t1_unit_tests` | `acceptance_pipeline.run_t1()` | `src/grace_control/core/acceptance_pipeline.py` | `test_report.json` |
| `t2_e2e_smoke` | `acceptance_pipeline.run_t2()` | `src/grace_control/core/acceptance_pipeline.py` | `playwright_report.json`, `screenshots/` |
| `t3_visual` | `visual_baseline_manager.compare()` | `src/grace_control/services/visual_baseline_manager.py` | `visual_diff.png`, `baseline.json` (planned) |
| `verifier` | `evidence_verifier.run_evidence_verifier()` | `src/grace_control/core/evidence_verifier.py` | `verifier_decision.json` |
| `reviewer` | `reviewer_gate.run_reviewer_gate()` | `src/grace_control/core/reviewer_gate.py` | `reviewer_decision.json` |
| `merge` | `MergeService.merge_packet()` | `src/grace_control/services/merge_service.py` | `merge_commit_sha` |

### 8.3. Recovery loops — `loop_round` и `parent_stage_run_id`

Когда `recovery_controller` принимает решение вернуть пакет с verifier в coder, он должен создать новый `StageRun` для coder со следующими полями:

- `stage_key='coder'` (тот же ключ стадии).
- `attempt_number` — увеличивается на 1 (это уже делает `packet_service`).
- `loop_round` — увеличивается на 1 относительно предыдущего `StageRun` этой стадии этого пакета.
- `parent_stage_run_id` — указывает на `StageRun` verifier-а, который инициировал возврат.
- `recovery_reason` — строка из `result_json.recovery.reason` (например, `'evidence missing T1'`).
- `trace_id` — тот же `trace_id`, что и у parent (сквозной trace пакета).

В `recovery_controller.py` добавляется вызов `stage_runs.create_for_return()` при каждом решении из `RECOVERY_EVENTS`. Это позволяет Stage Timeline показывать историю всех прогонов каждой стадии с явными связями parent→child.

### 8.4. LLM cost tracking

Для LLM-стадий (`architect`, `coder`, `verifier`, `reviewer`) нужно собирать `tokens_in`, `tokens_out`, `cost_usd`. Agent runtime (opencode) уже возвращает usage в JSONL events (см. `tests/grace_control/runtime/test_opencode_event_collector.py`). Нужно:

- В `opencode_event_collector.py` суммировать `usage` события за время стадии.
- В `packet_executor.py` прокидывать суммарный usage в `ExecutionResult`.
- Декоратор `@stage(llm=True)` забирает эти значения из результата и пишет в `stage_runs`.
- Cost считается по таблице моделей (см. §15.3).

---

## 9. API endpoints — новые и изменяемые

Все новые endpoints живут в существующих роутерах `src/grace_control/api/routers/`. Read endpoints добавляются в `admin.py` (или в новый `admin_pipeline.py`, подключаемый к `app_factory`). Control endpoints заменяют stub-ы в `admin.py` на реальные реализации. Существующие endpoints не меняют сигнатуры — только добавляются поля в response (см. A9).

### 9.1. Новые read endpoints

| Method | Path | Query params | Response shape | Назначение |
|---|---|---|---|---|
| GET | `/api/admin/packet/{id}/pipeline` | `include_skipped=false` | `{stages: StageRun[], recovery_chain: Recovery[], totals: {duration_ms, tokens_in, tokens_out, cost_usd, loop_count}}` | Полный pipeline пакета со всеми прогонами стадий (включая loops). Заменяет текущий `pipeline` в packet detail. |
| GET | `/api/admin/packet/{id}/pipeline/gantt` | `zoom=1h\|6h\|24h\|7d, include_loops=true` | `{zoom, time_min, time_max, lanes: [{packet_id, label, bars: [{stage_key, started_at, finished_at, status, loop_round, color}]}]}` | Готовые данные для Gantt-таймлайна одного пакета. Один lane = один цикл (round 1, round 2 ...). |
| GET | `/api/admin/feature/{id}/gantt` | `zoom=1h\|6h\|24h\|7d, wave_id=all` | `{zoom, time_min, time_max, lanes: [{packet_id, wave, label, bars: [...]}]}` | Gantt для всей фичи: один lane = один пакет, бары стадий на оси времени. |
| GET | `/api/admin/packet/{id}/logs/aggregated` | `sources=server,supervisor,worker_stdout,worker_stderr,agent,recovery,db_events, tail=500, level=all, trace_id=, regex=` | `{lines: [{ts, source, level, trace_id, msg}], total, truncated, sources_used: []}` | Агрегированные логи из 7 источников, склеенные по времени, опционально отфильтрованные по trace_id/level/regex. |
| GET | `/api/admin/packet/{id}/stages/{stage_key}/artifacts` | `loop_round=1` | `{stage_key, loop_round, artifacts: [{name, path, size, type, preview_url}], total_size}` | Артефакты конкретной стадии (например, только `verifier_decision.json` и связанные логи). |
| GET | `/api/admin/packet/{id}/stages/{stage_key}/logs` | `stream=stdout\|stderr\|agent\|all, tail=200` | `{lines: [...], source_file}` | Логи только одной стадии — подмножество aggregated, но с привязкой к `stage_run`. |
| GET | `/api/admin/stages/{stage_key}/metrics` | `period=24h\|7d\|30d` | `{stage_key, period, count, p50_ms, p95_ms, avg_ms, max_ms, success_rate, avg_tokens_in, avg_tokens_out, avg_cost_usd, total_cost_usd, avg_idle_seconds, histogram: [{bucket, count}], trend: [{day, p50, p95}]}` | Метрики по типу стадии. Данные из `stage_metrics`, пересчитываемые по cron. |
| GET | `/api/admin/stages/metrics/heatmap` | `period=7d` | `{matrix: [[stage_key, hour, count, avg_ms]], stages: [...], hours: [0..23]}` | Heatmap «стадия × час» для поиска bottleneck-ов (например, coder долго в пиковые часы). |
| GET | `/api/admin/stages` | — | `{stages: [{key, label, description, is_llm, is_acceptance, profile_required}]}` | Справочник стадий (для UI — какие стадии показывать, в каком порядке). |

### 9.2. Control endpoints — реализация stub-ов и новые

Текущие stub-ы `resume`/`delete`/`stop` возвращают 501. Это ТЗ требует их реализовать, плюс добавить 3 новых control-action:

| Method | Path | Status | Что делает | Audit |
|---|---|---|---|---|
| POST | `/api/admin/packet/{id}/retry` | NEW (заменяет `resume` stub) | Для packet в `BLOCKED_RECOVERABLE`: сбрасывает state в `READY`, увеличивает `attempt_count`, эмитит `packet_transition` event с `reason='manual_retry'`. | `Event(event_type='admin_action', payload={action:'retry', actor, reason})` |
| POST | `/api/admin/packet/{id}/cancel` | NEW (заменяет `stop` stub) | Для packet в `RUNNING`: отправляет сигнал worker-у на graceful stop, освобождает lease, переводит state в `CANCELLED`. Таймаут 30s на graceful, потом force-kill. | `Event(event_type='admin_action', payload={action:'cancel', actor, force_after_30s:true})` |
| POST | `/api/admin/packet/{id}/delete` | Реализовать stub | Удаляет packet и все `PacketRun`/`StageRun`/`Event` записи. Требует подтверждения через `confirm=packet_id` в body. Не удаляет artifacts на диске (отдельная ручка). | `Event(event_type='admin_action', payload={action:'delete', actor, confirmed:true})` |
| POST | `/api/admin/packet/{id}/stages/{stage_key}/rerun` | NEW | Re-run одной стадии (только `verifier`/`reviewer` для дебага). Создаёт новый `StageRun` с `loop_round+1`, не трогает coder. Эмитит `stage_started`. | `Event(event_type='admin_action', payload={action:'rerun_stage', stage_key, actor})` |
| POST | `/api/admin/workers/{worker_id}/stop` | NEW | Для зависшего worker: `SIGTERM` subprocess, освобождает lease, переводит worker в `status='stopped'`. Если worker не отвечает 60s — `SIGKILL`. | `Event(event_type='admin_action', payload={action:'stop_worker', worker_id, actor, force_after_60s:true})` |
| POST | `/api/admin/packet/{id}/dev-replay` | NEW (UI-обёртка над существующим `dev_replay` router) | Воспроизводит стадию по `trace_id` — использует существующий `src/grace_control/api/routers/dev_replay.py`. UI даёт кнопку «Dev-replay this stage». | `Event(event_type='admin_action', payload={action:'dev_replay', trace_id, actor})` |

### 9.3. Изменения существующих endpoints

Существующие endpoints расширяются новыми полями в response. Старые клиенты не ломаются (новые поля опциональны):

- `GET /api/admin/packet/{id}/detail` — добавляется поле `stages` (полный `StageRun[]` вместо упрощённого `pipeline`), `recovery_chain`, `totals`.
- `GET /api/admin/packet/{id}/runs` — добавляется `tokens_in`/`tokens_out`/`cost_usd` для каждого run.
- `GET /api/admin/packet/{id}/runs/{run_id}/artifacts` — артефакты группируются по стадии: `{by_stage: {context_builder: [...], architect: [...], coder: [...], ...}}`.
- `GET /api/admin/overview` — добавляется `stats.by_stage: {running: {coder: 3, verifier: 1}, today_cost_usd: 1.23}`.
- `GET /api/admin/system/workers` — добавляется `current_stage_key`, `current_stage_started_at` для каждого worker.

### 9.4. Response contracts (примеры)

Пример `GET /api/admin/packet/{id}/pipeline`:

```json
{
  "packet_id": "pkt_T4V9K2mA1b",
  "totals": {
    "duration_ms": 1843200,
    "tokens_in": 45200,
    "tokens_out": 8900,
    "cost_usd": 0.342,
    "loop_count": 1
  },
  "stages": [
    {"id":"srun_001","stage_key":"context_builder","status":"done",
     "started_at":"2026-06-25T10:00:00Z","finished_at":"2026-06-25T10:00:15Z",
     "duration_ms":15000,"loop_round":1,"executor_id":"context_builder_v1",
     "model":"deepseek/deepseek-v4-flash","tokens_in":1200,"tokens_out":800,
     "cost_usd":0.012,"artifacts_dir":"/state/.../context_builder/",
     "log_links":{"stdout":"/api/admin/.../logs?stream=stdout&stage=context_builder"},
     "artifact_links":[{...}]},
    {"id":"srun_002","stage_key":"architect","status":"done", ...},
    {"id":"srun_003","stage_key":"materialize","status":"done", ...},
    {"id":"srun_004","stage_key":"executor","status":"done", ...},
    {"id":"srun_005","stage_key":"coder","status":"done",
     "loop_round":1, "duration_ms":420000, ...},
    {"id":"srun_006","stage_key":"t1_unit_tests","status":"failed",
     "duration_ms":18000, "error":"2 tests failed"},
    {"id":"srun_007","stage_key":"verifier","status":"failed",
     "duration_ms":9000,
     "recovery_reason":"evidence missing T1",
     "parent_stage_run_id":null},
    {"id":"srun_008","stage_key":"coder","status":"done",
     "loop_round":2,
     "parent_stage_run_id":"srun_007",
     "recovery_reason":"evidence missing T1",
     "duration_ms":380000},
    {"id":"srun_009","stage_key":"t1_unit_tests","status":"done",
     "loop_round":2, "duration_ms":12000},
    {"id":"srun_010","stage_key":"verifier","status":"done",
     "loop_round":2, "duration_ms":8000},
    {"id":"srun_011","stage_key":"reviewer","status":"done",
     "duration_ms":11000},
    {"id":"srun_012","stage_key":"merge","status":"done",
     "duration_ms":2000, "result":{"commit_sha":"abc1234"}}
  ],
  "recovery_chain": [
    {"from":"verifier","to":"coder","reason":"evidence missing T1",
     "decision":"recovery_return_to_coder","at":"2026-06-25T10:25:00Z",
     "loop_round":2}
  ]
}
```

---

## 10. WebSocket события — расширение

Существующий `/ws` endpoint уже работает и бродкастит `state_change` и `recovery_update`. Это ТЗ расширяет набор event types, чтобы UI мог обновлять stage timeline и aggregated logs в реальном времени, без polling.

### 10.1. Новые event types

| Event type | Когда эмитится | Payload |
|---|---|---|
| `stage_started` | Декоратор `@stage()` начинает выполнение (см. §8.1) | `{packet_id, stage_key, stage_run_id, attempt, loop_round, started_at, executor_id?, model?}` |
| `stage_finished` | Декоратор `@stage()` завершается (успех или fail) | `{packet_id, stage_key, stage_run_id, status: done\|failed\|skipped, finished_at, duration_ms, error?, tokens_in?, tokens_out?, cost_usd?}` |
| `stage_progress` | Промежуточный heartbeat для long-running стадий (coder, architect) | `{packet_id, stage_key, stage_run_id, message, percent?, last_heartbeat}` |
| `stage_log_line` | Когда stage пишет в stdout/stderr и мы стримим в UI (opt-in) | `{packet_id, stage_key, source: stdout\|stderr\|agent\|recovery, line, level: info\|warn\|error, ts, trace_id}` |
| `stage_artifact_added` | Когда stage сохранила артефакт (`evidence.json`, `diff.patch`, `screenshot.png`) | `{packet_id, stage_key, path, size, type: image\|log\|json\|file}` |
| `stage_returned` | Когда `recovery_controller` принял решение вернуть пакет в предыдущую стадию | `{packet_id, from_stage, to_stage, reason, decision: recovery_return_to_*, loop_round, parent_stage_run_id}` |
| `worker_heartbeat` | Worker шлёт heartbeat (раз в 10s) | `{worker_id, current_packet_id, current_stage_key, last_heartbeat, lease_expires_at}` |
| `metrics_updated` | Cron пересчитал `stage_metrics` | `{stage_keys: [...], period: 24h\|7d\|30d, computed_at}` |

### 10.2. Формат сообщений

Все WS-сообщения — JSON с обязательным полем `type`. Сервер не фильтрует сообщения по подписке — клиент сам решает, что обрабатывать. Это упрощает серверную логику и соответствует существующей реализации `ws_broadcast`.

```json
// Каждое сообщение от сервера имеет вид:
{
  "type": "stage_started",
  "packet_id": "pkt_T4V9K2mA1b",
  "stage_key": "coder",
  "stage_run_id": "srun_005",
  "attempt": 1,
  "loop_round": 1,
  "started_at": "2026-06-25T10:05:00Z",
  "executor_id": "coder-deepseek-v4-flash",
  "model": "deepseek/deepseek-v4-flash"
}

// Сообщения от recovery_controller-а дополнительно
// проходят через _broadcast_recovery() и имеют type="recovery_update":
{
  "type": "recovery_update",
  "data": {...},
  "event_type": "recovery_return_to_architect",
  "timestamp": "2026-06-25T10:25:00Z"
}
```

### 10.3. Клиентская фильтрация

Клиентский `admin.js` должен фильтровать входящие WS-сообщения по `packet_id`. Если оператор открыт на packet detail, обновляем только stage timeline этого пакета. Если открыт overview — обновляем только stats и Gantt-таймлайн текущей фичи. Пример логики:

```javascript
// admin.js — фрагмент WS-обработчика
ws.onmessage = (ev) => {
  const msg = JSON.parse(ev.data);
  if (msg.type === "stage_started" ||
      msg.type === "stage_finished" ||
      msg.type === "stage_returned") {
    if (msg.packet_id === currentPacketId) {
      htmx.trigger("#stage-timeline", "refresh");
    }
    if (currentFeaturePackets.includes(msg.packet_id)) {
      htmx.trigger("#feature-gantt", "refresh");
    }
  }
  if (msg.type === "stage_log_line" &&
      msg.packet_id === currentPacketId &&
      aggregatedLogsOpen) {
    appendLogLine(msg);
  }
  if (msg.type === "worker_heartbeat") {
    updateWorkerCard(msg);
  }
  if (msg.type === "recovery_update") {
    htmx.trigger("#recovery-chain", "refresh");
  }
};
```

### 10.4. Backoff и reconnect

Если WS-соединение упало, клиентский код должен:

- Показать индикатор «Offline, retrying» в шапке админки (красный бейдж).
- Пытаться переподключиться с экспоненциальным backoff: 1s, 2s, 4s, 8s, 16s, 30s (макс).
- После 3 неудачных попыток — переключиться на HTMX polling 5s как fallback.
- При восстановлении — сделать полный refresh текущей страницы (HTMX `hx-get`), потому что мы могли пропустить события.

### 10.5. Опциональная подписка (filter при connect)

Расширение `/ws`: при handshake клиент может передать `?filter=packet:{id}` в URL, чтобы сервер фильтровал события только для этого пакета. Это снижает нагрузку на канал, если оператор открыл detail и не нуждается в событиях других пакетов. Реализация опциональна (v1.1), v1 бродкастит всё.

---

## 11. UI: Главный экран — Feature Pipeline Gantt

Главный экран `/admin` меняется: вместо текущего «features tree + selected feature timeline с packet cards» появляется трёхколоночный layout с Gantt-таймлайном в центре. Левая и правая колонки остаются, центральная меняется кардинально. Это даёт обзор всего пайплайна фичи на одной картине.

### 11.1. Layout (desktop ≥1100px)

```
┌──────────────────────────────────────────────────────────────────┐
│  Stats Bar: Health | Features | Packets | Running | Blocked | $  │
├──────────┬─────────────────────────────────────────┬─────────────┤
│ Features │  Feature Pipeline Gantt                 │ Right       │
│   tree   │  ┌───────────────────────────────────┐  │  - Workers  │
│          │  │ zoom: [1h][6h][24h][7d]  filter ▾ │  │  - Blocked  │
│ ▸ Feat A │  ├───────────────────────────────────┤  │  - Recent   │
│ ▾ Feat B │  │ W1 · pkt_001  ▓▓░░░░▓▓░░░░░░░░░░  │  │    events   │
│   ▾ W1   │  │ W1 · pkt_002  ░░▓▓▓▓░░░░░░░░░░░░  │  │             │
│     p001 │  │ W2 · pkt_003  ░░░░░░▓▓░░░▓▓░░░░░  │  │             │
│     p002 │  │ W2 · pkt_004  ░░░░░░░░░░▓▓▓▓░░░░  │  │             │
│   ▸ W2   │  │ W3 · pkt_005  ░░░░░░░░░░░░░░▓▓░░  │  │             │
│ ▸ Feat C │  │                                     │  │             │
│          │  │ legend: ▓ctx ▓arch ▓coder ▓ver ▓mer│  │             │
│          │  └───────────────────────────────────┘  │             │
├──────────┴─────────────────────────────────────────┴─────────────┤
│  Footer: clock | offline/online | version                       │
└──────────────────────────────────────────────────────────────────┘
```

### 11.2. Левая колонка: Features tree (без изменений)

Остаётся как сейчас — дерево features → waves → packets с expand/collapse. Клик по feature обновляет центральную Gantt-зону (загружает пакеты этой фичи). Клик по packet — открывает packet detail (см. §12).

### 11.3. Центральная колонка: Feature Pipeline Gantt

Главная новая зона. Структура сверху вниз:

- **Toolbar:** zoom-переключатель (`1h` / `6h` / `24h` / `7d`), filter chip (`all` / `running` / `failed` / `blocked` / `attention`), search input.
- **Gantt-тело:** вертикальный список пакетов выбранной фичи (с группировкой по wave — заголовок wave перед каждой группой).
- Для каждого пакета — горизонтальный lane с bars стадий.
- **Легенда стадий** снизу.
- **Timeline-линейка** сверху с timestamp-метками (24h формат).

Цветовая кодировка баров (по status стадии):

| Цвет | Status | Семантика |
|---|---|---|
| Серый `#CCC` | `pending` | Стадия ещё не запущена (ждёт свою очередь) |
| Синий `#0B5E87` | `running` | Сейчас выполняется, обновляется в реальном времени |
| Зелёный `#1E7E34` | `done` | Успешно завершена |
| Красный `#B02A2A` | `failed` | Завершилась с ошибкой |
| Жёлтый `#B8860B` | `skipped` | Пропущена (не в `acceptance_profile`) |
| Фиолетовый `#6C3483` | `returned` | Стадия инициировала возврат (loop) |

### 11.4. Возвраты (loops) на Gantt

Если пакет вернулся с verifier в coder, на Gantt это показывается как:

- Два бара coder на одном lane (один над другим или рядом, в зависимости от zoom).
- Пунктирная красная стрелка от конца verifier-бара к началу второго coder-бара.
- Под стрелкой — подпись причины (например, «evidence missing T1»), обрезанная до 30 символов с tooltip на полный текст.
- Бар второго раунда coder имеет полупрозрачный паттерн (диагональные полоски), чтобы визуально отличаться от первого.
- Справа от lane — бейдж «Round 2/3» с количеством loops.

### 11.5. Hover и click на баре

Hover на баре стадии показывает tooltip с:

- `stage_key` + label (например, «Coder run»).
- status с цветным кружком.
- `started_at` → `finished_at` (24h с ms).
- duration (HH:MM:SS).
- `worker_id`, `executor_id`, `model` (если есть).
- `loop_round`, если > 1.
- `tokens_in` / `tokens_out` / `cost_usd`, если LLM-стадия.

Click на баре — открывает packet detail с активной секцией Pipeline, проскролленной к выбранной стадии (см. §12). URL меняется на `/admin?packet_id=...&stage=srun_005`.

### 11.6. Real-time обновление Gantt

Gantt обновляется через WebSocket: при получении `stage_started` или `stage_finished` для `packet_id` из текущей фичи — HTMX делает `hx-get` на `/admin/_partial/gantt?feature_id=...` для перерисовки. Для running-баров правая граница «тянется» в реальном времени через CSS transition (width анимируется раз в 5s на основе elapsed).

### 11.7. Реализация в шаблоне

Новый Jinja2-шаблон `src/grace_control/ui/templates/admin/_gantt.html`. Структура:

```jinja2
{# _gantt.html #}
<div id="feature-gantt" hx-trigger="refresh"
     hx-get="/admin/_partial/gantt?feature_id={{ f.id }}&zoom={{ zoom }}"
     hx-swap="outerHTML">
  <div class="gantt-toolbar">
    <div class="zoom-switch">
      {% for z in ["1h","6h","24h","7d"] %}
      <button class="zoom-btn {{ 'active' if z == zoom }}"
              hx-get="/admin/_partial/gantt?feature_id={{ f.id }}&zoom={{ z }}"
              hx-target="#feature-gantt" hx-swap="outerHTML">{{ z }}</button>
      {% endfor %}
    </div>
    <input type="search" name="gantt_search"
           hx-get="/admin/_partial/gantt" hx-trigger="keyup changed delay:300ms"
           hx-target="#feature-gantt" hx-swap="outerHTML"
           placeholder="Filter packets...">
  </div>

  <div class="gantt-body">
    <div class="gantt-ruler">10:00  11:00  12:00  13:00  14:00  15:00</div>
    {% for w in f.waves %}
      <div class="gantt-wave-header">W{{ w.order }} · {{ w.title }}</div>
      {% for p in w.packets %}
        <div class="gantt-lane" data-packet="{{ p.id }}">
          <div class="gantt-lane-label">{{ p.slug }}</div>
          <div class="gantt-lane-track">
            {% for s in p.stages %}
              <div class="gantt-bar status-{{ s.status }}"
                   style="left: {{ s.left_pct }}%; width: {{ s.width_pct }}%"
                   title="{{ s.label }} · {{ s.started }} → {{ s.finished }} ({{ s.duration }})"
                   hx-get="/admin?packet_id={{ p.id }}&stage={{ s.id }}"
                   hx-push-url="true">
                {{ s.label }}
              </div>
              {% if s.returned_to %}
              <svg class="gantt-arrow" ...><path d="..."/></svg>
              {% endif %}
            {% endfor %}
          </div>
        </div>
      {% endfor %}
    {% endfor %}
  </div>

  <div class="gantt-legend">
    <span class="legend-item"><span class="swatch status-pending"></span>pending</span>
    <span class="legend-item"><span class="swatch status-running"></span>running</span>
    <span class="legend-item"><span class="swatch status-done"></span>done</span>
    <span class="legend-item"><span class="swatch status-failed"></span>failed</span>
    <span class="legend-item"><span class="swatch status-skipped"></span>skipped</span>
    <span class="legend-item"><span class="swatch status-returned"></span>returned</span>
  </div>
</div>
```

---

## 12. UI: Детализация пакета — Stage Timeline

Packet detail меняется: над существующими вкладками добавляется новая верхняя секция «Pipeline» с горизонтальным Stage Timeline. Эта секция всегда видна при открытии пакета — оператор сразу видит, что и когда произошло, без переключения вкладок. Существующие вкладки (`timeline`/`spec`/`runs`/`sessions`/`evidence`/`logs`/`artifacts`/`diagnostics`) остаются под ней.

### 12.1. Layout Packet Detail

```
┌─ Packet Detail ───────────────────────────────────────────────────────┐
│ [pkt_T4V9K2mA1b]  Packet title here                       [Retry][⏹] │
│ Wave W1 · Feat B · state: MERGED · attempt 2/3 · profile: STRICT       │
│ Worker: wkr_abc · Model: deepseek-v4-flash · Started: 14:00 · 30:42   │
├───────────────────────────────────────────────────────────────────────┤
│ ▼ Pipeline                                                            │
│   14:00:00          14:05     14:10    14:15    14:20    14:30        │
│   ▓▓ ▓▓▓▓ ▓ ▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓░ ▓▓ ▓▓▓▓▓▓▓▓▓▓▓▓ ▓▓▓▓ ▓▓▓              │
│   ctx arch mat cod         T1  ver ←──── coder(2) ──── T1 ver rev mer │
│                                          ↑ returned: "evidence T1"   │
│                                                                       │
│   Stage cards (вертикальный список):                                  │
│   ┌─ Context Builder ─ done ─ 00:15 ────────────────────────── [L][A]┐│
│   ├─ Architect      ─ done ─ 02:00 ──────────────────────── [L][A][R]││
│   ├─ Materialize    ─ done ─ 00:01 ───────────────────────────── [A]││
│   ├─ Executor       ─ done ─ 00:00 ─ wkr_abc ─────────────────── [L]││
│   ├─ Coder (r1)     ─ done ─ 07:00 ─ deepseek-v4 ─ 12k tok ── [L][A]││
│   ├─ T1 unit tests  ─ failed ─ 00:18 ─ 2/15 failed ──────────── [L][A]││
│   ├─ Verifier       ─ failed ─ 00:09 ─ "evidence missing T1" ── [L][A]││
│   ├─ Coder (r2)     ─ done ─ 06:20 ─ 11k tok ─────────────── [L][A][R]││
│   ├─ T1 unit tests  ─ done ─ 00:12 ───────────────────────── [L][A]  ││
│   ├─ Verifier       ─ done ─ 00:08 ───────────────────────── [L][A]  ││
│   ├─ Reviewer       ─ done ─ 00:11 ───────────────────────── [L][A]  ││
│   └─ Merge          ─ done ─ 00:02 ─ commit abc1234 ──────── [L][A]  ┘│
│                                                                       │
│   Recovery chain (collapsed by default):                             │
│   ▸ 1 return: verifier → coder (round 2) · "evidence missing T1"     │
├───────────────────────────────────────────────────────────────────────┤
│ Tabs: [Timeline] [Spec] [Runs] [Sessions] [Evidence] [Logs] [Aggr]*  │
│       [Artifacts] [Diagnostics]                                       │
│                                                                       │
│   ... (содержимое активной вкладки)                                   │
└───────────────────────────────────────────────────────────────────────┘
                                                              * = new tab
```

### 12.2. Stage Timeline (горизонтальный Gantt одного пакета)

Над stage cards — компактный Gantt одного пакета. Каждая стадия — горизонтальный бар на оси времени. Бары расположены в один ряд, но возвраты сдвигаются вниз (round 2 на отдельной строке). Особенности:

- Ось времени — адаптивная, от 1 минуты до 24 часов в зависимости от общей длительности пакета.
- Под осью — timestamp-метки в 24h формате (например, `14:00`, `14:05`, `14:10`).
- Текущая running стадия — синий бар с пульсирующей анимацией; правая граница «тянется» в реальном времени.
- Возвраты — пунктирная красная стрелка от верификатора к coder (round 2) с подписью причины.
- Click на баре — раскрывает соответствующую stage card ниже (scroll + highlight).

### 12.3. Stage cards (вертикальный список)

Под Gantt — вертикальный список карточек стадий в порядке выполнения. Каждая карточка показывает:

| Поле | Пример | Описание |
|---|---|---|
| Stage label + round | `Coder (r2)` | Название стадии и round, если > 1 |
| Status badge | `done` / `failed` / `running` | Цветной бейдж по статусу |
| Duration | `06:20` | HH:MM:SS, для running — elapsed (живой) |
| Started → Finished | `14:05:12 → 14:11:32` | 24h timestamps с секундами |
| Worker / Executor | `wkr_abc · coder-deepseek-v4` | Кто исполнял |
| Model | `deepseek/deepseek-v4-flash` | Для LLM-стадий |
| Tokens / Cost | `12k in · 3k out · $0.042` | Для LLM-стадий |
| Error / Reason | `evidence missing T1` | Если failed или возвращалась |
| Buttons | `[L] [A] [R]` | Logs, Artifacts, Re-run (только verifier/reviewer) |

Если у пакета есть P50/P95 метрики по этому типу стадии (см. §15), рядом с duration показывается сравнение: «06:20 (P50: 05:45, P95: 12:30)». Аномально долгая стадия (> P95) подсвечивается жёлтой рамкой.

### 12.4. Recovery chain

Если у пакета были возвраты (`loop_count > 0`), под stage cards показывается сворачиваемая секция Recovery chain. По умолчанию collapsed — раскрывается по клику. Внутри:

- Список всех recovery decisions в порядке времени.
- Для каждого: timestamp (24h), `from_stage → to_stage`, reason (полный текст), decision (`recovery_return_to_coder` / `recovery_switch_coder` / `recovery_return_to_architect` / `recovery_block_feature` / ...).
- Ссылка на связанный `Event` (по `event_id` из `Event` table).
- Ссылка на `trace_id` (открывает aggregated logs с фильтром по этому trace).

### 12.5. Header с контрольными действиями

Header пакета (как сейчас) показывает: id, title, state, attempt, profile, worker, model, started, elapsed. Дополнительно — кнопки:

| Кнопка | Когда активна | Действие |
|---|---|---|
| Retry | `state ∈ {BLOCKED_RECOVERABLE, REJECTED}` | `POST /api/admin/packet/{id}/retry` — сбрасывает в `READY` |
| Cancel | `state = RUNNING` | `POST /api/admin/packet/{id}/cancel` — graceful stop |
| Delete | `state ∈ terminal states` | `POST /api/admin/packet/{id}/delete` — требует подтверждения |
| Dev-replay | любой state | `POST /api/admin/packet/{id}/dev-replay` — открыть dev_replay dialog |

Кнопки показываются с confirm dialog. Confirm dialog показывает: «This will `<action>` packet `<id>` in state `<state>`. Continue?» с кнопками Cancel и Confirm. После действия — toast notification с результатом и audit event в `recent_events`.

### 12.6. Шаблоны

Новые Jinja2-шаблоны в `src/grace_control/ui/templates/admin/`:

- `detail/_pipeline.html` — Stage Timeline + Stage cards (новая верхняя секция).
- `detail/_recovery_chain.html` — Recovery chain (collapsed).
- `detail/_stage_card.html` — одна карточка стадии (используется в цикле).
- `tabs/_aggregated_logs.html` — новая вкладка Aggregated Logs (см. §13).

Существующий `_detail.html` расширяется: в начало добавляется `{% include 'detail/_pipeline.html' %}`, ниже — текущее содержимое. Существующие вкладки не меняются.

---

## 13. UI: Агрегированные логи

Новая вкладка **Aggregated Logs** в packet detail (рядом с существующей Logs). Существующая вкладка Logs остаётся — она показывает stderr одного run-а. Aggregated Logs — это сквозной поток всех подсистем по пакету, склеенный по времени, с фильтрами по source/level/trace_id/regex и real-time режимом через WebSocket.

### 13.1. Источники логов

Агрегированный поток собирается из 7 источников. Каждый источник имеет свой цвет в UI и свою механику чтения:

| # | Source | Цвет | Где хранится | Как читается |
|---|---|---|---|---|
| 1 | Server (FastAPI/uvicorn) | Серый `#888` | `/tmp/api*.log` (rotating) | Tail-N последних строк, фильтр по `packet_id` в JSON-строке |
| 2 | Supervisor (process_supervisor) | Фиолетовый `#6C3483` | `/tmp/supervisor.log` или stderr supervisor-а | Tail-N, фильтр по `worker_id`/`packet_id` |
| 3 | Worker stdout | Синий `#0B5E87` | `PacketRun.worktree/stdout.log` | Tail-N (уже есть endpoint `/logs?stream=stdout`) |
| 4 | Worker stderr | Красный `#B02A2A` | `PacketRun.worktree/stderr.log` | Tail-N (уже есть endpoint `/logs?stream=stderr`) |
| 5 | Agent runtime (opencode JSONL) | Зелёный `#1E7E34` | `PacketRun.worktree/agent.jsonl` | Tail-N JSONL строк, парсим в поля (ts, type, message) |
| 6 | Recovery controller | Оранжевый `#CC5500` | `Event` table (`event_type LIKE 'recovery_%'`) | SQL-запрос по `entity_id=packet_id` |
| 7 | DB events (audit trail) | Голубой `#17A2B8` | `Event` table (все остальные) | SQL-запрос по `entity_id=packet_id` |

### 13.2. Endpoint

`GET /api/admin/packet/{id}/logs/aggregated` — основной endpoint. Параметры:

| Параметр | Default | Описание |
|---|---|---|
| `sources` | `all` | Comma-separated список источников: `server,supervisor,worker_stdout,worker_stderr,agent,recovery,db_events`. `all` = все |
| `tail` | `500` | Сколько строк каждого источника тащить. Max 5000 на источник |
| `level` | `all` | `all \| info \| warn \| error` — фильтр по уровню (если источник его поддерживает) |
| `trace_id` | — | Фильтр по `trace_id` (substring match) |
| `regex` | — | Regex для фильтрации строк |
| `since` | — | ISO timestamp — только события после этого времени |
| `until` | — | ISO timestamp — только события до этого времени |

Response shape:

```json
{
  "lines": [
    {"ts":"2026-06-25T14:00:00.123Z", "source":"server",
     "level":"info", "trace_id":"trc_abc",
     "msg":"packet_claimed pkt_T4V9K2mA1b by wkr_001"},
    {"ts":"2026-06-25T14:00:01.456Z", "source":"supervisor",
     "level":"info", "trace_id":"trc_abc",
     "msg":"spawn opencode --model deepseek-v4-flash"},
    {"ts":"2026-06-25T14:00:02.789Z", "source":"agent",
     "level":"info", "trace_id":"trc_abc",
     "msg":"tool_call: read_file(src/hello.py)"},
    ...
  ],
  "total": 1234,
  "truncated": false,
  "sources_used": ["server","supervisor","worker_stdout","agent"],
  "time_range": {"min":"2026-06-25T14:00:00Z","max":"2026-06-25T14:30:42Z"}
}
```

### 13.3. UI вкладки Aggregated Logs

Layout вкладки:

```
┌─ Aggregated Logs ──────────────────────────────────────────────────┐
│ Sources: ☑Server ☑Supervisor ☑Worker out ☑Worker err ☑Agent ☑Rec ☑DB│
│ Level: [All ▾]  Trace: [______]  Regex: [______]  Tail: [500 ▾]    │
│ [Refresh] [Auto-scroll ☑] [Freeze] [Export .log]                   │
├────────────────────────────────────────────────────────────────────┤
│ 14:00:00.123 [server]    INFO  trc_abc  packet_claimed pkt_...     │
│ 14:00:01.456 [supervisor] INFO trc_abc  spawn opencode --model...  │
│ 14:00:02.789 [agent]     INFO  trc_abc  tool_call: read_file...    │
│ 14:00:03.012 [worker_out] INFO trc_abc  → file read OK 1.2 KB      │
│ 14:05:12.345 [agent]     WARN  trc_abc  retry: rate_limit hit      │
│ 14:05:13.678 [worker_err] ERROR trc_abc  test failed: Login.test   │
│ 14:25:00.111 [recovery]  INFO  trc_abc  decision: return_to_coder  │
│ 14:25:01.234 [db_event]  INFO  trc_abc  packet_transition: ...     │
│ ...                                                                │
└────────────────────────────────────────────────────────────────────┘
```

### 13.4. Колонки и форматирование

- **Timestamp** — 24h формат `HH:MM:SS.mmm`, monospace, серый.
- **Source** — цветной бейдж (см. таблицу выше), в скобках `[source]`.
- **Level** — INFO/WARN/ERROR с цветным кружком (зелёный/жёлтый/красный).
- **Trace_id** — monospace, серый, короткий (первые 8 символов). Клик → фильтр по этому trace.
- **Message** — основной текст, моноширинный для логов, обычный для events. Длинные строки обрезаются с tooltip.

### 13.5. Real-time режим

По умолчанию вкладка работает в real-time: WebSocket пушит `stage_log_line` события (см. §10.1) для текущего `packet_id`, и они prepend-ятся в начало потока. Если оператор нажал «Freeze» — auto-scroll останавливается, новые строки накапливаются в буфере и показываются баннером «N new lines, click to load». Кнопка «Auto-scroll» обратно включает real-time.

### 13.6. Performance

Агрегированные логи могут быть огромными. Защита от перегрузки:

- **Tail-limit:** не больше 5000 строк на источник. Если source имеет больше — берутся последние 5000, остальное отсекается с пометкой `truncated:true`.
- **Streaming:** для больших ответов (>1MB) endpoint поддерживает HTTP streaming (`transfer-encoding: chunked`), клиент читает по мере поступления.
- **Cache на сервере:** результат кешируется 5 секунд по ключу `(packet_id, sources, tail, since, until)` — для случаев, когда оператор часто переключает фильтры.
- **Лимит параллельных запросов:** не больше 3 одновременных агрегированных запросов на сессию (semaphore).

### 13.7. Export

Кнопка «Export .log» — скачивает текущий отфильтрованный поток как plain-text файл. Имя файла: `aggregated_logs_pkt_XXXX_YYYYMMDD_HHMMSS.log`. Формат — тот же, что в UI, но без цветовых кодов.

---

## 14. UI: Артефакты по стадиям

Существующая вкладка Artifacts показывает дерево файлов из `evidence_dir`. Это работает, но не отвечает на вопрос «какие файлы принадлежат какой стадии». Это ТЗ расширяет вкладку: файлы группируются по стадии, которая их произвела. Источник группировки — `StageRun.artifacts_dir` и `StageRun.result_path` (см. §7).

### 14.1. Layout вкладки Artifacts

```
┌─ Artifacts ──────────────────────────────────────────────────────────┐
│ Group by: [Stage ▾] [Type] [Flat]            Total: 1.4 MB · 12 files│
├──────────────────────────────────────────────────────────────────────┤
│ ▼ Context Builder (srun_001) · 2 files · 24 KB                       │
│   📄 context_bundle.json     12 KB  [preview] [download]              │
│   📄 scope_manifest.json     12 KB  [preview] [download]              │
│ ▼ Architect (srun_002) · 1 file · 8 KB                               │
│   📄 plan.json               8 KB   [preview] [download]              │
│ ▼ Coder r1 (srun_005) · 4 files · 124 KB                             │
│   📄 stdout.log              18 KB  [tail 200] [download]             │
│   📄 stderr.log              2 KB   [preview] [download]              │
│   📄 agent.jsonl             88 KB  [preview] [download]              │
│   📋 diff.patch              16 KB  [preview] [download]              │
│ ▼ T1 unit tests (srun_006) · 1 file · 14 KB                          │
│   📄 test_report.json        14 KB  [preview] [download]              │
│ ▼ Verifier (srun_007) · 1 file · 6 KB                                │
│   📄 verifier_decision.json  6 KB   [preview] [download]              │
│ ▼ Coder r2 (srun_008) · 1 file · 95 KB                               │
│   📋 commit.patch            95 KB  [preview] [download]              │
│ ▼ Merge (srun_012) · 1 file · 1 KB                                   │
│   📄 merge_log.txt           1 KB   [preview] [download]              │
└──────────────────────────────────────────────────────────────────────┘
```

### 14.2. Группировка

По умолчанию артефакты группируются по стадии. Каждая группа — collapsible блок с заголовком: «Stage label (srun_XXX) · N files · SIZE». Внутри — список файлов с иконкой типа, размером, и кнопками `[preview] [download]`. Альтернативные группировки (через Group by переключатель):

- **Group by Stage** — по умолчанию, как описано выше.
- **Group by Type** — image / log / json / patch / file.
- **Flat** — простое дерево директорий (текущий режим, без группировки).

### 14.3. Smart rendering при preview

При клике `[preview]` файл открывается inline в модальном окне. Поведение зависит от типа файла (соответствует `TZ_ADMIN_PANEL.md`):

| Тип | Расширения | Inline preview | Только Download |
|---|---|---|---|
| Image | `.png .jpg .jpeg .gif .svg .webp` | Всегда `<img>` | — |
| Text/Log | `.log .txt .md` | Если < 1 MB → `<pre>` | Если ≥ 1 MB |
| JSON | `.json .jsonl .har` | Если < 1 MB → pretty-printed JSON | Если ≥ 1 MB |
| Patch/Diff | `.patch .diff` | Всегда `<pre>` с подсветкой `+`/`-` строк | — |
| Binary | остальное | Если < 256 KB → hex preview (256 байт) | Если ≥ 256 KB |

### 14.4. Endpoint

Новый endpoint: `GET /api/admin/packet/{id}/stages/{stage_key}/artifacts`. Возвращает:

```json
{
  "stage_key": "coder",
  "stage_run_id": "srun_005",
  "loop_round": 1,
  "artifacts": [
    {"name":"stdout.log", "path":"coder/stdout.log",
     "size":18432, "type":"log",
     "preview_url":"/api/admin/packet/.../artifacts/file?path=coder/stdout.log&tail=200"},
    {"name":"stderr.log", "path":"coder/stderr.log",
     "size":2048, "type":"log",
     "preview_url":"..."},
    {"name":"agent.jsonl", "path":"coder/agent.jsonl",
     "size":90112, "type":"json",
     "preview_url":"..."},
    {"name":"diff.patch", "path":"coder/diff.patch",
     "size":16384, "type":"patch",
     "preview_url":"..."}
  ],
  "total_size": 127008
}
```

### 14.5. Storage convention

Чтобы артефакты можно было группировать по стадии, instrumentation (§8) должна складывать файлы в поддиректории `evidence_dir` по `stage_key`. Конвенция:

```
<evidence_dir>/
  context_builder/
    context_bundle.json
    scope_manifest.json
  architect/
    plan.json
  materialize/
    (нет артефактов)
  executor/
    lease.json
  coder/
    stdout.log
    stderr.log
    agent.jsonl
    diff.patch
    commit.txt
  t1_unit_tests/
    test_report.json
  verifier/
    verifier_decision.json
  reviewer/
    reviewer_decision.json
  merge/
    merge_log.txt
    commit_sha.txt
```

`StageRun.artifacts_dir` указывает на соответствующую поддиректорию. `StageRun.result_path` — на главный файл результата (например, `verifier_decision.json`). Это позволяет UI не угадывать, какой файл главный, а сразу его подсвечивать.

---

## 15. UI: Метрики P50/P95

Новый раздел в навигации — **Metrics**. Сюда оператор заходит, чтобы понять, является ли текущий прогон стадии аномальным (например, coder идёт 30 минут, а P50 за неделю — 7 минут). Данные материализованы в таблице `stage_metrics` (см. §7.2), пересчёт — по cron.

### 15.1. Layout экрана Metrics

```
┌─ Stage Metrics ─────────────────────────────────────────────────────┐
│ Period: [24h] [7d] [30d]                  [Recalculate now]         │
├──────────────────────────────────────────────────────────────────────┤
│ ┌─ context_builder ──────────────────┐  ┌─ architect ──────────────┐│
│ │ P50: 00:15   P95: 00:42   n: 124  │  │ P50: 02:30   P95: 04:12  ││
│ │ success: 98%   cost: $0.012 avg   │  │ success: 96%   n: 89    ││
│ │ ▁▂▃▅▇▇▆▅▃▂▁                       │  │ ▁▂▃▄▅▆▇▆▅▄▃▂▁          ││
│ │ [view trend] [view histogram]     │  │ [view trend]            ││
│ └────────────────────────────────────┘  └──────────────────────────┘│
│ ┌─ coder ────────────────────────────┐  ┌─ verifier ───────────────┐│
│ │ P50: 07:20   P95: 14:55   n: 67   │  │ P50: 00:08   P95: 00:18  ││
│ │ success: 84%   cost: $0.042 avg   │  │ success: 91%   n: 67    ││
│ │ tokens: 12k in / 3k out avg       │  │ tokens: 5k in / 1k out  ││
│ │ idle: 45s avg (claim→start)       │  │ ▁▂▃▃▂▁                  ││
│ │ ▁▂▃▅▇▇▆▅▃▂▁                       │  │                          ││
│ └────────────────────────────────────┘  └──────────────────────────┘│
│ ...                                                                 │
├──────────────────────────────────────────────────────────────────────┤
│ Heatmap (стадия × час за 7d):                                       │
│        00  02  04  06  08  10  12  14  16  18  20  22               │
│ coder  ░░  ░░  ░░  ░░  ▓▓  ▓▓▓ ▓▓▓ ▓▓▓ ▓▓  ▓▓  ░░  ░░               │
│ arch   ░░  ░░  ░░  ░░  ▓   ▓▓  ▓▓  ▓   ▓   ░   ░░  ░░               │
│ ver    ░░  ░░  ░░  ░░  ░   ▓   ▓   ▓   ░   ░   ░░  ░░               │
└──────────────────────────────────────────────────────────────────────┘
```

### 15.2. Карточка стадии

Каждая карточка показывает:

- **Stage label** + иконку (LLM-стадия или нет).
- **P50 / P95 / avg / max / min** — длительность в `HH:MM:SS`.
- **count (n)** — количество прогонов за период.
- **success_rate** — процент успешных прогонов.
- **avg_tokens_in / avg_tokens_out** — для LLM-стадий.
- **avg_cost_usd / total_cost_usd** — для LLM-стадий.
- **avg_idle_seconds** — среднее время между claim и start (для executor/coder).
- **Мини-гистограмма** — распределение длительности (sparkline).
- Кнопки `[view trend]` (тренд P50/P95 по дням) и `[view histogram]` (полная гистограмма).

### 15.3. Таблица стоимости моделей

Для подсчёта `cost_usd` нужна таблица цен. Создаётся в `src/grace_control/config/model_pricing.py`:

```python
MODEL_PRICING = {
    # USD per 1M tokens (in, out)
    "deepseek/deepseek-v4-flash":      {"in": 0.14, "out": 0.28},
    "deepseek/deepseek-v4-pro":        {"in": 0.55, "out": 1.10},
    "anthropic/claude-sonnet-4-5":     {"in": 3.00, "out": 15.00},
    "anthropic/claude-opus-4-1":       {"in": 15.00, "out": 75.00},
    "openai/gpt-4o":                   {"in": 2.50, "out": 10.00},
    "openai/gpt-4o-mini":              {"in": 0.15, "out": 0.60},
}

def compute_cost(model: str, tokens_in: int, tokens_out: int) -> float:
    pricing = MODEL_PRICING.get(model, {"in": 0, "out": 0})
    return (tokens_in / 1_000_000) * pricing["in"] + \
           (tokens_out / 1_000_000) * pricing["out"]
```

Таблица обновляется вручную при выходе новых моделей. Unknown модели дают `cost_usd=0` (не падаем).

### 15.4. Heatmap «стадия × час»

Показывает, когда какие стадии тормозят. Цвет ячейки = avg duration (темнее = дольше). Это помогает выявить, например, что coder долго в пиковые часы (потому что LLM-rate-limit), и планировать запуск тяжёлых пакетов на ночь.

### 15.5. Cron пересчёта

Пересчёт `stage_metrics` запускается через APScheduler (или через stuck_scanner-подобный background task):

- Каждую минуту — пересчёт периода `24h` (rolling).
- Каждый час — пересчёт периода `7d`.
- Каждый день в 00:00 UTC — пересчёт периода `30d`.

Кнопка «Recalculate now» в UI — запускает пересчёт всех периодов синхронно (для отладки или после восстановления из бэкапа).

---

## 16. UI: Контрольные действия

Этот раздел собирает все контрольные действия в одном месте: что делает каждая кнопка, какие endpoints вызывает, какой state transition инициирует, что пишет в audit log.

### 16.1. Кнопки и их условия

| Кнопка | Где в UI | Когда активна | Endpoint | State transition |
|---|---|---|---|---|
| **Retry** | Packet header | `state ∈ {BLOCKED_RECOVERABLE, REJECTED}` | `POST /api/admin/packet/{id}/retry` | `BLOCKED_RECOVERABLE → READY` |
| **Cancel** | Packet header | `state = RUNNING` | `POST /api/admin/packet/{id}/cancel` | `RUNNING → CANCELLED` |
| **Delete** | Packet header (в menu) | `state ∈ terminal states` (`MERGED`, `FAILED`, `REJECTED`, `BLOCKED_FINAL`, `CANCELLED`) | `POST /api/admin/packet/{id}/delete` | удаляет packet |
| **Re-run stage** | Stage card (только `verifier`/`reviewer`) | `state ∈ terminal` или `state = RUNNING` (тогда нужна confirm «Stage will be re-run after current») | `POST /api/admin/packet/{id}/stages/{stage_key}/rerun` | создаёт новый `StageRun` с `loop_round+1` |
| **Stop worker** | System > Workers | worker `status = active` | `POST /api/admin/workers/{worker_id}/stop` | `worker.status = stopped`, lease освобождается |
| **Dev-replay** | Stage card | любой state | `POST /api/admin/packet/{id}/dev-replay` | использует существующий `dev_replay` router |

### 16.2. Confirm dialog

Каждая кнопка открывает confirm dialog:

```
┌─ Confirm action ──────────────────────────────┐
│ Action:   Retry packet                         │
│ Packet:   pkt_T4V9K2mA1b                       │
│ State:    BLOCKED_RECOVERABLE                  │
│ Effect:   Packet will be returned to READY     │
│           queue. attempt_count: 2 → 3.         │
│ Reason:   [_________________________]          │
│                                                │
│              [Cancel]  [Confirm]               │
└────────────────────────────────────────────────┘
```

Для `delete` — дополнительное поле `confirm_id`, в которое нужно ввести `packet_id` (защита от случайного удаления).

### 16.3. Audit log

После выполнения действия:

- Создаётся `Event` с `event_type='admin_action'`, `entity_type='packet'` (или `worker`), `entity_id=...`.
- В `payload_json` пишется: `{action, actor (из auth), reason, before_state, after_state, at}`.
- В `recent_events` в правой колонке админки — новое событие появляется с пометкой «admin action».
- В WebSocket — бродкастится `state_change` (если изменился state) или `worker_status_change`.

### 16.4. Toast notifications

После выполнения действия показывается toast:

- Успех: «Packet pkt_T4V9K2mA1b retried. New state: READY.» (зелёный, 5s).
- Ошибка: «Failed to retry: <error message>» (красный, пока не закроют).
- В прогрессе: «Cancelling packet... waiting for worker to stop (30s timeout)» (жёлтый, пока не завершится).

### 16.5. Ограничения и safety

- `delete` требует ввода `packet_id` в confirm dialog (защита от misclick).
- `cancel` сначала graceful (30s), потом force-kill — оператор видит прогресс.
- `rerun` stage работает только для `verifier`/`reviewer` — нельзя «rerun» coder без перепрогона всей цепочки (это изменило бы state machine).
- `stop worker` не работает, если worker сейчас исполняет packet в критической стадии (coder с `started_at < 5 min ago`) — нужно подтвердить «Force stop even if coding».

---

## 17. UI: Recovery chain visualization

Отдельная визуализация всех возвратов пакета. Появляется в packet detail под stage cards, если `loop_count > 0`. Это не просто список, а flow diagram, показывающая причинно-следственные связи.

### 17.1. Flow diagram

```
┌─ Recovery Chain ─────────────────────────────────────────────────────┐
│                                                                      │
│  ┌─────┐    ┌──────┐    ┌─────┐    ┌──────┐    ┌─────┐    ┌──────┐  │
│  │coder│───▶│  T1  │───▶│ ver │═══▶│coder │───▶│  T1 │───▶│ ver  │  │
│  │ r1  │    │tests │    │ r1  │    │ r2   │    │tests│    │ r2   │  │
│  └─────┘    └──────┘    └─────┘    └──────┘    └─────┘    └──────┘  │
│                            │                                          │
│                            │ reason:                                  │
│                            │ "evidence missing T1"                    │
│                            │ decision: recovery_return_to_coder       │
│                            │ at: 14:25:00                             │
│                            ▼                                          │
│                       (return arrow)                                  │
│                                                                      │
│  Decisions table:                                                    │
│  ┌─────────────┬───────────┬───────────┬──────────────────────────┐  │
│  │ at          │ from → to │ reason    │ decision                 │  │
│  ├─────────────┼───────────┼───────────┼──────────────────────────┤  │
│  │ 14:25:00.123│ver→coder  │evidence m.│recovery_return_to_coder  │  │
│  │             │           │issing T1  │                          │  │
│  └─────────────┴───────────┴───────────┴──────────────────────────┘  │
└──────────────────────────────────────────────────────────────────────┘
```

### 17.2. Узлы и стрелки

- **Узлы стадии** — карточки с `stage_key` + `loop_round` (например, «coder r1»).
- **Сплошная стрелка →** — нормальный переход (success path).
- **Пунктирная стрелка ═══▶** — возврат (recovery loop), красная, с подписью причины.
- **Цвет узла** — по статусу: green (done), red (failed), gray (skipped).
- **Click на узле** — скроллит к соответствующей stage card в Stage Timeline.

### 17.3. Decisions table

Под diagram — таблица всех recovery decisions:

| Колонка | Пример | Описание |
|---|---|---|
| `at` | `14:25:00.123` | Timestamp (24h с ms) |
| `from → to` | `verifier → coder` | Из какой стадии в какую вернулись |
| `reason` | `evidence missing T1` | Полный текст причины из `result_json.recovery.reason` |
| `decision` | `recovery_return_to_coder` | Имя decision из `RECOVERY_EVENTS` |
| `loop_round` | `2` | В какой round перешли |
| `event_id` | `evt_12345` | Ссылка на `Event` (клик → открывает event detail) |
| `trace_id` | `trc_abc123def` | Ссылка на aggregated logs с фильтром по этому trace |

### 17.4. Источник данных

- `Event` table, `event_type LIKE 'recovery_%'`, `entity_id = packet_id`.
- `StageRun` с `loop_round > 1` и `parent_stage_run_id IS NOT NULL`.
- Эти два источника склеиваются по `trace_id` и `timestamp`.

### 17.5. Empty state

Если у пакета не было возвратов, секция скрыта. В её месте — короткая подпись: «No recovery loops for this packet».

---

## 18. UI: Workers и Supervisor

Страница `/admin/system` расширяется: сейчас она показывает только список workers с basic-инфо, а должна показывать текущую стадию каждого worker-а, health-checks, и давать контрольные действия.

### 18.1. Layout страницы System

```
┌─ System ───────────────────────────────────────────────────────────┐
│ Health: supervisor ✓ | api ✓ | db ✓ | code_sha: abc1234            │
├─────────────────────────────────────────────────────────────────────┤
│ Workers (3 active, 1 stopped)                                       │
│                                                                     │
│ ┌─ wkr_abc ────────────────────────────────────────────────────┐   │
│ │ status: ●active  packet: pkt_T4V9K2mA1b  stage: coder (r1)   │   │
│ │ started: 14:00:00  elapsed: 07:23  last_hb: 2s ago           │   │
│ │ lease: expires 14:32:00 (5 min left)                         │   │
│ │ heartbeat health: ●●●●● (good)                               │   │
│ │                                            [Stop worker]     │   │
│ └──────────────────────────────────────────────────────────────┘   │
│ ┌─ wkr_def ────────────────────────────────────────────────────┐   │
│ │ status: ●active  packet: pkt_P3X9K8mB2c  stage: verifier     │   │
│ │ ...                                                          │   │
│ └──────────────────────────────────────────────────────────────┘   │
├─────────────────────────────────────────────────────────────────────┤
│ Stuck packets (1)                              [Force cancel all]  │
│ ┌─ pkt_Q1Y2Z4nD8f ────────────────────────────────────────────┐    │
│ │ state: RUNNING  started: 13:00:00  no heartbeat for 12 min  │    │
│ │ worker: wkr_xyz (last_hb 12m ago)                           │    │
│ │ reason: stuck_scanner flagged                               │    │
│ │                                  [Force cancel] [Stop worker]│    │
│ └─────────────────────────────────────────────────────────────┘    │
├─────────────────────────────────────────────────────────────────────┤
│ Supervisor logs (live)                                             │
│ [14:00:00] starting worker wkr_abc                                 │
│ [14:00:01] wkr_abc claimed pkt_T4V9K2mA1b                          │
│ [14:05:00] wkr_abc heartbeat ok                                    │
│ ...                                                                │
└─────────────────────────────────────────────────────────────────────┘
```

### 18.2. Карточка worker-а

Каждый worker показывает:

- **status** — `active` / `stopped` / `crashed` с цветным кружком.
- **current_packet_id** + **current_stage_key** (из `stage_runs` где `worker_id` и `status='running'`).
- **started_at** + **elapsed** — когда воркер начал текущий packet, сколько уже идёт (живой elapsed).
- **last_heartbeat** + age (например, «2s ago», «45s ago», «5m ago»).
- **lease_expires_at** — когда lease истечёт, и сколько осталось.
- **heartbeat health** — 5 последних heartbeat-ов в виде точек (зелёная = < 10s, жёлтая = < 60s, красная = > 60s).
- Кнопка **[Stop worker]** — с confirm dialog.

### 18.3. Stuck packets

Список пакетов, которые `stuck_scanner` отметил как зависшие (state `RUNNING`, но `last_heartbeat` старше порога). Для каждого:

- `packet_id`, `started_at`, «no heartbeat for N min».
- `worker_id` (с last_hb age).
- reason из `stuck_scanner` (например, «lease expired but state still RUNNING»).
- Кнопки **[Force cancel]** (принудительный cancel без ожидания worker-а) и **[Stop worker]**.

### 18.4. Supervisor logs

Live-stream из `process_supervisor`. Показывает последние N строк (50 по умолчанию), auto-scroll. Источник: `/tmp/supervisor.log` или stderr supervisor-а (зависит от конфигурации). Можно расширить существующий `GET /api/admin/system/logs` параметром `source=supervisor`.

### 18.5. WebSocket обновления

- `worker_heartbeat` event обновляет `last_heartbeat` и health-точки без полной перезагрузки.
- `stage_started` / `stage_finished` обновляют `current_stage_key` соответствующего worker-а.
- `state_change` (для packet) может убрать packet из списка stuck.

---

## 19. Mobile layout

Responsive single-page, breakpoints 900/600. Соответствует `TZ_MISSION_CONTROL.md`.

### 19.1. Desktop (≥1100px)

Полный трёхколоночный layout, как описано в §11. Все элементы видны одновременно.

### 19.2. Tablet (600-1100px)

- Features tree сворачивается в drawer (открывается по кнопке-гамбургеру в шапке).
- Stats bar остаётся, но compact.
- Gantt занимает всю ширину.
- Right колонка (workers/blocked/recent events) уходит вниз, под Gantt.
- Packet detail: header compact, Stage Timeline — горизонтальный скролл, stage cards — одна колонка.

### 19.3. Mobile (<600px)

- Stats bar — только 3 ключевых метрики (Running, Blocked, Failed), остальные в expandable section.
- Features tree — drawer с overlay.
- Gantt — горизонтальный скролл (zoom по умолчанию 1h, можно менять пинчем).
- Packet detail:
  - Header compact (id, state, retry/cancel buttons в виде иконок).
  - Stage Timeline — горизонтальный скролл.
  - Stage cards — одна колонка, компактные.
  - Tabs уходят в **bottom navigation bar** (Timeline, Pipeline, Logs, Artifacts, More).
  - Recovery chain — отдельная секция под Stage Timeline.
- Aggregated Logs — fullscreen, фильтры в collapsible panel сверху.
- Контрольные действия — floating action button (FAB) справа внизу.

### 19.4. Touch-оптимизация

- Минимальный tap-target: 44×44px (соответствие iOS HIG).
- Hover-эффекты заменяются на active-состояния (для тача).
- Long-press на баре стадии — показывает tooltip с деталями.
- Swipe left/right на Stage Timeline — переключение между packet-ами одной волны.

### 19.5. Test viewports

Должно работать на:

- 390×844 (iPhone 14)
- 430×932 (iPhone 14 Pro Max)
- 768×1024 (iPad Mini)
- 1440×900 (laptop)

---

## 20. Тесты

Стратегия тестирования — соответствует `docs/TZ_FRONTEND_ACCEPTANCE.md`, расширяется под новые компоненты.

### 20.1. Backend unit-тесты

- **Новые endpoints** (см. §9) — тесты в `tests/grace_control/api/test_admin_pipeline.py`. Каждый endpoint: happy path + 404 + edge cases.
- **StageRun CRUD** — `tests/grace_control/services/test_stage_run_service.py`. Создание, обновление статусов, parent→child связи для loops.
- **Декоратор `@stage()`** — `tests/grace_control/core/test_stage_instrumentation.py`. Проверка: создаёт `StageRun`, эмитит WS events, обрабатывает success/failure.
- **Миграции** — `tests/grace_control/db/test_migrations.py` расширяется проверкой `0010_stage_runs.py` и `0011_stage_metrics.py` на idempotency.
- **LLM cost tracking** — `tests/grace_control/runtime/test_opencode_event_collector.py` расширяется проверкой суммирования usage.
- **Model pricing** — `tests/grace_control/config/test_model_pricing.py` — все известные модели дают cost > 0, unknown модели дают 0.

### 20.2. Frontend smoke tests

- **HTML template smoke** — `tests/ui/test_admin_ui_pipeline_templates.py`. Рендеринг `_gantt.html`, `detail/_pipeline.html`, `tabs/_aggregated_logs.html` не падает с тестовыми данными.
- **JS syntax check** — `node --check` для всех новых `.js` файлов (как в существующем CI).
- **CSS sanity** — нет синтаксических ошибок в новых `.css` файлах.

### 20.3. API contract tests

- `tests/grace_control/api/test_admin_pipeline_contract.py` — фиксирует response shape всех новых endpoints. Любое изменение сигнатуры требует обновления контракта.
- Использует `tests/grace_control/api/test_openapi_paths.py` для проверки, что OpenAPI spec не сломан.

### 20.4. Playwright E2E

Новые тесты в `tests/ui/test_admin_pipeline_e2e.py`:

- **Gantt renders** — открыть feature, увидеть Gantt с барами стадий.
- **Stage Timeline opens** — клик на packet, увидеть Stage Timeline + cards.
- **Recovery chain visible** — открыть packet с loops, увидеть стрелку возврата.
- **Aggregated Logs filter works** — переключить source checkboxes, увидеть фильтрацию.
- **Stage Artifacts grouped** — открыть Artifacts, увидеть группировку по стадии.
- **Metrics screen renders** — открыть Metrics, увидеть карточки с P50/P95.
- **Mobile viewport (390×844)** — все экраны без horizontal scroll, bottom tabs работают.
- **Console error gate** — fail при `pageerror` или `console.error` (как сейчас).
- **Realtime WS** —模拟 stage_started event, проверить что Stage Timeline обновился.

### 20.5. Performance tests

- **Gantt рендерит 100 пакетов** за < 500ms (измерение в Playwright).
- **Aggregated Logs с tail=5000** загружается за < 2s.
- **Stage Timeline с 20 стадиями (10 loops)** рендерится за < 200ms.
- **Metrics пересчёт для 10 000 stage_runs** — < 5s.

### 20.6. CI gate

Расширение существующего CI (`.github/workflows/`):

1. Backend tests (pytest) — все тесты зелёные.
2. JS syntax check — `node --check` на всех `.js`.
3. HTML template smoke tests.
4. API contract tests.
5. Playwright smoke (desktop 1440×900).
6. Playwright mobile (390×844).
7. Pipeline E2E (Gantt + Stage Timeline + Recovery Chain + Aggregated Logs + Metrics).
8. Coverage gate — ≥ 80% на новом коде.

---

## 21. План реализации — эпики

Разбивка на 6 эпиков. Каждый эпик — отдельный PR (или последовательность PR-ов). Эпики можно делать параллельно, кроме зависимостей.

### E1. Schema + migrations + instrumentation

**Scope:** добавить `StageRun`, `StageMetric` таблицы; декоратор `@stage()`; обернуть 12 функций стадий; LLM cost tracking; model_pricing.

**Files:**
- `src/grace_control/db/schema.py` — добавить `StageRun`, `StageMetric`.
- `db/migrations/0010_stage_runs.py`, `0011_stage_metrics.py`, `0012_packetrun_llm_cost.py`.
- `src/grace_control/core/stage_instrumentation.py` — новый.
- `src/grace_control/config/model_pricing.py` — новый.
- `src/grace_control/services/feature_planning_service.py` — обернуть `run_context_builder`, `run_architect`.
- `src/grace_control/services/packet_materializer.py` — обернуть `materialize`.
- `src/grace_control/services/packet_service.py` — обернуть `claim`.
- `src/grace_control/adapters/packet_executor.py` — обернуть `execute`, прокинуть LLM usage.
- `src/grace_control/core/acceptance_pipeline.py` — обернуть `run_t0/t1/t2`.
- `src/grace_control/core/evidence_verifier.py` — обернуть `run_evidence_verifier`.
- `src/grace_control/core/reviewer_gate.py` — обернуть `run_reviewer_gate`.
- `src/grace_control/services/merge_service.py` — обернуть `merge_packet`.
- `src/grace_control/core/recovery_controller.py` — создавать `StageRun` с `loop_round+1` при return-решениях.
- `src/grace_control/runtime/opencode_event_collector.py` — суммировать usage.

**Estimate:** 4-5 дней.

**Dependencies:** нет.

**Acceptance:**
- Все 12 стадий создают `StageRun` записи.
- Возвраты создают `StageRun` с правильным `loop_round` и `parent_stage_run_id`.
- LLM-стадии пишут `tokens_in`/`tokens_out`/`cost_usd`.
- Все существующие тесты остаются зелёными.

### E2. API endpoints

**Scope:** реализовать все новые read endpoints (см. §9.1) и control endpoints (см. §9.2). Расширить существующие endpoints новыми полями (см. §9.3).

**Files:**
- `src/grace_control/api/routers/admin.py` — расширить, заменить stub-ы.
- `src/grace_control/api/routers/admin_pipeline.py` — новый роутер для pipeline/gantt/aggregated-logs/stage-artifacts.
- `src/grace_control/services/admin_aggregation_service.py` — расширить: `get_pipeline`, `get_gantt`, `get_aggregated_logs`, `get_stage_artifacts`, `get_stage_metrics`.
- `src/grace_control/services/aggregated_logs_service.py` — новый, читает 7 источников и склеивает.
- `src/grace_control/services/stage_metrics_service.py` — новый, читает/пересчитывает `stage_metrics`.
- `src/grace_control/services/packet_control_service.py` — новый, реализует retry/cancel/delete/rerun.

**Estimate:** 5-6 дней.

**Dependencies:** E1 (нужны `StageRun` данные).

**Acceptance:**
- Все endpoints из §9 отвечают 200 на тестовых данных.
- Contract tests (§20.3) зелёные.
- Control endpoints пишут audit events.

### E3. WebSocket события

**Scope:** расширить `ws_broadcast.py` новыми event types; добавить эмит из декоратора `@stage()`.

**Files:**
- `src/grace_control/api/ws_broadcast.py` — новые broadcast-функции: `broadcast_stage_started`, `broadcast_stage_finished`, `broadcast_stage_log_line`, `broadcast_stage_artifact_added`, `broadcast_stage_returned`, `broadcast_worker_heartbeat`, `broadcast_metrics_updated`.
- `src/grace_control/core/stage_instrumentation.py` — вызывать broadcast-функции (из E1).
- `src/grace_control/worker/worker.py` — эмитить `worker_heartbeat` раз в 10s.
- `src/grace_control/core/stuck_scanner.py` — эмитить `worker_stuck` (новый event type).

**Estimate:** 2-3 дня.

**Dependencies:** E1 (декоратор `@stage()`).

**Acceptance:**
- Все новые event types эмитятся и ловятся клиентом.
- Backoff и reconnect работают (тест с обрывом WS).

### E4. UI: Feature Pipeline Gantt

**Scope:** главная страница `/admin` с Gantt-таймлайном фичи.

**Files:**
- `src/grace_control/ui/templates/admin/_gantt.html` — новый.
- `src/grace_control/ui/templates/admin/console.html` — расширить: подключить `_gantt.html` в центральной колонке.
- `src/grace_control/ui/static/css/gantt.css` — новый.
- `src/grace_control/ui/static/admin.js` — WS-обработчики для Gantt refresh.
- `src/grace_control/api/routers/admin_ui.py` — новый partial `/admin/_partial/gantt`.

**Estimate:** 4-5 дней.

**Dependencies:** E2 (gantt endpoint), E3 (WS events).

**Acceptance:**
- Gantt рендерит пакеты фичи с барами стадий.
- Zoom 1h/6h/24h/7d работает.
- Возвраты показываются стрелками.
- Real-time обновление через WS.

### E5. UI: Packet Detail (Stage Timeline + Recovery Chain + Aggregated Logs + Stage Artifacts)

**Scope:** расширить packet detail: Stage Timeline, Stage cards, Recovery Chain, Aggregated Logs tab, переработанная Artifacts tab.

**Files:**
- `src/grace_control/ui/templates/admin/detail/_pipeline.html` — новый.
- `src/grace_control/ui/templates/admin/detail/_recovery_chain.html` — новый.
- `src/grace_control/ui/templates/admin/detail/_stage_card.html` — новый.
- `src/grace_control/ui/templates/admin/tabs/_aggregated_logs.html` — новый.
- `src/grace_control/ui/templates/admin/tabs/_artifacts.html` — расширить (группировка по стадии).
- `src/grace_control/ui/templates/admin/_detail.html` — расширить.
- `src/grace_control/ui/static/css/pipeline.css`, `recovery_chain.css`, `aggregated_logs.css` — новые.
- `src/grace_control/ui/static/admin.js` — WS-обработчики для stage events, log streaming.
- `src/grace_control/api/routers/admin_ui.py` — новые partials для stage cards, recovery chain, aggregated logs.

**Estimate:** 6-7 дней.

**Dependencies:** E2 (endpoints), E3 (WS events), E4 (общий CSS/JS).

**Acceptance:**
- Stage Timeline показывает все стадии с timing.
- Stage cards кликабельны, открывают логи/артефакты.
- Recovery chain показывает arrows + decisions table.
- Aggregated Logs фильтрует по source/level/trace_id/regex.
- Artifacts сгруппированы по стадии.

### E6. UI: Metrics + Workers + Mobile

**Scope:** экран Metrics, расширение System (workers + stuck + supervisor logs), mobile layout для всех новых экранов.

**Files:**
- `src/grace_control/ui/templates/admin/metrics.html` — новый.
- `src/grace_control/ui/templates/admin/system.html` — расширить.
- `src/grace_control/ui/static/css/metrics.css`, `system.css`, `mobile.css` — новые/расширить.
- `src/grace_control/ui/static/admin.js` — heatmap rendering, mobile navigation.
- `src/grace_control/services/stage_metrics_service.py` — cron пересчёт (из E2).
- `src/grace_control/core/cron.py` или расширение `stuck_scanner` — cron scheduling.

**Estimate:** 4-5 дней.

**Dependencies:** E2 (metrics endpoint), E4/E5 (общий layout).

**Acceptance:**
- Metrics показывает P50/P95/heatmap.
- Workers показывает current_stage + heartbeat health + stop button.
- Mobile layout работает на 390×844 и 768×1024.

### Сводная таблица

| Эпик | Estimate | Dependencies | Параллельность |
|---|---|---|---|
| E1 — Schema + instrumentation | 4-5 дней | — | Сначала |
| E2 — API endpoints | 5-6 дней | E1 | После E1 |
| E3 — WebSocket | 2-3 дня | E1 | Параллельно с E2 |
| E4 — Feature Gantt UI | 4-5 дней | E2, E3 | После E2/E3 |
| E5 — Packet Detail UI | 6-7 дней | E2, E3, E4 | После E4 |
| E6 — Metrics + Workers + Mobile | 4-5 дня | E2, E4, E5 | После E5 |
| **Итого** | **25-31 день** | | |

---

## 22. Риски и открытые вопросы

### 22.1. Риски

| # | Риск | Mitigation |
|---|---|---|
| R1 | SQLite может не вытянуть 100+ пакетов на Gantt с stages — тормозит запрос | Пагинация: Gantt показывает 20 пакетов на странице. Lazy-load следующих при скролле. Кеш на 5s. |
| R2 | Агрегированные логи могут быть огромными (worker stdout > 100MB) | Tail-limit 5000 строк на источник. Streaming. Cache 5s. Semaphore на 3 concurrent. |
| R3 | Instrumentation существующего кода может сломать текущие тесты | Декоратор `@stage()` написан так, что если `StageRun` создание падает, ошибка логируется, но не пробрасывается — стадия продолжает работать. |
| R4 | Re-run stage может нарушить state machine | Re-run работает только для verifier/reviewer (terminal stages). Для coder — через retry всего пакета. |
| R5 | Метрики P50/P95 требуют достаточной выборки — на старте будут неточные | Показывать «low sample (n<10)» warning рядом с метрикой. Не показывать P95 если n<20. |
| R6 | WebSocket broadcast может стать bottleneck-ом при 100+ подписчиков | Текущая реализация — in-memory list. На 100+ подписчиков нужен Redis pub/sub. За пределами этого ТЗ. |
| R7 | Migration `0010_stage_runs.py` может затормозить на большой БД | `CREATE TABLE` — быстро. Индексы создаются после. На 1M rows — секунды. |
| R8 | Cron пересчёт metrics может конфликтовать с ad-hoc «Recalculate now» | Mutex на пересчёт. Если cron запущен, ad-hoc ждёт или возвращает 409. |

### 22.2. Открытые вопросы

| # | Вопрос | Вариант | Решение |
|---|---|---|---|
| Q1 | Кто крутит cron для `stage_metrics`? | (a) APScheduler в процессе API; (b) отдельный supervisor-child; (c) systemd timer | (a) — проще, соответствует существующей архитектуре. |
| Q2 | Как хранить логи >1MB? | (a) в файлах (как сейчас); (b) сжимать старые; (c) отдельная таблица | (a) + (b) — retention политикой удалять/сжимать старше 7 дней. |
| Q3 | Нужен ли retention для `stage_runs`? | Удалять старше 30 дней, или хранить вечно? | Хранить вечно до отдельного ТЗ по retention (уже есть `TZ_RETENTION_POLICY.md`). |
| Q4 | Trace_id есть не у всех events — что показывать в aggregated logs? | Для events без trace_id — пустое поле. | OK. |
| Q5 | Как тестировать instrumentation без реального LLM? | Mock-agent в `tests/fixtures/` + golden fixtures. | OK, в репо уже есть golden fixtures. |
| Q6 | WebSocket filter (§10.5) — реализовывать в v1 или v1.1? | v1.1, чтобы не усложнять первый релиз. | OK. |
| Q7 | Heatmap Metrics — рисовать на сервере (PNG) или на клиенте (CSS-grid)? | CSS-grid — проще, не требует matplotlib. | OK. |
| Q8 | Mobile bottom tabs — заменяют ли они desktop tabs? | Нет, desktop tabs остаются горизонтальными. Bottom tabs — только на mobile. | OK. |

---

## 23. Приложения

### Приложение A. Глоссарий терминов

| Термин | Определение |
|---|---|
| **Packet** | Самостоятельная единица работы в оркестраторе. Создаётся архитектором, исполняется worker-ом, проходит через pipeline стадий. |
| **Wave** | Группа пакетов, исполняемых последовательно. Принадлежит фиче. |
| **Feature** | Топ-level бизнес-фича. Декомпозируется архитектором на waves и packets. |
| **PacketRun** | Одна попытка исполнения пакета. Создаётся при claim, завершается при success/fail. |
| **StageRun** (NEW) | Один запуск одной стадии пакета. Если был loop — несколько `StageRun` с разными `loop_round`. |
| **Stage** | Этап pipeline: `context_builder`, `architect`, `coder`, `verifier`, `reviewer`, `merge` и т.д. (см. §4.1). |
| **Attempt** | Номер попытки пакета (увеличивается при retry). |
| **Loop round** (NEW) | Номер круга стадии (увеличивается при возврате из verifier/reviewer). |
| **Trace ID** | Сквозной идентификатор, связывающий все events/runs одного исполнения. |
| **Lease** | Эксклюзивная заявка worker-а на packet, с fencing token. Истекает через N минут. |
| **Acceptance profile** | `FAST` / `NORMAL` / `STRICT` — определяет, какие стадии запускаются (см. §4.3). |
| **Recovery** | Решение `recovery_controller` о том, что делать с упавшим пакетом: retry, switch executor, return to architect, block. |
| **Worker** | Процесс, исполняющий packets. Регулярно шлёт heartbeat. |
| **Supervisor** | Процесс, управляющий workers (spawn, restart, cleanup). |
| **Evidence** | Артефакты стадии coder + T0/T1/T2 — то, что verifier проверяет. |
| **Stage metric** (NEW) | Агрегат P50/P95/avg/max/count по типу стадии за период. |

### Приложение B. Существующие admin endpoints (для reference)

См. §5.2 — полный список реализованных endpoints.

### Приложение C. Примеры JSON-пейлоадов для новых WebSocket событий

#### `stage_started`

```json
{
  "type": "stage_started",
  "packet_id": "pkt_T4V9K2mA1b",
  "stage_key": "coder",
  "stage_run_id": "srun_005",
  "attempt": 1,
  "loop_round": 1,
  "started_at": "2026-06-25T10:05:00Z",
  "executor_id": "coder-deepseek-v4-flash",
  "model": "deepseek/deepseek-v4-flash"
}
```

#### `stage_finished` (успех)

```json
{
  "type": "stage_finished",
  "packet_id": "pkt_T4V9K2mA1b",
  "stage_key": "coder",
  "stage_run_id": "srun_005",
  "status": "done",
  "finished_at": "2026-06-25T10:12:00Z",
  "duration_ms": 420000,
  "tokens_in": 12000,
  "tokens_out": 3000,
  "cost_usd": 0.042
}
```

#### `stage_finished` (ошибка)

```json
{
  "type": "stage_finished",
  "packet_id": "pkt_T4V9K2mA1b",
  "stage_key": "verifier",
  "stage_run_id": "srun_007",
  "status": "failed",
  "finished_at": "2026-06-25T10:25:09Z",
  "duration_ms": 9000,
  "error": "evidence missing T1 unit_tests report"
}
```

#### `stage_returned`

```json
{
  "type": "stage_returned",
  "packet_id": "pkt_T4V9K2mA1b",
  "from_stage": "verifier",
  "to_stage": "coder",
  "reason": "evidence missing T1",
  "decision": "recovery_return_to_coder",
  "loop_round": 2,
  "parent_stage_run_id": "srun_007",
  "at": "2026-06-25T10:25:00Z"
}
```

#### `stage_log_line`

```json
{
  "type": "stage_log_line",
  "packet_id": "pkt_T4V9K2mA1b",
  "stage_key": "coder",
  "source": "agent",
  "line": "tool_call: write_file(src/hello.py)",
  "level": "info",
  "ts": "2026-06-25T10:06:23.456Z",
  "trace_id": "trc_abc123def"
}
```

#### `stage_artifact_added`

```json
{
  "type": "stage_artifact_added",
  "packet_id": "pkt_T4V9K2mA1b",
  "stage_key": "t2_e2e_smoke",
  "path": "t2_e2e_smoke/screenshots/login.png",
  "size": 184320,
  "type": "image"
}
```

#### `worker_heartbeat`

```json
{
  "type": "worker_heartbeat",
  "worker_id": "wkr_abc",
  "current_packet_id": "pkt_T4V9K2mA1b",
  "current_stage_key": "coder",
  "last_heartbeat": "2026-06-25T10:10:00Z",
  "lease_expires_at": "2026-06-25T10:32:00Z"
}
```

#### `metrics_updated`

```json
{
  "type": "metrics_updated",
  "stage_keys": ["coder", "verifier", "architect"],
  "period": "24h",
  "computed_at": "2026-06-25T10:15:00Z"
}
```

### Приложение D. Список файлов репозитория, которые будут изменены

**Новые файлы:**

- `src/grace_control/db/schema.py` — дополнения (классы `StageRun`, `StageMetric`).
- `src/grace_control/core/stage_instrumentation.py` — новый.
- `src/grace_control/config/model_pricing.py` — новый.
- `src/grace_control/services/aggregated_logs_service.py` — новый.
- `src/grace_control/services/stage_metrics_service.py` — новый.
- `src/grace_control/services/packet_control_service.py` — новый.
- `src/grace_control/api/routers/admin_pipeline.py` — новый роутер.
- `db/migrations/0010_stage_runs.py` — новый.
- `db/migrations/0011_stage_metrics.py` — новый.
- `db/migrations/0012_packetrun_llm_cost.py` — новый.
- `src/grace_control/ui/templates/admin/_gantt.html` — новый.
- `src/grace_control/ui/templates/admin/metrics.html` — новый.
- `src/grace_control/ui/templates/admin/detail/_pipeline.html` — новый.
- `src/grace_control/ui/templates/admin/detail/_recovery_chain.html` — новый.
- `src/grace_control/ui/templates/admin/detail/_stage_card.html` — новый.
- `src/grace_control/ui/templates/admin/tabs/_aggregated_logs.html` — новый.
- `src/grace_control/ui/static/css/gantt.css` — новый.
- `src/grace_control/ui/static/css/pipeline.css` — новый.
- `src/grace_control/ui/static/css/recovery_chain.css` — новый.
- `src/grace_control/ui/static/css/aggregated_logs.css` — новый.
- `src/grace_control/ui/static/css/metrics.css` — новый.
- `src/grace_control/ui/static/css/mobile.css` — новый.
- `tests/grace_control/api/test_admin_pipeline.py` — новый.
- `tests/grace_control/api/test_admin_pipeline_contract.py` — новый.
- `tests/grace_control/services/test_stage_run_service.py` — новый.
- `tests/grace_control/services/test_aggregated_logs_service.py` — новый.
- `tests/grace_control/services/test_stage_metrics_service.py` — новый.
- `tests/grace_control/services/test_packet_control_service.py` — новый.
- `tests/grace_control/core/test_stage_instrumentation.py` — новый.
- `tests/grace_control/config/test_model_pricing.py` — новый.
- `tests/ui/test_admin_pipeline_templates.py` — новый.
- `tests/ui/test_admin_pipeline_e2e.py` — новый.

**Изменяемые файлы:**

- `src/grace_control/db/schema.py` — добавить `StageRun`, `StageMetric`, расширить `PacketRun`.
- `src/grace_control/api/routers/admin.py` — заменить stub-ы на реальные реализации, добавить новые endpoints.
- `src/grace_control/api/routers/admin_ui.py` — добавить partials для Gantt, Stage Timeline, Recovery Chain.
- `src/grace_control/api/ws_broadcast.py` — новые broadcast-функции.
- `src/grace_control/services/admin_aggregation_service.py` — расширить `get_pipeline`, добавить `get_gantt`, `get_aggregated_logs`, `get_stage_artifacts`, `get_stage_metrics`.
- `src/grace_control/services/feature_planning_service.py` — обернуть `run_context_builder`, `run_architect`.
- `src/grace_control/services/packet_materializer.py` — обернуть `materialize`.
- `src/grace_control/services/packet_service.py` — обернуть `claim`.
- `src/grace_control/services/merge_service.py` — обернуть `merge_packet`.
- `src/grace_control/adapters/packet_executor.py` — обернуть `execute`, прокинуть LLM usage.
- `src/grace_control/core/acceptance_pipeline.py` — обернуть `run_t0/t1/t2`.
- `src/grace_control/core/evidence_verifier.py` — обернуть `run_evidence_verifier`.
- `src/grace_control/core/reviewer_gate.py` — обернуть `run_reviewer_gate`.
- `src/grace_control/core/recovery_controller.py` — создавать `StageRun` с `loop_round+1` при return-решениях.
- `src/grace_control/runtime/opencode_event_collector.py` — суммировать usage.
- `src/grace_control/worker/worker.py` — эмитить `worker_heartbeat`.
- `src/grace_control/core/stuck_scanner.py` — эмитить `worker_stuck`.
- `src/grace_control/api/app_factory.py` — подключить `admin_pipeline` роутер.
- `src/grace_control/ui/templates/admin/console.html` — расширить (Gantt в центральной колонке).
- `src/grace_control/ui/templates/admin/_detail.html` — расширить (Pipeline секция сверху).
- `src/grace_control/ui/templates/admin/system.html` — расширить (workers, stuck, supervisor logs).
- `src/grace_control/ui/templates/admin/tabs/_artifacts.html` — расширить (группировка по стадии).
- `src/grace_control/ui/static/admin.js` — WS-обработчики, mobile navigation.
- `src/grace_control/ui/static/css/base.css` — общие стили для новых компонентов.
- `tests/grace_control/db/test_migrations.py` — расширить (проверка новых миграций).
- `tests/grace_control/api/test_openapi_paths.py` — расширить (новые endpoints в OpenAPI).
- `tests/ui/test_admin_ui_*.py` — расширить (новые компоненты в smoke tests).

### Приложение E. Ссылки на связанные TZ-документы

- `TZ_MISSION_CONTROL.md` — концепция админки (baseline).
- `docs/TZ_ADMIN_PANEL.md` — реализованная Admin Panel v2.
- `docs/TZ_FRONTEND_ACCEPTANCE.md` — стратегия frontend testing.
- `docs/work/TZ_ADMIN_UI_PIPELINE_STAGE_CARDS_NOT_LOG.md` — stage cards.
- `docs/work/TZ_ADMIN_UI_PIPELINE_WIDE_STACKED_CARDS.md` — wide stacked layout.
- `docs/work/TZ_ADMIN_UI_PIPELINE_STAGE_BLOCKS_FINAL.md` — финальный stage blocks layout.
- `docs/work/TZ_ADMIN_UI_VERTICAL_PIPELINE_TIMELINE.md` — vertical timeline.
- `docs/work/TZ_ADMIN_UI_PACKET_VISIBILITY_AND_TIMING.md` — packet timing.
- `docs/grace/EXECUTION_PIPELINE.md` — каноническое описание pipeline.
- `docs/grace/ACCEPTANCE_PIPELINE.md` — T0/T1/T2 акцепторы.
- `docs/grace/STATE_MACHINE.md` — state machine пакета.
- `docs/grace/TRACE_AND_OBSERVABILITY.md` — trace и observability.
- `docs/SUPERVISOR.md` — supervisor.
- `GRACE_CONTROL_PLANE_SPEC.md` — спецификация control plane.
- `docs/TZ_RETENTION_POLICY.md` — retention (для будущей очистки `stage_runs`).
- `docs/TZ_SESSION_RESUME.md` — resume/fork sessions (для `AgentSession.parent_session_id`).

---

**Конец документа.**
