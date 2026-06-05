# ТЗ для кодера: API-first cleanup waves W0–W11

Date: 2026-06-05
Repo: `basilivanov/grace-orchestrator`
Source roadmap: `source/codex/roadmap-api-first-legacy-cli-hardcode-cleanup.md`

## Общая цель

Перевести GRACE Control Plane в схему:

```text
Services = единственное ядро бизнес-логики
FastAPI + OpenAPI = единственный публичный runtime-интерфейс для людей и агентов
CLI = удалить как продуктовый/user-facing control plane
Local CLI agents = допустимый execution adapter, запускаемый только из GRACE API/backend
scripts/ = только CI/dev wrappers, без runtime orchestration
Legacy Prefect = изолировать, заменить UniversalCliAgentBackend, удалить из runtime package
MCP = не делать сейчас; только future thin adapter поверх services
GraceLint = executable GRACE canon, который запрещает возврат техдолга
```

Главное правило для всех волн:

```text
Не добавлять второй control plane.
Не дублировать бизнес-логику между API / CLI / scripts / legacy.
Все действия, которые нужны агентам, должны быть доступны через API и видны в OpenAPI.
Локальные CLI-агенты разрешены только как backend исполнения, не как интерфейс управления GRACE.
```

## Базовые требования ко всем PR/пакетам

Каждый пакет должен:

1. Сохранять текущие зелёные тесты.
2. Добавлять regression tests на новую архитектурную гарантию.
3. Не раздувать существующие монолиты.
4. Соблюдать GRACE canon:
   - `AI_HEADER`;
   - `START_MODULE_CONTRACT` / `END_MODULE_CONTRACT`;
   - `START_MODULE_MAP` / `END_MODULE_MAP`;
   - `START_FUNCTION_CONTRACT` для публичных функций;
   - логические `START_BLOCK_*` / `END_BLOCK_*` в крупных файлах.
5. Не добавлять прямые `os.environ.get`, `subprocess`, `prefect_grace`, `Packet.state = ...` вне разрешённых слоёв.
6. При изменении API — обновлять generated OpenAPI через существующий docs flow.
7. В конце PR писать краткое evidence summary: tests, files changed, remaining risks.

---

# W0 — Finish merge atomicity

## Статус

Считать выполненным после коммита `e89f410` и ревью `source/codex/review-2026-06-05-e89f410-merge-atomicity.md`.

## Цель

Нельзя допускать сценарий: git merge/push прошёл, API вернул 200, но DB packet остался `accepted`.

## Scope

```text
src/grace_control/services/merge_service.py
src/grace_control/api/routers/packets.py
tests/grace_control/core/test_post_refactor_audit_fixes.py
```

## Требования

1. `MergeService.merge_packet()` при падении `PacketService.transition(packet_id, PacketState.MERGED)` возвращает `MergeResult(success=False)`.
2. `MergeResult.commit_sha` сохраняется, даже если DB transition упал.
3. `/api/packets/{id}/merge` возвращает HTTP 409, если `MergeResult.success == False`.
4. Event recording на success/failure path — best-effort, не должен маскировать HTTP 409.

## Acceptance criteria

- `test_followup_5198516_merge_fails_when_transition_fails` проходит.
- `test_followup_5198516_merge_router_returns_409_on_transition_failure` проходит.
- Happy-path merge переводит packet в `merged`.

---

# W1 — API-first contract + CLI inventory

## Цель

Зафиксировать API/OpenAPI как единственный публичный runtime-интерфейс для людей и агентов. Провести полную инвентаризацию CLI и определить, что удалить, что заменить API endpoint’ом, что оставить только как CI/dev script.

## Scope

```text
src/grace_control/cli/
src/grace_control/api/routers/
src/grace_control/services/
docs/grace/API_FIRST_CONTROL_PLANE.md
docs/grace/CLI_DEPRECATION_INVENTORY.md
source/codex/*
pyproject.toml
scripts/generate_docs.py
Makefile
tests/grace_control/api/
```

## Что сделать

### 1. Создать документ API-first

Создать `docs/grace/API_FIRST_CONTROL_PLANE.md`.

Документ должен зафиксировать:

```text
- OpenAPI is canonical runtime contract.
- Agents discover capabilities through /openapi.json.
- CLI is deprecated as runtime interface.
- Local CLI agents may still be launched by execution backends.
- Scripts are CI/dev only.
- MCP is future optional adapter, not active scope.
- Services own business logic; API routers expose services.
```

### 2. Инвентаризировать CLI

Создать `docs/grace/CLI_DEPRECATION_INVENTORY.md`.

Для каждой команды из `src/grace_control/cli/main.py` и `src/grace_control/cli/trace.py` указать:

```text
command
current behavior
runtime/business logic? yes/no
replacement API endpoint
migration action: delete | convert-to-api | keep-as-dev-script | temporary-thin-client
risk
acceptance test needed
```

Минимально покрыть:

```text
grace up
grace init
grace lint
grace eval run
grace trace ...
legacy grace-dev
legacy prefect-grace
legacy gracectl
```

### 3. Определить missing API capabilities

Сформировать список endpoint’ов, которых не хватает, чтобы удалить CLI как control plane:

```text
/api/trace/search
/api/trace/packets/{packet_id}
/api/trace/features/{feature_id}
/api/trace/runs/{run_id}
/api/tools/grace-lint/run
/api/tools/docs/check
/api/tools/smoke/run
/api/diagnostics/state
/api/diagnostics/config
```

На W1 не обязательно реализовать все endpoint’ы, но нужно создать issue-like checklist внутри документа.

### 4. Обновить README

README должен ссылаться на:

```text
docs/grace/API_FIRST_CONTROL_PLANE.md
docs/openapi.json
docs/grace/CLI_DEPRECATION_INVENTORY.md
```

И не рекламировать CLI как основной способ runtime управления.

### 5. Добавить OpenAPI regression test

Добавить тест, который проверяет, что generated OpenAPI доступен и содержит базовые runtime groups:

```text
/api/features
/api/packets
/api/workers
/api/architect
/api/recovery
```

## Что НЕ делать

- Не удалять CLI в этой волне.
- Не удалять legacy Prefect.
- Не переписывать executor.
- Не добавлять MCP.

## Acceptance criteria

1. Есть `docs/grace/API_FIRST_CONTROL_PLANE.md`.
2. Есть `docs/grace/CLI_DEPRECATION_INVENTORY.md` с таблицей по всем CLI commands.
3. README говорит, что API/OpenAPI — canonical runtime interface.
4. Есть тест на наличие базовых OpenAPI paths.
5. `make docs-check` зелёный.

---

# W4 — Trace / Observability API

## Цель

Заменить ценность CLI trace на OpenAPI-discoverable API. Агент должен уметь понять, что произошло с packet/feature/run, не зная hidden scripts/CLI.

## Scope

```text
src/grace_control/api/routers/trace.py
src/grace_control/api/routers/events.py
src/grace_control/api/routers/diagnostics.py
src/grace_control/services/trace_service.py
src/grace_control/services/event_query_service.py
src/grace_control/services/run_summary_service.py
src/grace_control/services/diagnostics_service.py
src/grace_control/api/main.py or app_factory wiring
tests/grace_control/api/test_trace_api.py
tests/grace_control/services/test_trace_service.py
docs/grace/TRACE_AND_OBSERVABILITY.md
```

## API endpoints

Реализовать:

```text
GET /api/trace/packets/{packet_id}
GET /api/trace/features/{feature_id}
GET /api/trace/runs/{run_id}
GET /api/trace/search?q=...
GET /api/events
GET /api/diagnostics/state
```

Опционально, если быстро:

```text
GET /api/diagnostics/config
GET /api/diagnostics/openapi-summary
```

## Response contracts

### `GET /api/trace/packets/{packet_id}`

Возвращает:

```json
{
  "packet_id": "...",
  "feature_id": "...",
  "wave_id": "...",
  "title": "...",
  "current_state": "accepted|rejected|...",
  "attempt_count": 1,
  "max_attempts": 3,
  "runs": [
    {
      "run_id": "...",
      "run_number": 1,
      "status": "accepted|rejected|running|...",
      "executor_id": "...",
      "started_at": "...",
      "finished_at": "...",
      "duration_ms": 123,
      "acceptance_verdict": "...",
      "acceptance_summary": "...",
      "evidence_path": "..."
    }
  ],
  "timeline": [
    {
      "timestamp": "...",
      "event_type": "packet_claimed",
      "entity_type": "packet",
      "entity_id": "...",
      "payload": {},
      "trace_id": "..."
    }
  ],
  "last_failure": {
    "stage": "T0|T1|T2|review|agent|merge",
    "summary": "...",
    "blocking_issues": []
  },
  "recommended_next_action": "retry|review|manual|merge|none"
}
```

### `GET /api/trace/features/{feature_id}`

Возвращает feature → waves → packets summary + timeline.

### `GET /api/trace/search?q=...`

Ищет по:

```text
packet id
packet title
feature id
event payload
run result summary
executor id
```

MVP можно сделать DB-search по Packet/Feature title/id, без full text engine.

## Service rules

- Routers не пишут SQL-агрегацию напрямую.
- `TraceService` собирает packet/feature/run trace.
- `EventQueryService` отвечает за event filtering.
- `RunSummaryService` извлекает last failure / acceptance summary.
- Все ошибки 404/400 структурированные.

## Tests

1. packet trace returns current state, runs, events.
2. feature trace groups packets by wave.
3. search by packet title returns packet.
4. missing packet returns 404.
5. OpenAPI contains all trace endpoints.
6. No CLI is needed for trace data.

## Acceptance criteria

- Агент через `/openapi.json` видит trace capabilities.
- `/api/trace/packets/{id}` заменяет минимум 80% текущей trace CLI ценности.
- Dashboard может позже переиспользовать TraceService.

---

# W2 — Remove public CLI business logic

## Цель

Удалить CLI как самостоятельный runtime control plane. CLI не должен запускать API+worker, мутировать state, запускать eval pipeline, делать trace или lint как уникальную capability.

Важно: удаляем GRACE CLI как интерфейс управления. Это **не запрещает** GRACE backend’у запускать локальные CLI-агенты (`opencode`, `codex`, `agy`, `gemini`, `claude`) как execution adapter по конфигу.

## Scope

```text
pyproject.toml
src/grace_control/cli/main.py
src/grace_control/cli/trace.py
src/grace_control/cli/*
docs/grace/CLI_DEPRECATION_INVENTORY.md
README.md
Makefile
scripts/*
tests/grace_control/cli/ if exists
```

## Требования

### 1. Удалить public entrypoint `grace`

В `pyproject.toml` убрать или перенести в optional dev-extra:

```toml
grace = "grace_control.cli.main:cli"
```

Предпочтительно: удалить полностью из runtime package.

### 2. Удалить legacy CLI entrypoints

Удалить из `[project.scripts]`:

```toml
grace-dev = "prefect_grace.devtools.cli:main"
prefect-grace = "prefect_grace.cli_compat:prefect_grace_main"
gracectl = "prefect_grace.cli_compat:gracectl_main"
```

### 3. Разобрать `src/grace_control/cli/main.py`

Удалить или архивировать runtime commands:

```text
up       -> delete; API startup is deployment concern, not product CLI
init     -> replace with docs/template or API if needed later
lint     -> scripts/grace_lint.py for CI; API tools endpoint if runtime needed
eval run -> scripts/local_smoke.py or /api/tools/smoke/run
trace    -> /api/trace/*
```

### 4. Убрать небезопасные паттерны

Удалить:

```text
os.system("pkill ...")
threading API server boot from CLI
feature watcher with silent except
worker spawning loop from CLI
hardcoded worker agy1
hardcoded /tmp/grace-eval
```

### 5. Сохранить CI/dev scripts

Оставить:

```text
scripts/grace_lint.py
scripts/generate_docs.py
scripts/local_smoke.py if needed
```

Но это не package entrypoint и не runtime interface.

## Tests

1. Test package metadata has no public `grace`, `grace-dev`, `prefect-grace`, `gracectl` entrypoints.
2. Test no imports from `grace_control.cli` in runtime code.
3. Test OpenAPI trace/tools endpoints exist as replacement.
4. Test Makefile still supports `lint`, `docs-check`, `test`.

## Acceptance criteria

- CLI business logic removed.
- Runtime state changes are possible only through API/services.
- No public CLI entrypoints remain in core package.
- Docs explain API-first usage.

---

# W3 — Hardcode / config cleanup

## Цель

Все runtime-настройки централизованы в typed config. Хардкод разрешён только в test fixtures или documented local defaults.

## Scope

```text
src/grace_control/config/settings.py
src/grace_control/config/project_config.py
src/grace_control/config/agent_profiles.py
src/grace_control/**/*.py
Makefile
pyproject.toml
docs/grace/CONFIGURATION.md
tests/grace_control/config/
scripts/grace_lint.py
```

## Требования

### 1. Ввести `.grace/config.yaml`

Добавить typed loader:

```text
src/grace_control/config/project_config.py
```

Пример config:

```yaml
project:
  name: grace-orchestrator

api:
  host: 127.0.0.1
  port: 8042

database:
  url: sqlite:///./grace.db

git:
  remote: origin
  base_branch: main
  target_branch: main

execution:
  backend: cli
  state_root: .grace/state
  worktree_root: .grace/worktrees
  timeout_seconds: 900

safety:
  sandbox_mode: restricted
  allow_sandbox_bypass: false
```

### 2. Разделить settings

`GraceSettings` должен читать:

```text
env > .grace/config.yaml > defaults
```

### 3. Убрать direct env reads вне config

Запретить:

```python
os.environ.get("GRACE_...")
```

кроме:

```text
src/grace_control/config/*
tests/*
explicit process/env builder for UniversalCliAgentBackend
```

### 4. Убрать hardcoded runtime values

Заменить:

```text
/tmp/grace-eval
/tmp/grace-orchestrator-export
main
origin
legacy
new
danger-full-access
127.0.0.1:8042
8042
agy1
src/prefect_grace
opencode/codex/agy hardcode in code
```

на settings/config/constants с понятным владельцем.

### 5. Agent command config

Профили локальных CLI-агентов должны жить в config, а не в коде:

```yaml
agents:
  coder_opencode:
    backend: cli
    command:
      - opencode
      - run
      - "--model"
      - "{model}"
      - "--effort"
      - "{effort}"
    model: "codex-5.1"
    effort: "high"
    cwd: "{worktree_path}"
    timeout_seconds: 900
    env:
      OPENAI_API_KEY: "${OPENAI_API_KEY}"
      OPENAI_BASE_URL: "${OPENAI_BASE_URL}"
    input:
      mode: stdin
      template: "{packet_markdown}"
```

## Tests

1. env overrides project config.
2. project config overrides default.
3. invalid config fails with clear error.
4. no direct `os.environ.get("GRACE_` outside allowlist.
5. no hardcoded `/tmp/grace-` outside tests/scripts allowlist.
6. settings values used by API lifespan, worker, packet executor, merge service.
7. agent command template loads from config and is not hardcoded in code.

## Acceptance criteria

- Runtime config documented in `docs/grace/CONFIGURATION.md`.
- Hardcode grep/lint rules pass.
- No new config scattered across code.

---

# W10 — Stronger GraceLint executable canon

## Цель

GraceLint должен стать executable GRACE canon: не просто проверять маркеры, а запрещать архитектурный регресс.

## Scope

```text
scripts/grace_lint.py
src/grace_control/core/grace_canon.py or src/grace_control/tools/grace_lint/
src/grace_control/api/routers/tools.py
tests/grace_control/core/test_grace_lint.py
docs/grace/CANON.md
docs/grace/GRACE_LINT_RULES.md
Makefile
```

## Требования

### 1. Сделать linter importable

Перенести основную логику из script-only в importable модуль:

```text
src/grace_control/tools/grace_lint/checker.py
```

`scripts/grace_lint.py` должен стать тонким wrapper.

### 2. Добавить правила

Минимальные правила:

```text
GRC001 AI_HEADER required
GRC020 MODULE_CONTRACT required
GRC021 MODULE_MAP required
GRC004 START_BLOCK/END_BLOCK pairing
GRC005 file size limit
GRC010 public function contract required
GRC012 function size limit
GRC100 no direct os.environ outside config/tests/explicit agent env builder
GRC101 no direct subprocess outside GitService/WorktreeCleanupService/UniversalCliAgentBackend/scripts/tests
GRC102 no direct prefect_grace import anywhere in src/grace_control after W8
GRC103 no Packet.state mutation outside PacketService/wave_gate/db migrations/tests
GRC104 routers must not contain heavy DB/business loops beyond threshold
GRC105 no hardcoded /tmp grace paths outside tests/scripts
GRC106 no hardcoded branch/remote outside config/tests
GRC107 generated docs must be in sync or docs-check covers this
GRC108 modules over N lines must have logical START_BLOCK sections
GRC109 no hardcoded agent command names in execution code; commands must come from profiles/config
```

### 3. Allowlist file

Добавить allowlist config:

```text
.grace/lint_allowlist.yaml
```

Каждая allowlist запись должна иметь:

```yaml
rule: GRC101
path: src/grace_control/agent/universal_cli_backend.py
reason: execution backend owns local CLI process spawning by design
expires_wave: never
```

### 4. API endpoint для агента

Если W4/W1 уже сделали tools endpoint, добавить:

```text
POST /api/tools/grace-lint/run
```

Payload:

```json
{"paths": ["src/grace_control"], "strict": true}
```

Response:

```json
{"ok": false, "violations": [{"rule": "GRC100", "path": "...", "line": 12, "message": "..."}]}
```

## Tests

По одному fixture-test на каждое правило:

```text
bad missing header
bad env read
bad subprocess in router
bad hardcoded agent command in backend code
bad prefect_grace import
bad packet state mutation
bad hardcoded /tmp
bad giant module without blocks
```

## Acceptance criteria

- `make lint` запускает stronger GraceLint.
- Новый код не может добавить direct env/subprocess/legacy/state mutation/hardcoded agent command без явного allowlist.
- Canon docs и lint rules синхронизированы.

---

# W5 — Split API monolith

## Цель

`api/main.py` должен стать app factory/wiring-only. UI/dashboard/events/artifacts/ws/diagnostics должны жить в отдельных routers/services.

## Scope

```text
src/grace_control/api/main.py
src/grace_control/api/app_factory.py
src/grace_control/api/routers/dashboard.py
src/grace_control/api/routers/events.py
src/grace_control/api/routers/artifacts.py
src/grace_control/api/routers/diagnostics.py
src/grace_control/api/routers/ws.py
src/grace_control/services/dashboard_service.py
src/grace_control/services/event_query_service.py
src/grace_control/services/artifact_service.py
src/grace_control/services/diagnostics_service.py
tests/grace_control/api/
```

## Требования

1. Создать `src/grace_control/api/app_factory.py` с `create_app(settings: GraceSettings | None = None) -> FastAPI`.
2. `main.py` должен только создавать app и запускать uvicorn.
3. Вынести lifespan loops в `api/lifespan.py` или `services/background_tasks.py`.
4. Вынести dashboard/events/artifacts/ws/health в отдельные routers/services.
5. Artifact file reading должно остаться path-safe:

```text
resolve evidence_dir
resolve target path
target must be inside evidence_dir
```

## Tests

1. app starts via `create_app()`.
2. all old endpoints still respond.
3. artifact traversal still forbidden.
4. dashboard data service returns features/waves/packets.
5. events endpoint still filters.
6. OpenAPI unchanged or intentionally updated.
7. `api/main.py` below target line count, e.g. <150 lines.

## Acceptance criteria

- `api/main.py` wiring-only.
- No DB-heavy dashboard/event/artifact logic in app entrypoint.
- Existing UI/API smoke tests still pass.

---

# W6 — Split execution pipeline monolith

## Цель

`PacketExecutionAdapter` должен стать тонким orchestrator-flow, без direct legacy, subprocess, git details, evidence/reviewer/verifier/self-evolution implementation details.

## Scope

```text
src/grace_control/adapters/packet_executor.py
src/grace_control/services/packet_loader.py
src/grace_control/services/worktree_inspector.py
src/grace_control/services/agent_commit_service.py
src/grace_control/services/acceptance_service.py
src/grace_control/services/evidence_verifier_service.py
src/grace_control/services/reviewer_service.py
src/grace_control/services/run_result_writer.py
src/grace_control/services/self_evolution_guard_service.py
tests/grace_control/services/
tests/grace_control/adapters/test_packet_executor.py
```

## Target flow

```text
PacketExecutionAdapter.execute(packet_id, worker_id)
  -> PacketLoader.snapshot(packet_id)
  -> PacketMaterializer.materialize(snapshot)
  -> ExecutionBackend.run(request)
  -> WorktreeInspector.inspect(result.worktree_path)
  -> AgentCommitService.ensure_commit(...)
  -> AcceptanceService.run(...)
  -> EvidenceVerifierService.run_or_skip(...)
  -> ReviewerService.run_or_skip(...)
  -> SelfEvolutionGuardService.evaluate(...)
  -> RunResultWriter.finish(...)
  -> ExecutionResult
```

## Требования

1. Extract `PacketLoader`: читает DB packet и возвращает session-safe DTO.
2. Extract `WorktreeInspector`: worktree exists, is git worktree, has changes, changed files, base sha.
3. Extract `AgentCommitService`: commit agent changes в worktree.
4. Extract `AcceptanceService`: оборачивает `AcceptancePipeline.run()`.
5. Extract `EvidenceVerifierService` / `ReviewerService`: не держать branching в executor.
6. Extract `RunResultWriter`: единственное место, которое обновляет `PacketRun` result/status/evidence summary.
7. `packet_executor.py` не должен импортировать `grace_control.agent.legacy_backend`, `prefect_grace`, `subprocess`.

## Tests

1. PacketExecutionAdapter happy path with MockBackend.
2. backend failure -> rejected/failed result as expected.
3. no worktree -> rejected early.
4. no changes -> rejected/blocker as current behavior says.
5. acceptance fail -> rework required.
6. reviewer fail -> rejected.
7. run result writer persists result.
8. grep/lint: no subprocess import in packet_executor.
9. packet_executor target size <250–300 lines.

## Acceptance criteria

- `packet_executor.py` is mostly orchestration.
- Each new service has unit tests.
- Execution can be tested with MockBackend without legacy Prefect.

---

# W7 — UniversalCliAgentBackend MVP

## Цель

Добавить основной execution backend для локальных CLI-агентов через универсальный конфигурируемый запускатор. API/OpenAPI остаётся единственным публичным control plane, но реальное исполнение packet’ов может запускать локальные CLI-агенты: `opencode`, `codex`, `agy`, `gemini`, `claude` или любой другой command из профиля.

Это заменяет прежнюю идею “ApiAgentBackend как HTTP provider backend”. В GRACE API-first означает:

```text
человек/агент управляет GRACE через API/OpenAPI
GRACE внутри сам выбирает ExecutionBackend
UniversalCliAgentBackend запускает локальный CLI-agent по профилю
```

Не возвращать CLI как пользовательский интерфейс. CLI — только исполняемый инструмент внутри backend.

## Scope

```text
src/grace_control/agent/backend.py
src/grace_control/agent/universal_cli_backend.py
src/grace_control/agent/mock_backend.py
src/grace_control/agent/__init__.py
src/grace_control/services/agent_run_service.py
src/grace_control/services/command_template_renderer.py
src/grace_control/services/agent_env_builder.py
src/grace_control/services/process_supervisor.py
src/grace_control/services/agent_artifact_collector.py
src/grace_control/api/routers/agents.py
src/grace_control/config/agent_profiles.yaml
src/grace_control/config/settings.py
tests/grace_control/agent/
tests/grace_control/api/test_agents_api.py
docs/grace/EXECUTION_BACKENDS.md
```

## Backend model

### `UniversalCliAgentBackend`

Implements:

```python
class UniversalCliAgentBackend(ExecutionBackend):
    async def run(self, request: ExecutionRequest) -> ExecutionResult:
        ...
```

Backend не знает конкретных `opencode`, `codex`, `agy`, `gemini`, `claude` в коде. Он читает профиль и запускает command template.

### Agent run services

Добавить сервисы:

```text
AgentRunService
CommandTemplateRenderer
AgentEnvBuilder
ProcessSupervisor
AgentArtifactCollector
```

Они отвечают за:

```text
agent profile selection
command template rendering
model / effort / packet_id / worktree_path / state_root substitutions
env/key expansion from config
timeout
process group kill on timeout
stdout/stderr/exit_code capture
artifact/log persistence
structured ExecutionResult normalization
```

## Agent profile contract

Профиль агента должен быть declarative config, например:

```yaml
agents:
  coder_opencode:
    backend: cli
    command:
      - opencode
      - run
      - "--model"
      - "{model}"
      - "--effort"
      - "{effort}"
    model: "codex-5.1"
    effort: "high"
    cwd: "{worktree_path}"
    timeout_seconds: 900
    env:
      OPENAI_API_KEY: "${OPENAI_API_KEY}"
      OPENAI_BASE_URL: "${OPENAI_BASE_URL}"
    input:
      mode: stdin
      template: "{packet_markdown}"
    output:
      collect_stdout: true
      collect_stderr: true
      artifacts:
        - "."
```

Другой агент должен отличаться только профилем:

```yaml
agents:
  coder_agy:
    backend: cli
    command:
      - agy
      - run
      - "--model"
      - "{model}"
      - "--effort"
      - "{effort}"
    model: "gemini-3.5-flash"
    effort: "medium"
    cwd: "{worktree_path}"
    timeout_seconds: 900
```

## API endpoint

Добавить или сохранить:

```text
POST /api/agents/run
```

Payload:

```json
{
  "packet_id": "...",
  "executor_id": "coder_opencode",
  "role": "coder",
  "model": "optional override",
  "effort": "optional override",
  "worktree_path": "...",
  "packet_markdown": "...",
  "timeout_seconds": 900
}
```

Response:

```json
{
  "accepted": false,
  "domain_status": "completed|rejected|blocked|failed|timeout",
  "executor_id": "coder_opencode",
  "command_preview": ["opencode", "run", "--model", "codex-5.1", "--effort", "high"],
  "exit_code": 0,
  "stdout_path": "...",
  "stderr_path": "...",
  "stdout_tail": "...",
  "stderr_tail": "...",
  "worktree_path": "...",
  "branch_name": "...",
  "duration_ms": 123456,
  "reason": "",
  "artifacts": []
}
```

## Требования

1. `execution_backend=cli` выбирает `UniversalCliAgentBackend`.
2. `execution_backend=mock` выбирает `MockBackend`.
3. `execution_backend=legacy` не поддерживается после W8 и должен падать с понятной ошибкой.
4. Agent profiles не должны быть legacy-specific.
5. Никаких hardcoded `opencode`, `codex`, `agy`, `gemini`, `claude` в backend-коде.
6. Command/env/model/effort/cwd/input mode берутся из профиля и request overrides.
7. Поддержать input modes:
   - `stdin` — отправить packet markdown в stdin;
   - `file` — передать path к materialized packet file;
   - `none` — command сам читает repo/context.
8. Timeout должен завершать весь process group, не оставляя висячие agent-процессы.
9. stdout/stderr/exit_code/duration должны сохраняться как evidence artifacts.
10. Structured result не должен зависеть от формата конкретного CLI.

## Tests

1. `select_backend("cli")` returns `UniversalCliAgentBackend`.
2. `select_backend("mock")` returns `MockBackend`.
3. `select_backend("legacy")` raises W8 removal error.
4. Command template renders model/effort/packet_id/worktree_path correctly.
5. Env builder expands `${ENV_VAR}` and redacts secrets in logs/previews.
6. ProcessSupervisor captures stdout/stderr/exit_code.
7. Timeout kills process group and returns `domain_status="timeout"`.
8. stdin input mode sends packet markdown to process stdin.
9. file input mode passes materialized packet path.
10. stdout/stderr artifacts are persisted in run evidence.
11. `/api/agents/run` appears in OpenAPI.
12. Packet execution can run with `UniversalCliAgentBackend` using a fake local command, no Prefect.
13. GraceLint fails on hardcoded agent command names in backend code.

## Acceptance criteria

- Normal execution path can run a fake local CLI command through `UniversalCliAgentBackend`.
- opencode/codex/agy/gemini/claude integration is config-only, not code-specific.
- API/OpenAPI remains the only public control plane.
- No public GRACE CLI is reintroduced.
- Legacy Prefect is no longer required for tests.

---

# W8 — Remove legacy Prefect

## Цель

Удалить legacy Prefect из runtime package после того, как `UniversalCliAgentBackend`/`MockBackend` закрывают execution path.

## Prerequisites

- W7 done.
- Tests pass without Prefect installed.
- No runtime path imports `prefect_grace`.
- `execution_backend=cli` or `mock` works.

## Scope

```text
pyproject.toml
src/prefect_grace/
src/grace_control/agent/legacy_backend.py
src/grace_control/config/settings.py
src/grace_control/config/agent_profiles.yaml
docs/grace/LEGACY_REMOVAL.md
docs/archived/
tests/*
```

## Требования

1. В `pyproject.toml` заменить packages на только `src/grace_control`.
2. Удалить force-include legacy templates/prompts/roles/policies.
3. Удалить entrypoints `grace-dev`, `prefect-grace`, `gracectl`.
4. Удалить optional `legacy = ["prefect>=3.0.0"]`, если больше не нужен.
5. Move `src/prefect_grace` to `archive/legacy_prefect_grace/` or delete after tag.
6. Remove `src/grace_control/agent/legacy_backend.py` or archive it.
7. `select_backend("legacy")` должен выдавать clear config error.
8. GraceLint: no `prefect_grace` import anywhere in `src/grace_control`.

## Tests

1. import `grace_control` works without Prefect installed.
2. `select_backend("legacy")` fails clearly.
3. grep/lint: no `prefect_grace` in runtime src.
4. package metadata has no legacy scripts and packages.
5. full `tests/grace_control/` passes.

## Acceptance criteria

- Legacy Prefect no longer runtime dependency.
- Runtime package contains only `grace_control`.
- Docs clearly mark legacy as removed/archived.

---

# W9 — Documentation cleanup

## Цель

Документация должна быть структурированной, не противоречить коду, и быть пригодной для агентов как source of truth.

## Scope

```text
README.md
docs/README.md
docs/grace/*
docs/archived/*
docs/openapi.json
docs/packet-states.md
docs/state-diagram.md
scripts/generate_docs.py
Makefile
```

## Target structure

```text
docs/
  README.md
  grace/
    CANON.md
    API_FIRST_CONTROL_PLANE.md
    ARCHITECTURE.md
    CONFIGURATION.md
    EXECUTION_PIPELINE.md
    EXECUTION_BACKENDS.md
    STATE_MACHINE.md
    ACCEPTANCE_PIPELINE.md
    TRACE_AND_OBSERVABILITY.md
    TESTING_STRATEGY.md
    SELF_EVOLUTION.md
    LEGACY_REMOVAL.md
    GRACE_LINT_RULES.md
  openapi.json
  packet-states.md
  state-diagram.md
  archived/
    ... historical docs
```

## Требования

1. README top-level должен быть кратким и ссылаться на docs/grace.
2. Все stale docs переместить в `docs/archived/`.
3. Удалить дубли, если они противоречат generated docs.
4. Generated docs не редактировать руками.
5. Добавить docs ownership table:

```text
doc
owner/source of truth
manual/generated
update command
```

6. `docs/API_CONTRACT.md` не должен быть активным source of truth.
7. Добавить `docs/README.md` как навигацию для людей и агентов.

## Tests / checks

1. `make docs-check` green.
2. README links do not point to missing files.
3. Optional script/test: validate docs links for local markdown links.
4. OpenAPI generated file up to date.

## Acceptance criteria

- Агент по README может найти актуальную архитектуру, API, config, execution, testing, self-evolution docs.
- Нет активных contradictory docs.
- Старые документы явно archived.

---

# W11 — Self-evolution safety cleanup

## Цель

Self-evolution не должен быть side-channel. Любое самоизменение должно идти через тот же packet/acceptance/review/merge/trace pipeline.

## Scope

```text
src/grace_control/core/self_evolution.py
src/grace_control/api/routers/self_evolution.py
src/grace_control/services/self_evolution_service.py
src/grace_control/services/self_evolution_guard_service.py
src/grace_control/db/schema.py
src/grace_control/api/routers/self.py or self_evolution.py
docs/grace/SELF_EVOLUTION.md
tests/grace_control/self_evolution/
```

## Требования

### 1. Explicit job model

Добавить или привести к явной модели:

```text
SelfEvolutionSession
SelfEvolutionJob
SelfEvolutionDecision
SelfEvolutionApproval
SelfEvolutionRollbackPlan
```

### 2. No direct worker spawn from API

Запретить:

```text
API request -> spawn worker process
API request -> mutate repo directly
API request -> reload app directly
```

Self-evolution API должен только создать job/session и вернуть id.

### 3. Pipeline path

Self-evolution flow:

```text
request
-> SelfEvolutionService.create_session
-> Architect/plan packet(s)
-> normal PacketService lifecycle
-> AcceptanceService
-> ReviewService
-> MergeService
-> TraceService visibility
```

### 4. Approval gates

Добавить policy:

```text
low-risk docs-only self-evolution may auto-merge if configured
code changes require approval by default
config/security/execution changes require manual approval
```

MVP может только классифицировать и block/manual, без UI approval.

### 5. Rollback plan

Каждая self-evolution session должна хранить:

```text
base commit
changed files
merge commit if any
rollback command suggestion
risk class
```

### 6. Trace integration

`/api/trace/features/{id}` или `/api/trace/self/{session_id}` должен показывать self-evolution session timeline.

## Tests

1. self-evolution request creates session/job, not direct worker process.
2. code-change session requires approval/manual status.
3. docs-only session can be classified lower risk.
4. rollback metadata stored.
5. trace endpoint can find self-evolution session.
6. GraceLint rule: no process spawn in self_evolution router.

## Acceptance criteria

- Self-evolution is controlled by same API/services pipeline.
- No hidden background mutation path.
- Every self-change is traceable.

---

# Финальный порядок выполнения

Выполнять в таком порядке:

```text
W0  finish merge atomicity                  # done / verify only
W1  API-first contract + CLI inventory
W4  trace/observability API
W2  remove public CLI business logic
W3  hardcode/config cleanup
W10 stronger GraceLint
W5  split API monolith
W6  split execution pipeline monolith
W7  UniversalCliAgentBackend MVP
W8  remove legacy Prefect
W9  docs cleanup
W11 self-evolution safety cleanup
```

Почему не по номеру: сначала нужно дать агентам OpenAPI-навигацию и trace capabilities, потом удалить CLI как control plane, потом зацементировать config/lint, и только после этого пилить большие монолиты и legacy.

## Общий definition of done для всей программы

Программа считается завершённой, когда:

1. Runtime управление возможно только через API/OpenAPI.
2. Public CLI entrypoints отсутствуют или являются dev-only thin clients без бизнес-логики.
3. Local CLI agents запускаются только через `UniversalCliAgentBackend` по declarative config.
4. Legacy Prefect не входит в runtime package.
5. Tests pass без Prefect.
6. `api/main.py` wiring-only.
7. `packet_executor.py` thin orchestration flow.
8. Hardcode runtime values вынесены в config.
9. GraceLint запрещает возврат прямых env/subprocess/legacy/state mutation/hardcoded agent commands.
10. Docs структурированы в `docs/grace/`.
11. Agents can discover capabilities from `/openapi.json` and inspect runs through `/api/trace/*`.
