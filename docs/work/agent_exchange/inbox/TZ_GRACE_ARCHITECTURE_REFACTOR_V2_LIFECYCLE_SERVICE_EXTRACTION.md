# TZ_GRACE_ARCHITECTURE_REFACTOR_V2_LIFECYCLE_SERVICE_EXTRACTION — Packet 6: thin lifecycle HTTP boundary

## Packet identity

- `TZ_NAME`: `TZ_GRACE_ARCHITECTURE_REFACTOR_V2_LIFECYCLE_SERVICE_EXTRACTION`
- Role: Coder
- Repository: `/opt/grace-orchestrator`
- Upstream: `origin/main`
- Parent programme: `docs/work/TZ_GRACE_ARCHITECTURE_REFACTOR_V2.md`
- Normative implementation detail: `docs/work/WORKER_GRACE_ARCHITECTURE_REFACTOR_V2.md`, **Wave 4 only**.
- Previous named packet `TZ_GRACE_ARCHITECTURE_REFACTOR_V2_ADMIN_AGGREGATION_CYCLE_REMOVAL` is ACCEPTED.
- Implement **only lifecycle router -> explicit services/ports extraction** in this packet.
- Do **not** start typed Admin DTO work, dead-code cleanup, CI consolidation, mutation-service mixin cleanup, or any later wave.

This packet is self-contained. Do not invent or start another packet. Only Architect ACCEPT authorizes the next named TZ.

## Mandatory sync before work

Before inspecting implementation files or editing anything:

```bash
cd /opt/grace-orchestrator
git switch main
git fetch origin main
git merge --ff-only origin/main
git status --short
git rev-parse HEAD
```

Record synced base SHA and initial `git status --short` in the submission.

Preserve unrelated pre-existing untracked files, including `.env.bak-mini-endpoint-20260705170600` and `parse_list.py` if still present. Do not use `git reset --hard` or `git clean`.

Do not create `state.json`, lock files, orchestration metadata, or any repository-side web-orch state.

---

# Objective

Make `src/grace_control/api/routers/lifecycle.py` a thin HTTP adapter.

Current router directly owns all of the following:

- `GRACE_TARGET_DIR` / settings/default target-dir resolution;
- `supervisor.json` filesystem lookup and JSON parsing;
- `supervisor.sock` path calculation;
- direct `httpx.AsyncHTTPTransport(uds=...)` supervisor transport;
- `git rev-parse` subprocess execution;
- direct `get_db()` + `Worker` ORM query/serialization;
- status/version/health composition;
- private `_restart_local()` / `_reload_local()` functions imported by `admin_controls_local.py`.

That coupling must be removed without changing the public API contract.

Target dependency direction:

```text
HTTP / FastAPI lifecycle router
        -> LifecycleService
            -> RuntimeStateStore
            -> SupervisorControlService -> existing SupervisorClient
            -> WorkerReadService
            -> VersionProvider

admin_controls.py / admin_controls_local.py
        -> explicit LifecycleService or narrow lifecycle control callback
        -> NEVER import private helpers from lifecycle router
```

The router is an HTTP mapping layer only. Infrastructure and business composition live below it.

---

# Frozen product/API invariants

1. Preserve every existing route and method under `/api/admin/lifecycle`:
   - `GET /status`
   - `GET /versions`
   - `GET /health/full`
   - `POST /restart/{target}`
   - `POST /cleanup`
   - `POST /shutdown`
   - `POST /reload`
2. Preserve existing response JSON keys and semantics for `status`, `versions`, and `health/full`.
3. Preserve current HTTP status behavior:
   - missing supervisor state for `/status` and `/versions` -> `503`;
   - missing state before a supervisor mutation -> `503`;
   - state exists but socket/control transport unavailable -> `502`;
   - remote supervisor HTTP failure preserves the remote status/detail behavior as closely as the current implementation;
   - `/health/full` remains `200` when degraded and communicates degradation through `healthy/issues`.
4. Preserve `restart`/`reload` authorization, confirmation and canonical audit path through `legacy_admin_action`. Do **not** bypass the Admin control/audit layer merely because control I/O moves into a service.
5. `cleanup` and `shutdown` legacy aliases remain unavailable/audited exactly as now. Do not make them operational.
6. Preserve restart target validation (`api|workers|all`).
7. Preserve bootstrap wording: no removed CLI may reappear. Startup remains `scripts/live_supervisor.sh`; runtime control remains HTTP API.
8. No DB schema change, no route rename, no response-field rename, no packet/lease/state-machine change.
9. Do not introduce Pydantic/Admin typed DTO migration in this packet; that is a later wave. Internal service return dictionaries are acceptable to preserve exact external JSON.
10. No generic service locator, global dependency registry, `BaseService`, `ManagerFactory`, or mutable singleton.
11. No new GRC005/GRC012 allowlist entries. Touched source files <=1000 physical lines; target <=800 where practical.

---

# Current files to inspect before editing

At minimum inspect:

```text
src/grace_control/api/routers/lifecycle.py
src/grace_control/api/routers/admin_controls.py
src/grace_control/api/routers/admin_controls_local.py
src/grace_control/supervisor_client.py
src/grace_control/config/settings.py
src/grace_control/db/__init__.py
src/grace_control/db/schema.py
src/grace_control/supervisor.py

tests/supervisor/test_lifecycle_api.py
```

Also search for all active imports/usages of:

```text
read_state_file
get_git_sha
get_db_workers
_proxy_supervisor
_restart_local
_reload_local
SupervisorClient
GRACE_TARGET_DIR
GRACE_SUPERVISOR_SOCK
```

Do not assume the known files are the full dependency surface.

---

# Required implementation

## 1. Create `RuntimeStateStore`

Create:

`src/grace_control/services/runtime_state_store.py`

Preferred class:

```python
class RuntimeStateStore:
    def __init__(self, target_dir: Path) -> None: ...
    @property
    def target_dir(self) -> Path: ...
    @property
    def state_path(self) -> Path: ...
    def exists(self) -> bool: ...
    def read(self) -> dict[str, Any] | None: ...
```

Responsibilities only:

- receive `target_dir` explicitly;
- locate `target_dir / "supervisor.json"`;
- expose whether the state file physically exists;
- read and parse JSON;
- return `None` on missing/unreadable/malformed state exactly like the current router helper;
- no FastAPI imports;
- no DB access;
- no Git subprocess;
- no supervisor HTTP transport.

Important compatibility detail: the current mutation proxy distinguishes **state-file missing** from **state content unreadable/malformed** by checking path existence before socket I/O. Therefore `exists()` and `read()` are separate concepts; do not implement control availability solely as `read() is not None` if that changes current mutation semantics.

## 2. Create `VersionProvider`

Create:

`src/grace_control/services/version_provider.py`

Preferred shape:

```python
class VersionProvider:
    def __init__(self, candidates: Sequence[Path]) -> None: ...
    def current_sha(self) -> str: ...
```

Responsibilities:

- isolate `git rev-parse --short HEAD` subprocess execution;
- try candidate directories in deterministic order;
- preserve current timeout/failure semantics: timeout, missing git, invalid repo, OSError -> try next candidate; final result `""`;
- no FastAPI imports;
- no environment reads inside the provider;
- no DB or supervisor socket work.

Current endpoint behavior effectively uses target directory then process cwd when no explicit source directory is supplied. Preserve the current observable result/fallback ordering unless repository evidence proves a different live source-dir contract.

No `subprocess` import may remain in the lifecycle router after this packet.

## 3. Create `WorkerReadService`

Create:

`src/grace_control/services/worker_read_service.py`

Preferred shape:

```python
class WorkerReadService:
    def __init__(self, db_context_factory=...) -> None: ...
    def snapshot(self) -> list[dict[str, Any]]: ...
```

Responsibilities:

- own the `Worker` query;
- preserve the exact current worker projection keys:
  - `worker_id`
  - `status`
  - `current_packet_id`
  - `last_heartbeat`
  - `started_at`
- preserve current timestamp/null representation;
- no FastAPI imports;
- no lifecycle-state filesystem work;
- no Git subprocess.

Prefer constructor injection of the DB context/session factory over importing router state. A focused infrastructure service may use the existing `get_db` boundary internally if that is the repository's canonical DB context API, but the lifecycle router must not.

## 4. Create `SupervisorControlService`

Create:

`src/grace_control/services/supervisor_control_service.py`

Use the existing:

`src/grace_control/supervisor_client.py::SupervisorClient`

Do not reimplement a second HTTP-over-UDS client in the new service.

Preferred responsibilities:

```python
class SupervisorControlService:
    async def status(self) -> dict[str, Any]: ...     # only if actually needed
    async def restart(self, target: str) -> dict[str, Any]: ...
    async def reload(self) -> dict[str, Any]: ...
```

Constructor should receive explicit collaborators/paths, for example:

```python
__init__(
    self,
    state_store: RuntimeStateStore,
    client: SupervisorClient,
)
```

Requirements:

- before restart/reload, preserve the current state-file-exists gate;
- preserve target validation;
- map `SupervisorConnectionError`, `httpx.HTTPStatusError`, timeout/transport failures into **service/domain exceptions**, not `fastapi.HTTPException`;
- no FastAPI imports in this module;
- preserve the current lifecycle proxy timeout of 30 seconds when composing the client unless tests/source prove another accepted contract;
- do not expose `stop()`/cleanup as new lifecycle API operations merely because `SupervisorClient` has them;
- no retry of ambiguous mutations.

Use a small number of explicit exception types in this module or `lifecycle_service.py`, e.g. conceptually:

```text
SupervisorNotRunningError
SupervisorUnavailableError
SupervisorRemoteError(status_code, detail)
```

Names may vary, but router/API code must be able to preserve current HTTP mappings without service code importing FastAPI.

## 5. Create `LifecycleService`

Create:

`src/grace_control/services/lifecycle_service.py`

Constructor receives exactly the lower-level collaborators it needs:

```python
class LifecycleService:
    def __init__(
        self,
        state_store: RuntimeStateStore,
        supervisor: SupervisorControlService,
        workers: WorkerReadService,
        version: VersionProvider,
    ) -> None: ...
```

Own the current composition logic for:

```text
status snapshot
versions snapshot
full health snapshot
restart(target)
reload()
```

Preserve exact current external DTO shapes.

### `status`

Equivalent output:

```json
{
  "supervisor_state": {},
  "db_workers": [],
  "code_sha": "...",
  "fetched_at": "...Z"
}
```

Missing/unreadable state must produce a typed service error that the router maps to current `503` behavior.

### `versions`

Preserve:

- `current_sha`;
- `api: {pid, in_sync: true}`;
- `workers: [{pid, started_at}]`;
- exact recommendation semantics depending on whether workers exist.

### `health/full`

Preserve the current issue rules:

- state missing -> `supervisor state missing`;
- state present without API -> `api not running`;
- state present without workers -> `no workers running`;
- no DB workers -> `no workers registered in DB`;
- endpoint still returns a normal snapshot with `healthy=False`, not an exception.

### control methods

`restart(target)` and `reload()` delegate only to `SupervisorControlService`.

Do not move Admin authorization/confirmation/audit into this service; those remain API/control-boundary responsibilities.

## 6. Add an explicit composition boundary

The router may not read environment variables directly, but current runtime/test semantics resolve target-dir dynamically:

```text
GRACE_TARGET_DIR env -> settings.target_dir -> /tmp/grace-live-wt
```

Preserve that precedence in a narrow composition/config module, preferred path:

`src/grace_control/lifecycle_composition.py`

Preferred API:

```python
def build_lifecycle_service() -> LifecycleService: ...
```

Responsibilities only:

- resolve runtime target path from environment/settings/default;
- construct `RuntimeStateStore`;
- construct explicit `SupervisorClient(target_dir / "supervisor.sock", timeout=30.0)`;
- construct `SupervisorControlService`;
- construct `WorkerReadService`;
- construct `VersionProvider` with the accepted fallback directories;
- return `LifecycleService`.

Rules:

- this is a composition root, not a registry/service locator;
- do not expose arbitrary service lookup by string/type;
- do not mutate global settings;
- do not cache a mutable global singleton unless there is proven application lifecycle infrastructure for safe invalidation;
- specifically preserve tests/runtime behavior where `GRACE_TARGET_DIR` can be set after module import, so avoid import-time freezing of the target directory.

A different narrow path/name is allowed if architecture is cleaner, but environment interpretation must not remain in `lifecycle.py`.

## 7. Rewrite `lifecycle.py` as a thin HTTP adapter

After refactor, `src/grace_control/api/routers/lifecycle.py` may own only:

- FastAPI route declarations;
- request/body/query extraction;
- calling `legacy_admin_action` for audited mutations;
- obtaining the explicitly composed `LifecycleService`;
- translating typed service exceptions to HTTP responses;
- no-response-shape business composition beyond trivial HTTP mapping.

Remove from the router:

```text
json filesystem parsing
os.environ access
subprocess
Path-based supervisor state/socket logic
httpx UDS transport
get_db()
Worker ORM query
health/status/version aggregation rules
```

The following imports must be gone from the router unless a very narrow unrelated reason is proven:

```python
import json
import os
import subprocess
import httpx
from pathlib import Path
from grace_control.db import get_db
from grace_control.db.schema import Worker
```

`datetime` should also move into `LifecycleService` if it exists only to build `fetched_at`.

Do not leave compatibility implementations such as `read_state_file()` / `get_git_sha()` / `get_db_workers()` / `_proxy_supervisor()` in the router merely to satisfy old tests. Update tests to the new service boundaries.

## 8. Remove the router-private control dependency from Admin controls

Current `admin_controls_local.py` imports at runtime:

```python
from grace_control.api.routers.lifecycle import _restart_local
from grace_control.api.routers.lifecycle import _reload_local
```

This is forbidden after the packet.

Refactor the existing `admin_controls.py` -> `admin_controls_local.py` dispatch seam so lifecycle control is an explicit collaborator.

Preferred shape is equivalent to one of:

```python
dispatch_local_action_impl(..., lifecycle_service_fn=build_lifecycle_service, ...)
```

or two narrow callbacks:

```python
dispatch_local_action_impl(..., restart_lifecycle=..., reload_lifecycle=..., ...)
```

Choose the smaller explicit contract that fits current code.

Rules:

- `admin_controls_local.py` must not import `grace_control.api.routers.lifecycle`;
- restart/reload remain within the existing canonical audit/confirmation flow;
- translate typed lifecycle control exceptions to the same HTTP failure semantics before `local_control_action_impl` records its outcome;
- no circular import between lifecycle router and Admin controls;
- do not refactor unrelated packet/archive/merge/maintenance dispatch in this packet.

## 9. Do not broaden `SupervisorClient` without evidence

Modify `src/grace_control/supervisor_client.py` only if needed to support explicit service composition/error preservation.

Allowed examples:

- narrow exception/result preservation required by `SupervisorControlService`;
- line/function-size cleanup if touched.

Do not:

- add an operator CLI;
- add retries to mutating operations;
- turn it into a generic HTTP client;
- change control endpoint paths.

---

# Required architecture guard

Add:

`tests/grace_control/architecture/test_lifecycle_router_boundary.py`

It must fail if the lifecycle boundary regresses.

At minimum assert:

1. `src/grace_control/api/routers/lifecycle.py` has no imports of:
   - `os`
   - `subprocess`
   - `httpx`
   - `get_db`
   - `Worker`
2. lifecycle router does not perform direct:
   - `os.environ` access;
   - `subprocess.run`;
   - ORM `.query(...)`;
   - `supervisor.json` file reads;
   - Unix socket transport construction.
3. router does not define legacy infrastructure helpers equivalent to:
   - `read_state_file`
   - `get_git_sha`
   - `get_db_workers`
   - `_proxy_supervisor`
4. `admin_controls_local.py` does not import `grace_control.api.routers.lifecycle` and contains no `_restart_local` / `_reload_local` dependency.
5. `RuntimeStateStore`, `SupervisorControlService`, `WorkerReadService`, `VersionProvider`, and `LifecycleService` do not import FastAPI.
6. `LifecycleService` constructor receives explicit collaborators rather than constructing hidden global dependencies itself.
7. composition module is not a generic service locator and does not mutate process-global settings.

Prefer AST assertions for imports/calls/definitions; use targeted source-string assertions only where AST is unnecessarily complex.

---

# Required service tests

Add focused tests for the extracted services. Preferred test paths may be:

```text
tests/grace_control/services/test_runtime_state_store.py
tests/grace_control/services/test_version_provider.py
tests/grace_control/services/test_worker_read_service.py
tests/grace_control/services/test_supervisor_control_service.py
tests/grace_control/services/test_lifecycle_service.py
```

Combining small related tests into fewer files is fine if still readable.

At minimum cover:

### RuntimeStateStore
- missing state -> `None`;
- malformed JSON -> `None`;
- valid JSON -> exact mapping;
- `exists()` distinguishes physical presence from parse success.

### VersionProvider
- first valid candidate wins;
- invalid/non-git candidate falls through;
- all candidates fail -> `""`.

Mock subprocess for unit tests; do not require network.

### WorkerReadService
- projection keys and timestamp/null behavior exactly match current router helper.

### SupervisorControlService
- missing state file -> typed not-running error;
- state file exists but socket/client unavailable -> typed unavailable error;
- invalid restart target rejected;
- successful restart/reload delegates once;
- remote HTTP error mapping preserves status/detail information;
- no retry of mutation.

### LifecycleService
- status exact shape;
- status missing-state error;
- versions exact shape/recommendation;
- full health issue matrix and `healthy` boolean;
- restart/reload delegation.

---

# Required regression proof

Run at minimum:

```bash
PYTHONPATH=src .venv/bin/pytest -q tests/supervisor/test_lifecycle_api.py
```

Also run all current Admin control tests that cover `restart_*`, `reload`, local action dispatch and audit behavior. Discover the exact active files with `rg`/pytest collection rather than guessing stale filenames.

Run the new focused service + architecture tests.

Then run:

```bash
python3 scripts/grace_lint.py <all-changed-python-files-and-tests>
ruff check <all-changed-python-files-and-tests>
python3 -m py_compile <all-changed-python-files>
git diff --check
```

If repository-wide lint remains non-zero from pre-existing baseline, do not broaden this packet into unrelated cleanup. Touched files must pass focused lint.

---

# Explicit structural verification

Before submission run searches equivalent to:

```bash
rg -n 'os\.environ|subprocess|httpx|\bget_db\b|\bWorker\b|\.query\(' \
  src/grace_control/api/routers/lifecycle.py || true

rg -n 'read_state_file|get_git_sha|get_db_workers|_proxy_supervisor|_restart_local|_reload_local' \
  src/grace_control/api/routers/lifecycle.py \
  src/grace_control/api/routers/admin_controls.py \
  src/grace_control/api/routers/admin_controls_local.py || true

rg -n 'grace_control\.api\.routers\.lifecycle' \
  src/grace_control/api/routers/admin_controls_local.py || true

rg -n 'from fastapi|import fastapi' \
  src/grace_control/services/runtime_state_store.py \
  src/grace_control/services/supervisor_control_service.py \
  src/grace_control/services/worker_read_service.py \
  src/grace_control/services/version_provider.py \
  src/grace_control/services/lifecycle_service.py || true
```

Interpretation:

- first scan expected zero in lifecycle router;
- second scan expected zero for removed infrastructure/private-control helpers in the listed API modules, except test/architecture guard text elsewhere;
- third scan expected zero;
- fourth scan expected zero.

Manually inspect all hits before claiming PASS.

---

# Acceptance criteria

PASS only if all are true:

1. Lifecycle router is a thin HTTP mapping layer.
2. No environment read, filesystem state parsing, DB query, Git subprocess or UDS `httpx` transport remains in lifecycle router.
3. `RuntimeStateStore` explicitly owns supervisor state-file reads.
4. `VersionProvider` explicitly owns Git SHA subprocess logic.
5. `WorkerReadService` explicitly owns Worker DB serialization.
6. `SupervisorControlService` uses the existing `SupervisorClient` and returns/raises non-FastAPI service contracts.
7. `LifecycleService` owns status/version/health composition and lifecycle control delegation.
8. Target-dir precedence remains `GRACE_TARGET_DIR -> settings.target_dir -> /tmp/grace-live-wt` without request-time global settings mutation.
9. Existing lifecycle routes, response fields and status semantics remain compatible.
10. `/health/full` still returns 200 degraded snapshots.
11. Restart/reload still go through canonical Admin authorization/confirmation/audit flow.
12. `cleanup`/`shutdown` legacy aliases remain audited/unavailable; no new destructive route appears.
13. `admin_controls_local.py` no longer imports private lifecycle-router helpers.
14. No circular dependency is introduced between lifecycle and Admin controls.
15. No new generic service locator/factory registry/base class is introduced.
16. New architecture guard passes.
17. Existing lifecycle and relevant Admin control regressions pass.
18. No schema/API contract change and no later-wave work is included.
19. No new lint/size allowlist exception is added.

---

# Required submission

After implementation, commit and push the implementation to `origin/main`.

Then create only:

`docs/work/agent_exchange/outbox/TZ_GRACE_ARCHITECTURE_REFACTOR_V2_LIFECYCLE_SERVICE_EXTRACTION_SUBMISSION.md`

The submission must begin with these exact lines:

```text
WEB_ORCH_REPORT: SUBMISSION TZ_GRACE_ARCHITECTURE_REFACTOR_V2_LIFECYCLE_SERVICE_EXTRACTION
WEB_ORCH_STATUS: DONE
WEB_ORCH_COMMIT: <implementation-commit-sha>
WEB_ORCH_CHECKS: PASS
```

`WEB_ORCH_COMMIT` must be the actual implementation commit, not the submission-document commit.

Submission body must include:

- synced base SHA;
- initial status/untracked preservation;
- exact changed files;
- final dependency graph;
- exact explanation of target-dir composition and dynamic env behavior;
- how supervisor errors map to API status codes;
- how Admin restart/reload dispatch was decoupled from lifecycle router without bypassing audit;
- structural scan results;
- exact tests/checks and counts;
- any documented pre-existing baseline failure only if actually encountered.

Do not create a next task. Do not start Wave 5.