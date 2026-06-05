# Roadmap: API-first GRACE cleanup, hardcode removal, CLI/legacy removal

Date: 2026-06-05
Context: after the post-refactor runtime fixes around `MergeService`, `PacketService`, `wave_gate`, SQLite migration, T0 worktree scope, and worktree cleanup are considered done.

## Executive decision

GRACE Control Plane should move to an **API-first architecture**.

The API/OpenAPI contract is the only public runtime control surface for agents and humans. CLI must not be a separate product interface and must not contain independent business logic. Legacy Prefect support must be isolated, replaced, then removed.

Target rule:

```text
Services = core business logic
FastAPI + OpenAPI = public runtime interface
CLI = removed, or at most temporary thin HTTP client during migration
scripts/ = CI/dev-only utilities, no runtime orchestration
MCP = optional future thin adapter over the same services, not a second control plane
Legacy Prefect = temporary backend only, then deleted
```

---

## Current state observed

### Good progress already done

- `PacketService` exists and owns most packet state transitions.
- `MergeService` and `GitService` exist.
- `ExecutionBackend` protocol exists.
- `LegacyPrefectBackend` isolates the direct `prefect_grace` import behind a backend boundary.
- `GraceSettings` exists via `pydantic-settings`.
- `scripts/grace_lint.py` exists and checks basic GRACE canon markers.
- Generated docs/OpenAPI flow exists through `scripts/generate_docs.py` and `make docs-check`.

### Remaining architectural debt

#### 1. CLI is still public and contains real behavior

`pyproject.toml` still exposes:

```toml
grace = "grace_control.cli.main:cli"
grace-dev = "prefect_grace.devtools.cli:main"
prefect-grace = "prefect_grace.cli_compat:prefect_grace_main"
gracectl = "prefect_grace.cli_compat:gracectl_main"
```

`src/grace_control/cli/main.py` still contains runtime-ish commands: `up`, `init`, `lint`, `eval run`, trace command wiring, local feature watcher, worker spawning, `pkill`, subprocess/env setup, and local project file mutation.

Decision: these must be migrated to API endpoints or CI/dev scripts, then removed from the public package entrypoints.

#### 2. Legacy is still packaged

`pyproject.toml` still packages both:

```toml
packages = ["src/prefect_grace", "src/grace_control"]
```

and still includes legacy templates/prompts/roles/policies into the wheel. Legacy is optional as dependency, but not optional as package payload.

Decision: first isolate, then archive/delete `src/prefect_grace` from the runtime package.

#### 3. Hardcoded defaults still exist

Examples still visible:

- `settings.api_url = http://127.0.0.1:8042`
- `settings.state_root = /tmp/grace-eval`
- `settings.sandbox_mode = danger-full-access`
- `settings.execution_backend = legacy`
- Makefile `GRACE_DB_URL = sqlite:////tmp/grace-orchestrator-export/test_grace.db`
- CLI defaults: port `8042`, worker `agy1`, local `.grace/state`, `/tmp/grace-eval/<slug>`.

Decision: runtime hardcode must move to typed config, project `.grace/config.yaml`, or test-only fixtures. Direct env reads outside settings/config should become lint violations.

#### 4. `api/main.py` still mixes too many responsibilities

`api/main.py` currently includes app creation, lifespan loops, CORS, exception handling, UI dashboard, `/test`, dashboard data aggregation, events listing, packet run lookup, artifact listing/file read, websocket, and health.

Decision: split into routers/services:

```text
api/app_factory.py
api/routers/dashboard.py
api/routers/events.py
api/routers/artifacts.py
api/routers/diagnostics.py
api/routers/ws.py
services/dashboard_service.py
services/event_query_service.py
services/artifact_service.py
```

#### 5. `packet_executor.py` is still too large and still knows legacy details

`packet_executor.py` is improved but still:

- says it bridges DB packets to legacy runner;
- imports `os`, `subprocess`, `yaml`;
- calls `legacy_prepare_worktree()`;
- resolves base refs and git state itself;
- runs agent commit logic;
- runs acceptance, verifier, reviewer, self-evolution guard, evidence updates;
- calls `_call_legacy_runner()`.

Decision: turn it into a thin orchestration service with dependencies injected.

#### 6. `GraceLint` exists but is not yet the full canon enforcer

`scripts/grace_lint.py` checks AI_HEADER, MODULE_CONTRACT, MODULE_MAP, START/END block balance, file size, public function contracts, and approximate function token size.

Missing checks should be added:

- forbidden imports by layer;
- direct `os.environ` outside config;
- direct `subprocess` outside approved adapters/services;
- direct `prefect_grace` imports outside legacy boundary;
- direct packet state mutation outside PacketService/wave gate policy;
- direct git subprocess outside GitService/legacy boundary;
- routers doing DB/business logic beyond request/response translation;
- required logical START_BLOCK markers for large modules;
- maximum router/service sizes;
- stale docs/generated docs drift.

---

## Target architecture

```text
src/grace_control/
  api/
    app_factory.py
    routers/
      features.py
      packets.py
      workers.py
      architect.py
      acceptance.py
      review.py
      merge.py
      trace.py
      events.py
      artifacts.py
      diagnostics.py
      tools.py
      self_evolution.py
  services/
    packet_service.py
    merge_service.py
    trace_service.py
    event_query_service.py
    artifact_service.py
    acceptance_service.py
    review_service.py
    agent_run_service.py
    dashboard_service.py
    self_evolution_service.py
  core/
    pure logic only; no FastAPI, no DB sessions, no subprocess unless explicitly core-safe
  agent/
    backend.py
    api_backend.py
    mock_backend.py
    legacy_backend.py  # temporary only
  config/
    settings.py
    project_config.py
    agent_profiles.py
  db/
    schema.py
    migrations.py or alembic/
  scripts/
    CI/dev only, not runtime interface
```

## Public runtime API capabilities

Every action an agent may need should be discoverable through OpenAPI.

Minimum capability groups:

```text
/api/features/*
/api/waves/*
/api/packets/*
/api/agents/run
/api/acceptance/run
/api/review/run
/api/merge/*
/api/trace/search
/api/trace/packets/{packet_id}
/api/trace/features/{feature_id}
/api/events
/api/artifacts/*
/api/diagnostics/health
/api/diagnostics/state
/api/tools/grace-lint/run
/api/tools/docs/check
/api/tools/smoke/run
/api/self/*
```

CLI commands must either map to one of these endpoints during migration or be deleted.

---

# Waves

## Wave 0 — Finish runtime correctness tail

Scope: last blocker before broad cleanup.

Required:

- `MergeService.merge_packet()` must return `success=False` if `PacketService.transition(..., MERGED)` fails.
- API `/merge` must return 409 in that case.
- Regression test: git merge/push success + DB transition failure => API/service failure, not success.

Acceptance:

- No path can report merge success while packet state is not persisted as `merged`.

---

## Wave 1 — API-first contract and CLI deprecation plan

Goal: define API as the only public runtime interface.

Tasks:

1. Write `docs/grace/API_FIRST_CONTROL_PLANE.md`.
2. Mark CLI entrypoints as deprecated in docs.
3. Inventory every CLI command and classify:
   - delete;
   - convert to API endpoint;
   - keep as CI/dev script only.
4. Add OpenAPI endpoints for missing capabilities currently available only via CLI/scripts:
   - trace;
   - lint;
   - docs-check;
   - eval/smoke run;
   - local diagnostics.
5. Add tests that OpenAPI contains these endpoints.

Acceptance:

- Any runtime action needed by an agent has an API endpoint and JSON schema.
- CLI contains no unique runtime capability not available through API.
- Documentation says: OpenAPI is canonical for agents.

---

## Wave 2 — Remove public CLI business logic

Goal: eliminate CLI as independent control plane.

Tasks:

1. Remove `grace` runtime CLI from `[project.scripts]`, or turn it into an optional dev-only extra.
2. Delete or archive `src/grace_control/cli/main.py` commands that mutate project/runtime state.
3. Convert `trace` to `/api/trace/*` endpoints.
4. Convert `lint` to `/api/tools/grace-lint/run` if runtime use is needed; keep `scripts/grace_lint.py` for CI.
5. Convert `eval run` to `/api/tools/smoke/run` or an explicit test harness script outside package runtime.
6. Remove local worker spawning, `pkill`, `os.system`, feature watcher, and API server boot from CLI.

Acceptance:

- No public package entrypoint starts API + worker + feature watcher.
- No CLI command mutates packet/feature/worker state directly.
- CI/dev scripts remain callable by Makefile, not by runtime agents.

---

## Wave 3 — Hardcode and config cleanup

Goal: centralize all runtime configuration.

Tasks:

1. Introduce nested settings/project config:

```yaml
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
  backend: api
  state_root: .grace/state
  worktree_root: .grace/worktrees
  timeout_seconds: 600

safety:
  sandbox_mode: restricted
  allow_sandbox_bypass: false
```

2. Add `.grace/config.yaml` project config loader with typed validation.
3. Replace direct `os.environ.get()` outside `config/`.
4. Replace hardcoded `/tmp`, `main`, `origin`, `8042`, `legacy`, `danger-full-access`, `agy1`.
5. Add GraceLint rules:
   - no direct env read outside config;
   - no magic `/tmp/grace-*` outside tests;
   - no direct subprocess in routers/core;
   - no hardcoded branch/remote in services.

Acceptance:

- Runtime hardcode inventory is empty except allowed test fixtures.
- Config has validation and documentation.
- `make lint` fails on new forbidden hardcode patterns.

---

## Wave 4 — API observability and trace replacement

Goal: replace hidden CLI diagnostics with OpenAPI-discoverable diagnostics.

Tasks:

1. Add `TraceService`.
2. Add `EventQueryService`.
3. Add `RunSummaryService`.
4. Add endpoints:

```text
GET /api/trace/packets/{packet_id}
GET /api/trace/features/{feature_id}
GET /api/trace/runs/{run_id}
GET /api/trace/search?q=...
GET /api/events
GET /api/diagnostics/state
```

5. Make responses structured JSON: timeline, runs, current state, last failure, artifacts, recommended next action.
6. Update dashboard to consume same services/endpoints.

Acceptance:

- Agent can inspect “what happened with packet X” from OpenAPI without CLI or scripts.
- Existing trace CLI can be deleted or becomes a thin HTTP client during migration.

---

## Wave 5 — Split API monolith

Goal: make API layer thin and maintainable.

Tasks:

1. Split `api/main.py` into app factory + routers:

```text
api/app_factory.py
api/routers/dashboard.py
api/routers/events.py
api/routers/artifacts.py
api/routers/diagnostics.py
api/routers/ws.py
```

2. Move dashboard aggregation to `DashboardService`.
3. Move artifact listing/file reading to `ArtifactService`.
4. Move event querying to `EventQueryService`.
5. Move health/state diagnostics to `DiagnosticsService`.
6. Keep `main.py` under ~100–150 lines.

Acceptance:

- `api/main.py` only creates app, wires middleware/routers/lifespan.
- Routers do request/response translation only.
- Services contain business/query logic.
- No DB-heavy dashboard loops inside app entrypoint.

---

## Wave 6 — Split execution pipeline monolith

Goal: shrink `PacketExecutionAdapter` and make pipeline replaceable/testable.

Target shape:

```text
PacketExecutionService
  PacketLoader
  PacketMaterializer
  ExecutionBackend
  WorktreeInspector
  AgentCommitService
  AcceptanceService
  EvidenceVerifierService
  ReviewerService
  SelfEvolutionGuardService
  RunResultWriter
```

Tasks:

1. Extract packet loading/session snapshot.
2. Extract base ref/changed file resolution.
3. Extract worktree inspection and no-changes detection.
4. Extract agent commit creation.
5. Extract acceptance pipeline invocation into `AcceptanceService`.
6. Extract evidence verifier/reviewer routing.
7. Extract run result writing.
8. Remove direct `subprocess` from `packet_executor.py`.
9. Remove direct legacy helper calls from `packet_executor.py`.

Acceptance:

- `packet_executor.py` becomes a thin orchestration flow, preferably <250 lines.
- Each service has isolated tests.
- Execution pipeline can run with `ApiAgentBackend` or `MockBackend` without legacy.

---

## Wave 7 — API Agent Backend MVP

Goal: replace CLI/Prefect-style agent execution with API-based agent execution.

Tasks:

1. Add `ApiAgentBackend` implementing `ExecutionBackend`.
2. Define `AgentRunRequest` / `AgentRunResult` schemas.
3. Add `/api/agents/run` or internal `AgentGatewayService`.
4. Support provider/model routing via config/agent profiles.
5. Persist stdout/stderr/messages/tool outputs as evidence artifacts.
6. Add timeout/retry/cancellation semantics.
7. Add `MockBackend` for deterministic tests.
8. Make `execution.backend = api` the intended target, with `legacy` still available only temporarily.

Acceptance:

- Full packet execution can run without `prefect_grace`.
- Agent execution is structured, logged, timeout-controlled, and testable.
- No shell/CLI is needed for normal runtime.

---

## Wave 8 — Legacy Prefect removal

Goal: remove legacy from runtime package.

Prerequisite:

- `ApiAgentBackend` passes smoke and acceptance pipeline tests.
- No production path imports `prefect_grace`.
- Legacy backend is not default.

Tasks:

1. Remove `legacy` as default execution backend.
2. Remove `prefect_grace` package from `[tool.hatch.build].packages`.
3. Remove `grace-dev`, `prefect-grace`, `gracectl` entrypoints.
4. Remove legacy force-included templates/prompts/roles/policies from wheel.
5. Move `src/prefect_grace` to `archive/legacy_prefect_grace/` or delete after tag.
6. Remove `prefect` optional dependency if no longer needed.
7. Add lint rule: no `prefect_grace` import anywhere in `src/grace_control`.

Acceptance:

- `pip install -e .` installs only `grace_control` runtime.
- Tests pass without Prefect installed.
- Legacy docs are archived and clearly marked historical.

---

## Wave 9 — Documentation structure cleanup

Goal: make docs canonical, discoverable, and non-duplicative.

Target docs:

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
  openapi.json                 # generated
  packet-states.md             # generated
  state-diagram.md             # generated
  archived/
    ... historical docs only
```

Tasks:

1. Move obsolete docs to `docs/archived/`.
2. Delete duplicate/contradictory docs.
3. Generate docs from source where possible.
4. Add doc ownership table.
5. Add docs-check CI target.
6. Ensure README links only to current canonical docs.

Acceptance:

- No stale `API_CONTRACT.md` style docs remain as active references.
- Canonical docs match code/generated OpenAPI.
- Agents can find architecture/pipeline/config docs from README.

---

## Wave 10 — GraceLint as executable canon

Goal: enforce GRACE canon automatically.

Existing `scripts/grace_lint.py` should evolve into a stronger checker.

Required rules:

```text
GRC001 AI_HEADER required
GRC020 MODULE_CONTRACT required
GRC021 MODULE_MAP required
GRC004 START_BLOCK/END_BLOCK pairing
GRC005 file size limit
GRC010 public function contract required
GRC012 function size limit
GRC100 no direct os.environ outside config
GRC101 no direct subprocess outside allowed adapters/services
GRC102 no direct prefect_grace import outside legacy boundary
GRC103 no Packet.state mutation outside PacketService/wave gate migration policy
GRC104 no router DB-heavy business logic
GRC105 no hardcoded /tmp grace paths outside tests
GRC106 no hardcoded branch/remote outside config/tests
GRC107 generated docs must be in sync
GRC108 module must contain logical START_BLOCK sections if >N lines
```

Tasks:

1. Move linter implementation from script-only into importable `grace_control.core.grace_canon` or `tools/grace_lint`.
2. Keep `scripts/grace_lint.py` as CI wrapper.
3. Add API endpoint `/api/tools/grace-lint/run` if agents need it at runtime.
4. Add tests for every rule.
5. Run against `src/grace_control/` and ratchet from warning to error.

Acceptance:

- New code cannot introduce non-canonical files.
- Legacy/archive directories are excluded or checked with historical mode.
- CI fails on missing contracts, forbidden imports, oversized files, direct state mutation, hardcoded paths.

---

## Wave 11 — Self-evolution safety cleanup

Goal: make self-improvement safe and API-first.

Tasks:

1. Create explicit `SelfEvolutionJob` model/service.
2. Remove any direct worker spawning/reload behavior from API request handlers.
3. Add approval gates and rollback plan.
4. Run all self-evolution changes through normal packet/acceptance/merge path.
5. Add traceability: session → packets → runs → merge → artifacts.

Acceptance:

- Self-evolution is just another controlled pipeline, not a side-channel.
- No hidden background mutation path exists.
- Every self-change is inspectable via trace API.

---

## Deletion / archive inventory

Candidates to delete or archive after replacements exist:

```text
src/grace_control/cli/                 # after API replacements
grace CLI entrypoint                   # remove from pyproject
grace-dev / prefect-grace / gracectl   # remove from pyproject
src/prefect_grace/                     # archive/delete after ApiAgentBackend
legacy templates/prompts/roles/policies force-includes
old docs/API_CONTRACT or stale docs
manual eval CLI flows
local feature watcher
pkill/subprocess worker spawn helpers
```

Candidates to keep as CI/dev scripts:

```text
scripts/grace_lint.py       # wrapper around importable linter
scripts/generate_docs.py    # generated docs check
scripts/dev_seed.py         # if needed
scripts/local_smoke.py      # if needed, no product logic
```

---

## Pipeline risks to watch

1. **Merge atomicity:** git success + DB transition failure must be a failure, not success.
2. **Double event/broadcast paths:** some router/service observability may duplicate events; centralize later.
3. **Worker release semantics:** ensure worker status/current packet is always cleared through one service path.
4. **Wave gate policy:** only completed/safe waves open next wave; final blocked/rejected/failed states stop.
5. **Acceptance pipeline root handling:** all checks must run against worktree, not control-plane repo root.
6. **Legacy backend path math:** legacy backend currently derives project root from worktree paths. This should disappear with ApiAgentBackend.
7. **Settings import-time read:** `settings = GraceSettings()` reads at import time; tests/runtime overrides must be deliberate.
8. **Global exception handler:** returning raw exception messages can leak internal data; later replace with structured public error + trace_id.
9. **SQLite additive migrations:** acceptable short-term, but Alembic or explicit migrations are needed before serious DB evolution.
10. **API auth:** current API is localhost/dev-oriented; before remote/multi-user use, add auth/token/rbac.

---

## Recommended packet order

1. **W0:** finish merge atomicity tail.
2. **W1:** API-first contract + CLI inventory.
3. **W4:** trace/observability API, because it replaces hidden CLI value.
4. **W2:** remove public CLI business logic.
5. **W3:** hardcode/config cleanup.
6. **W10:** GraceLint stronger rules to prevent new debt.
7. **W5:** split API monolith.
8. **W6:** split execution pipeline monolith.
9. **W7:** ApiAgentBackend MVP.
10. **W8:** remove legacy Prefect.
11. **W9:** docs cleanup can run in parallel after W1, but final consolidation after W8.
12. **W11:** self-evolution safety cleanup.

## Non-goals for the next immediate packet

Do not start with deleting `prefect_grace` immediately.
Do not rewrite the whole packet executor in one packet.
Do not introduce MCP now.
Do not add a second interface layer parallel to API.
Do not keep CLI alive as a product interface.

The next phase is about making API/OpenAPI canonical, then deleting alternative control paths.
