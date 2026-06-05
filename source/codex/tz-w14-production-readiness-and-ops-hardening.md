# ТЗ: W14 — Production readiness and ops hardening

Date: 2026-06-05
Repo: `basilivanov/grace-orchestrator`
Depends on: W0–W13 accepted, green default test suite.

## Контекст

После W0–W13 проект приведён к новой архитектуре:

```text
GRACE API/OpenAPI = public control plane
UniversalCliAgentBackend = configurable local CLI agent execution adapter
Legacy Prefect = removed from runtime package
Public GRACE CLI = removed as control plane
Trace / artifacts / evidence = canonical API-visible paths
GraceLint / docs / config = guardrails against old debt returning
```

W14 — это уже не legacy cleanup. Это следующий слой готовности к реальной эксплуатации: CI gates, безопасность API, operational runbooks, profile validation, observability in UI/API, and small readability hardening.

## Главная цель

Сделать так, чтобы текущая новая архитектура была безопасно запускаема, проверяема и сопровождаема:

```text
- every push is guarded by CI gates;
- API has at least token auth for non-local use;
- agent profiles can be validated before execution;
- operators can see which executor/model/profile ran each packet;
- runbooks explain how to deploy/run/debug the control plane;
- remaining dense services are easier to maintain without broad rewrites.
```

---

# W14.1 — CI gates and repository hygiene

## Цель

На `main` нельзя пушить изменения, которые ломают tests, GraceLint, docs-check, package metadata, или снова тащат generated artifacts.

## Scope

```text
.github/workflows/ci.yml
Makefile
scripts/generate_docs.py
scripts/grace_lint.py
src/grace_control/tools/grace_lint/*
.gitignore
tests/grace_control/*
docs/grace/TESTING_STRATEGY.md
```

## Требования

### 1. GitHub Actions CI

Добавить workflow:

```text
.github/workflows/ci.yml
```

Минимальные jobs:

```text
unit-tests
  - python setup
  - install package + dev deps
  - pytest -q

grace-lint
  - python scripts/grace_lint.py src/grace_control tests scripts

docs-check
  - make docs-check or equivalent

repo-hygiene
  - fail if generated runtime artifacts are tracked
  - fail if public CLI entrypoints return
  - fail if src/prefect_grace returns to package
```

### 2. Repo hygiene checks

Добавить script или pytest test, который проверяет:

```text
- no tracked agents/ runtime artifacts
- no tracked .grace runtime state
- no packet_registry.yaml
- no src/prefect_grace in pyproject packages
- no project scripts: grace, grace-dev, prefect-grace, gracectl
- no expires_wave pointing to already completed waves W0–W13
```

### 3. Makefile standard commands

Makefile должен иметь понятные targets:

```text
make test
make lint
make docs-check
make ci
```

`make ci` должен запускать локально то же, что CI.

## Tests

1. CI config exists and includes pytest/lint/docs/hygiene jobs.
2. Repo hygiene test catches fake tracked `agents/llm_x/EXECUTION_PACKET.md` fixture.
3. Package metadata test catches reintroduced public CLI scripts.
4. Allowlist expiry test fails on `expires_wave: W13` after W13 completion.

## Acceptance criteria

```text
- GitHub Actions CI green on main.
- `make ci` green locally.
- Generated artifacts cannot silently re-enter repo.
- Old CLI/legacy package entrypoints cannot return unnoticed.
```

---

# W14.2 — API token auth and safe local defaults

## Цель

API остаётся удобным локально, но при удалённом доступе не должен быть полностью открытым.

## Scope

```text
src/grace_control/api/app_factory.py
src/grace_control/api/auth.py
src/grace_control/config/settings.py
src/grace_control/api/routers/*
docs/grace/API_SECURITY.md
docs/grace/CONFIGURATION.md
tests/grace_control/api/test_auth.py
```

## Требования

### 1. Settings

Добавить settings:

```yaml
api:
  auth_enabled: false
  token_env: GRACE_API_TOKEN
  allow_unauthenticated_localhost: true
```

Env overrides:

```text
GRACE_API_AUTH_ENABLED=true|false
GRACE_API_TOKEN=...
GRACE_API_ALLOW_UNAUTHENTICATED_LOCALHOST=true|false
```

### 2. Auth middleware/dependency

Добавить token auth через header:

```http
Authorization: Bearer <token>
```

или:

```http
X-GRACE-API-Token: <token>
```

Минимум: Bearer token.

### 3. Endpoint policy

Auth required for mutating/runtime endpoints when enabled:

```text
POST /api/packets/*
POST /api/agents/run
POST /api/merge/*
POST /api/self-evolution/*
POST /api/tools/*
```

Read-only endpoints can also require auth when `auth_enabled=true`, except maybe `/health`.

Recommended:

```text
/health = public minimal
/openapi.json = public only in local/dev; protected when auth_enabled=true unless explicitly allowed
all /api/* = protected when auth_enabled=true
```

### 4. Error contract

Unauthorized response:

```json
{
  "error": {
    "code": "UNAUTHORIZED",
    "message": "missing or invalid API token"
  }
}
```

No token value should appear in logs/errors.

## Tests

1. Auth disabled: existing API tests still pass.
2. Auth enabled + missing token => 401.
3. Auth enabled + wrong token => 401.
4. Auth enabled + correct Bearer token => request passes.
5. `/health` behavior matches documented policy.
6. Token never appears in response body/log preview.

## Acceptance criteria

```text
- API has opt-in token auth.
- Local dev remains easy by default.
- Remote deployment can turn auth on without code changes.
- Docs explain exactly how to set token and expose API safely.
```

---

# W14.3 — Agent profile validation and dry-run endpoint

## Цель

Перед запуском packet’ов оператор/агент должен уметь проверить, что CLI profiles валидны, commands рендерятся, env есть, cwd/input mode корректны, но без реального запуска тяжёлого агента.

## Scope

```text
src/grace_control/config/agent_profiles.py
src/grace_control/services/agent_profile_validator.py
src/grace_control/api/routers/agents.py
src/grace_control/api/schemas/agents.py if exists
docs/grace/EXECUTION_BACKENDS.md
docs/grace/AGENT_PROFILES.md
tests/grace_control/agent/test_agent_profile_validator.py
tests/grace_control/api/test_agents_api.py
```

## API endpoints

Добавить:

```text
GET  /api/agents/profiles
GET  /api/agents/profiles/{executor_id}
POST /api/agents/profiles/{executor_id}/validate
POST /api/agents/profiles/{executor_id}/dry-run
```

### `GET /api/agents/profiles`

Возвращает список profiles без секретов:

```json
{
  "profiles": [
    {
      "executor_id": "coder_opencode",
      "backend": "cli",
      "model": "codex-5.1",
      "effort": "high",
      "command_preview": ["opencode", "run", "--model", "codex-5.1", "--effort", "high"],
      "input_mode": "stdin",
      "timeout_seconds": 900
    }
  ]
}
```

### validate

Checks:

```text
- command is list[str]
- no unresolved placeholders after render
- cwd template can render
- input mode is stdin/file/none
- timeout > 0
- env var references are present or explicitly optional
- executable exists on PATH if validate_executable=true
```

### dry-run

Renders command/env/cwd/input plan without launching by default:

```json
{
  "ok": true,
  "executor_id": "coder_opencode",
  "rendered_command": [...],
  "cwd": "/path/to/worktree",
  "input_mode": "stdin",
  "env_preview": {"OPENAI_API_KEY": "***"},
  "would_execute": false
}
```

Optionally allow safe fake execution only when command is explicitly a test command.

## Tests

1. Valid profile passes validation.
2. String command fails validation.
3. Unknown placeholder fails validation.
4. Missing required env var fails validation.
5. Env preview redacts secrets.
6. Dry-run does not spawn process.
7. Profiles API does not expose raw secrets.

## Acceptance criteria

```text
- Agent profiles are inspectable through OpenAPI.
- Bad profile config fails before runtime packet execution.
- Secrets are redacted in all previews.
- Operators can run dry-run before enabling a profile.
```

---

# W14.4 — UI/API observability for execution details

## Цель

В dashboard/trace/API должно быть видно, какой executor/profile/model/effort запускался, где лежат stdout/stderr artifacts, и на какой стадии packet находится.

## Scope

```text
src/grace_control/services/trace_service.py
src/grace_control/services/dashboard_service.py
src/grace_control/services/evidence_service.py
src/grace_control/api/routers/trace.py
src/grace_control/api/routers/artifacts.py
src/grace_control/ui/templates/*
docs/grace/TRACE_AND_OBSERVABILITY.md
tests/grace_control/api/test_trace_api.py
tests/grace_control/services/test_dashboard_service.py
```

## Требования

### Trace response enrichment

`GET /api/trace/packets/{packet_id}` должен показывать:

```json
{
  "runs": [
    {
      "run_id": "...",
      "executor_id": "coder_opencode",
      "backend": "cli",
      "model": "codex-5.1",
      "effort": "high",
      "exit_code": 0,
      "domain_status": "completed",
      "stdout_artifact": "agent_stdout.log",
      "stderr_artifact": "agent_stderr.log",
      "command_artifact": "agent_command.log"
    }
  ]
}
```

### Dashboard/UI

Минимум:

```text
- show executor_id / model / effort per active/recent run
- show status: queued/running/completed/failed/timeout/accepted/rejected
- link to artifacts: stdout/stderr/command/evidence summary
- show last failure reason compactly
```

Не делать сложный дизайн. Главное — operator clarity.

### Event stream

Events should include executor metadata where useful:

```text
packet_started
agent_run_started
agent_run_finished
acceptance_started
acceptance_finished
review_started
review_finished
merge_started
merge_finished
```

## Tests

1. Trace packet response includes executor metadata.
2. Artifacts endpoint lists `agent_stdout.log`, `agent_stderr.log`, `agent_command.log` for CLI runs.
3. Dashboard service includes executor/model/status for recent packets.
4. UI template smoke test does not fail with missing fields.

## Acceptance criteria

```text
- Operator can answer: what ran, where, with which model, what happened, where are logs?
- Trace API and dashboard use the same service data where possible.
- No separate hidden diagnostics path is introduced.
```

---

# W14.5 — Operational runbooks

## Цель

Сделать проект сопровождаемым без “памяти автора”: как запускать, как добавлять профили, как дебажить packet, как чистить worktrees, как откатывать self-evolution.

## Scope

```text
docs/grace/RUNBOOK_LOCAL_DEV.md
docs/grace/RUNBOOK_SERVER_DEPLOY.md
docs/grace/RUNBOOK_AGENT_PROFILES.md
docs/grace/RUNBOOK_DEBUG_PACKET.md
docs/grace/RUNBOOK_SELF_EVOLUTION.md
README.md
```

## Документы

### RUNBOOK_LOCAL_DEV.md

```text
- install
- config
- run API locally
- run worker/scheduler if applicable
- run fake CLI profile
- run tests/lint/docs-check
```

### RUNBOOK_SERVER_DEPLOY.md

```text
- env vars
- database location
- state_root/worktree_root
- API auth token
- process manager/systemd example
- logs
- backup/restore basics
```

### RUNBOOK_AGENT_PROFILES.md

```text
- profile schema
- opencode example
- codex example
- agy example
- env/secrets
- dry-run/validate
- common failures
```

### RUNBOOK_DEBUG_PACKET.md

```text
- find packet by trace API
- inspect run timeline
- inspect stdout/stderr artifacts
- rerun packet safely
- handle timeout
- handle no-changes rejection
- handle merge 409
```

### RUNBOOK_SELF_EVOLUTION.md

```text
- what self-evolution can/cannot do
- approval gates
- rollback metadata
- trace self-change
- manual recovery
```

## Tests/checks

1. Markdown link check if available.
2. README links to all runbooks.
3. Docs mention current backend `cli`, not stale `api` default.
4. Commands in docs match Makefile/API endpoints.

## Acceptance criteria

```text
- A new operator can set up local dev and run a fake profile from docs.
- A server operator can enable auth and find logs/artifacts.
- Debug packet flow is documented end-to-end.
```

---

# W14.6 — Small readability hardening, not broad rewrite

## Цель

После W0–W13 основные blockers закрыты, но некоторые файлы остаются плотными. W14 должен сделать минимальные безопасные extraction’ы, не открывая новый широкий рефакторинг.

## Scope candidates

```text
src/grace_control/adapters/packet_executor.py
src/grace_control/services/evidence_service.py
src/grace_control/services/agent_run_service.py
```

## Требования

### 1. packet_executor readability

Если файл всё ещё плотный, вынести только очевидные pure/helper chunks:

```text
- attempt naming helper if not already isolated
- execution request builder
- evidence dir builder
- route after result helper
```

Не менять state machine semantics.

### 2. evidence_service readability

Разделить helper blocks:

```text
- artifact listing
- evidence summary write/read
- path safety validation
```

### 3. agent_run_service readability

Если нужно:

```text
- input materialization helper
- result normalization helper
```

## Tests

1. Existing packet execution tests pass unchanged.
2. Artifact path traversal tests still pass.
3. AgentRunService stdin/file/none tests pass.
4. GraceLint GRC108 allowlist shrinks if possible.

## Acceptance criteria

```text
- No behavior rewrite.
- Smaller, clearer helpers with direct unit tests.
- Remove GRC108 allowlist entries where practical.
```

---

# Non-goals

```text
- no MCP
- no public GRACE CLI return
- no new legacy backend
- no migration away from UniversalCliAgentBackend
- no large UI redesign
- no microservices
- no unrelated product features
```

---

# Recommended execution order

```text
W14.1 CI gates and repo hygiene
W14.3 Agent profile validation/dry-run
W14.2 API token auth
W14.4 UI/API observability
W14.5 Operational runbooks
W14.6 Small readability hardening
```

Rationale:

```text
First lock the project with CI/hygiene, then make agent profiles safe to inspect, then secure API, then improve operator visibility/docs, then do small readability cleanup.
```

---

# W14 Definition of Done

W14 is done when:

1. GitHub Actions and `make ci` run pytest + GraceLint + docs-check + hygiene.
2. Generated runtime artifacts cannot be tracked unnoticed.
3. API supports opt-in token auth with tests.
4. Agent profiles can be listed, validated, and dry-run through OpenAPI.
5. Dashboard/trace expose executor/model/effort/status/artifact links.
6. Runbooks exist and README links them.
7. Remaining readability cleanup is done without behavior drift.
8. Test suite is green.
9. No old CLI/legacy/control-plane path returns.

## Suggested packet title

```text
feat(W14): production readiness, CI gates, auth, profile validation, and ops runbooks
```

For implementation, split into smaller packets by W14.x. Do not attempt all of W14 in one coder run unless the agent explicitly creates sub-packets and reports evidence per section.
