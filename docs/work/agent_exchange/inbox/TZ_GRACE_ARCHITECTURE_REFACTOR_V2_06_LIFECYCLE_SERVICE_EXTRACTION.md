# TZ_GRACE_ARCHITECTURE_REFACTOR_V2_06_LIFECYCLE_SERVICE_EXTRACTION — Packet 06: thin lifecycle HTTP boundary

## Packet identity

- `TZ_NAME`: `TZ_GRACE_ARCHITECTURE_REFACTOR_V2_06_LIFECYCLE_SERVICE_EXTRACTION`
- Role: Coder
- Repository: `/opt/grace-orchestrator`
- Upstream: `origin/main`
- Parent source: `docs/work/TZ_GRACE_ARCHITECTURE_REFACTOR_V2.md`
- Normative detail: Architecture Refactor V2 Wave 4 — lifecycle router/service extraction only.
- Previous new-cycle packet `TZ_GRACE_ARCHITECTURE_REFACTOR_V2_05_ADMIN_AGGREGATION_CYCLE_REMOVAL` is ACCEPTED.
- Historical agent-exchange packets from earlier cycles are evidence only. Do not edit or reuse their submission/review files.

Implement only this named packet. Do not start typed Admin read models, dead-code cleanup, CI consolidation, mutation refactoring, or any later wave.

## Mandatory fast-forward sync

Before inspecting implementation files or editing anything:

```bash
cd /opt/grace-orchestrator
git switch main
git fetch origin --prune
git pull --ff-only origin main
git status --short --branch
git rev-parse HEAD
```

Record synced base SHA and initial status. Preserve unrelated untracked files. Do not use `git reset --hard`, `git clean`, destructive checkout, repo-side `state.json`, lock files, or orchestration metadata.

## Current-state rule

This new cycle verifies/refines a repository that may already contain the earlier accepted Wave 4 implementation.

1. Current synced `main` is authoritative.
2. Audit actual code first; do not recreate router-owned filesystem/DB/subprocess logic merely because the parent TZ describes the historical starting point.
3. If every acceptance criterion is already satisfied, run the required verification and submit a **verified no-op** using synced `HEAD` as `WEB_ORCH_COMMIT`.
4. Do not manufacture a source diff merely to produce an implementation commit.
5. If a gap exists, make only the smallest in-scope correction, commit/push it, and report the actual implementation SHA.

## Objective

Ensure `src/grace_control/api/routers/lifecycle.py` is a thin HTTP adapter and lifecycle business/infrastructure composition lives below the router.

Required direction:

```text
FastAPI lifecycle router
    -> LifecycleService
        -> RuntimeStateStore
        -> SupervisorControlService -> SupervisorClient
        -> WorkerReadService
        -> VersionProvider

Admin controls local dispatch
    -> explicit lifecycle service/callback
    -> never imports private lifecycle-router helpers
```

The lifecycle router must not directly own supervisor-state filesystem parsing, UDS HTTP transport, Git subprocesses, Worker ORM queries, target-dir environment resolution, or health/status/version business composition.

## Frozen API/product invariants

Preserve all current `/api/admin/lifecycle` routes and semantics, including:

- `GET /status`
- `GET /versions`
- `GET /health/full`
- `POST /restart/{target}`
- `POST /cleanup`
- `POST /shutdown`
- `POST /reload`

Preserve:

- status/version/health JSON keys and meaning;
- missing supervisor-state behavior for status/version;
- mutation distinction between state missing and supervisor transport unavailable;
- `/health/full` degraded-state behavior via `healthy/issues`, not route failure;
- restart target validation (`api|workers|all`);
- canonical authorization/confirmation/audit flow through existing Admin controls;
- cleanup/shutdown alias behavior;
- bootstrap model: `scripts/live_supervisor.sh` starts the process, runtime control stays HTTP/OpenAPI;
- API/OpenAPI contracts, DB schema, lifecycle state values, packet execution/reviewer/recovery/merge semantics.

Do not introduce typed Admin DTO migration in this packet. Do not create a service locator, global dependency registry, `BaseService`, manager factory, replacement CLI, new GRC005/GRC012 allowlist entry, or mutable process-global target settings.

## Audit before edits

Inspect current versions of at least:

```text
src/grace_control/api/routers/lifecycle.py
src/grace_control/api/routers/admin_controls.py
src/grace_control/api/routers/admin_controls_local.py
src/grace_control/services/lifecycle_service.py
src/grace_control/services/runtime_state_store.py
src/grace_control/services/supervisor_control_service.py
src/grace_control/services/worker_read_service.py
src/grace_control/services/version_provider.py
src/grace_control/lifecycle_composition.py
src/grace_control/supervisor_client.py
src/grace_control/config/settings.py
tests/supervisor/test_lifecycle_api.py
tests/grace_control/architecture/test_lifecycle_router_boundary.py
```

Some preferred files may differ if the accepted implementation chose an equivalent narrow name. Verify responsibilities rather than filenames alone.

Run structural inventory:

```bash
rg -n 'read_state_file|get_git_sha|get_db_workers|_proxy_supervisor|_restart_local|_reload_local|SupervisorClient|GRACE_TARGET_DIR|GRACE_SUPERVISOR_SOCK' \
  src tests || true

rg -n 'import os|import subprocess|import httpx|from pathlib import Path|from grace_control.db import get_db|from grace_control.db.schema import Worker|os\.environ|subprocess\.run|AsyncHTTPTransport' \
  src/grace_control/api/routers/lifecycle.py || true
```

Interpret every hit. Historical `docs/work` evidence is excluded from zero-hit requirements.

## Required target state

### 1. Runtime state ownership below HTTP

`RuntimeStateStore` or equivalent must receive target directory explicitly and own supervisor-state path existence/read/JSON parsing.

It must distinguish physical state-file existence from readable/valid state content when current mutation semantics require that distinction.

No FastAPI, DB, Git subprocess or supervisor HTTP transport belongs in this store.

### 2. Git/version lookup isolated

`VersionProvider` or equivalent must own `git rev-parse` execution and deterministic candidate-directory fallback.

Timeout, missing Git, invalid repo and OS errors must preserve current fallback behavior. No subprocess import/use may remain in the lifecycle router.

### 3. Worker DB projection isolated

`WorkerReadService` or equivalent must own the Worker ORM query and preserve the accepted worker projection fields/serialization.

The lifecycle router must not import `get_db` or `Worker` and must not issue ORM queries.

### 4. Supervisor control uses the existing client

`SupervisorControlService` must use `src/grace_control/supervisor_client.py::SupervisorClient` or the accepted equivalent transport abstraction; do not reimplement HTTP-over-UDS in the lifecycle router/service.

Restart/reload must preserve state-file gate, target validation, remote failure semantics and no-retry behavior for ambiguous mutations.

Service/infrastructure code should expose typed/domain errors; FastAPI `HTTPException` mapping belongs at the HTTP boundary.

### 5. LifecycleService owns composition semantics

`LifecycleService` must receive its lower-level collaborators explicitly and own current status, versions, health-full, restart and reload behavior.

Preserve current external dictionaries and semantics, including:

```text
status -> supervisor_state + db_workers + code_sha + fetched_at
versions -> current_sha + api + workers + recommendation
health/full -> healthy + issues + runtime details
```

Health degradation remains data, not an exception.

### 6. Runtime target resolution belongs to a narrow composition root

Environment/settings/default target-dir precedence must be resolved outside `lifecycle.py`, preferably in `lifecycle_composition.py` or an equivalent narrow builder.

Do not freeze `GRACE_TARGET_DIR` at import time if current tests/runtime allow it to change after module import.

The composition root may construct:

```text
RuntimeStateStore
SupervisorClient
SupervisorControlService
WorkerReadService
VersionProvider
LifecycleService
```

It must not become a general service registry.

### 7. Lifecycle router is HTTP mapping only

After the packet, `src/grace_control/api/routers/lifecycle.py` may own:

- route declarations;
- request/body/query extraction;
- existing audited Admin control calls;
- obtaining/building `LifecycleService`;
- translation of typed lifecycle/service failures to HTTP responses.

It must not directly own:

- `json` filesystem parsing;
- `os.environ` target resolution;
- `subprocess`;
- direct `httpx.AsyncHTTPTransport(uds=...)`;
- `get_db()` / Worker ORM queries;
- supervisor socket/path business logic;
- status/version/health aggregation rules.

Do not keep old private router helpers (`read_state_file`, `get_git_sha`, `get_db_workers`, `_proxy_supervisor`, `_restart_local`, `_reload_local`) solely for compatibility. Migrate active callers to explicit services/callbacks.

### 8. Admin controls must not import lifecycle-router private helpers

`admin_controls_local.py` must not import `grace_control.api.routers.lifecycle` to call restart/reload helpers.

Lifecycle restart/reload control must be injected through an explicit narrow service/factory/callback while preserving authorization, confirmation and audit semantics.

Do not refactor unrelated packet/archive/merge/maintenance Admin controls in this packet.

## Architecture guard

A durable architecture guard, preferred path

`tests/grace_control/architecture/test_lifecycle_router_boundary.py`

must prove directly or equivalently:

1. lifecycle router does not import/use `os`, `subprocess`, direct `httpx` UDS transport, `get_db`, or `Worker`;
2. lifecycle router performs no ORM query, Git subprocess or state-file JSON parsing;
3. lifecycle router depends on explicit lifecycle service/composition boundary;
4. `admin_controls_local.py` does not import private lifecycle-router helpers;
5. lower-level lifecycle services contain no FastAPI dependency;
6. supervisor control uses the accepted `SupervisorClient` boundary;
7. runtime target resolution is outside the router and not frozen incorrectly at import time.

If the existing guard already proves these and passes, do not duplicate it.

## Required verification

Run at minimum current equivalents of:

```bash
PYTHONPATH=src .venv/bin/pytest -q tests/grace_control/architecture/test_lifecycle_router_boundary.py
PYTHONPATH=src .venv/bin/pytest -q tests/supervisor/test_lifecycle_api.py
```

Discover and run current focused tests for:

```text
LifecycleService
RuntimeStateStore
SupervisorControlService
WorkerReadService
VersionProvider
admin_controls_local restart/reload dispatch
```

Also run:

```bash
make lint
make docs-check
make hygiene
python3 -m py_compile <changed-python-files-if-any>
git diff --check
```

For baseline-aware lint, report canonical `make lint` success separately from raw Ruff/GraceLint debt.

Run final scans:

```bash
rg -n 'read_state_file|get_git_sha|get_db_workers|_proxy_supervisor|_restart_local|_reload_local' \
  src/grace_control/api/routers src/grace_control/services || true

rg -n 'os\.environ|subprocess\.run|AsyncHTTPTransport|get_db\(|query\(Worker' \
  src/grace_control/api/routers/lifecycle.py || true
```

Explain every surviving hit. The lifecycle router should have no direct infrastructure/business ownership represented by those patterns.

## Submission protocol

If corrections are required, commit and push them and use the full 40-character implementation SHA. If current `main` already satisfies the packet, use synced `HEAD` and explicitly state `verified no-op`.

Create only:

`docs/work/agent_exchange/outbox/TZ_GRACE_ARCHITECTURE_REFACTOR_V2_06_LIFECYCLE_SERVICE_EXTRACTION_SUBMISSION.md`

It MUST begin exactly:

```text
WEB_ORCH_REPORT: SUBMISSION TZ_GRACE_ARCHITECTURE_REFACTOR_V2_06_LIFECYCLE_SERVICE_EXTRACTION
WEB_ORCH_STATUS: DONE
WEB_ORCH_COMMIT: <full-40-character-implementation-sha>
WEB_ORCH_CHECKS: PASS
```

Then include:

- synced base SHA and initial status;
- implementation SHA or verified-no-op statement;
- final lifecycle dependency graph;
- thin-router structural evidence;
- target-dir composition evidence;
- supervisor/worker/version ownership evidence;
- Admin-controls restart/reload wiring evidence;
- exact targeted test counts/check results;
- changed paths, or `none` for verified no-op.

Do not create/start the next packet. Wait for Architect ACCEPT/REVIEW.

## Acceptance criteria

Architect ACCEPT requires all of:

1. lifecycle router is a thin FastAPI mapping layer with no direct filesystem state parsing, DB query, Git subprocess or UDS transport ownership;
2. lifecycle state/version/worker/supervisor responsibilities live in explicit lower-level collaborators;
3. `LifecycleService` owns status/version/health/control composition and preserves external semantics;
4. supervisor restart/reload goes through the accepted `SupervisorClient` boundary without retrying ambiguous mutations;
5. runtime target resolution lives outside the router and preserves current dynamic precedence;
6. Admin controls no longer import private lifecycle-router helpers;
7. API routes/status codes/response fields/audit behavior remain compatible;
8. no DB/API/lifecycle-state/packet execution semantic drift occurs;
9. no later wave or lint allowlist expansion is mixed in;
10. architecture/regression checks pass and are truthfully reported;
11. submission follows the exact named-file protocol with a full SHA.
