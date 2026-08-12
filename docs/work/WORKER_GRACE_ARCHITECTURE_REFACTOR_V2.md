# WORKER TZ — GRACE Architecture Refactor V2

Status: READY FOR CODER
Parent TZ: `docs/work/TZ_GRACE_ARCHITECTURE_REFACTOR_V2.md`
Repository: `basilivanov/grace-orchestrator`
Suggested implementation branch: `refactor/grace-architecture-v2`

## 0. Your role

You are the coder. You are NOT the architect.

Implement the parent TZ exactly. Do not reinterpret the architecture, do not preserve intentionally removed legacy, and do not create alternate compatibility paths because they feel safer.

Two names are easy to confuse. Read this twice:

1. **REMOVE the user/control CLI**: `src/grace_control/cli.py`, `grace_ctl`, `python -m grace_control.cli` and CLI-based operator control.
2. **KEEP the internal generic CLI/subprocess execution path used by mini-swe**: `UniversalCliAgentBackend`, `AgentRunService`, `mini_swe_runner.py`, generic process/env/command helpers.

Also:

3. **REMOVE OpenCode-specific runtime completely.** It is legacy and unused.
4. **KEEP mini-swe working.**
5. **Control Plane after bootstrap is HTTP/OpenAPI only.**

If you delete `UniversalCliAgentBackend` just because its filename contains `cli`, you failed this TZ.

## 1. Hard rules before touching code

Do not change:

- packet state semantics;
- packet lifecycle transitions;
- recovery ladder semantics;
- reviewer/verifier/acceptance semantics;
- merge fencing/serialization semantics;
- DB schema;
- API field names;
- current HTTP status behaviour unless an existing route is explicitly removed by this TZ (the control CLI is not an HTTP route);
- mini-swe role contracts;
- existing security/confirmation/audit rules for admin mutations.

Do not:

- add GRC005/GRC012 allowlist entries;
- weaken tests;
- replace integration behaviour with mocks only;
- create `BaseService`, service locator, dependency bag dictionary or global singleton registry to solve cycles;
- add hidden re-export modules for deleted OpenCode/control CLI;
- rename dozens of unrelated files;
- perform a formatting sweep;
- delete DB migrations because a filename says `legacy`;
- modify historical `docs/work/` merely to make `rg opencode` return zero. Historical evidence is allowed to remain.

## 2. Required baseline capture

Before edits run and save results for the final report:

```bash
git status --short
git rev-parse HEAD
git rev-parse --short HEAD
python3 --version
```

Record current tracked suspicious artifacts:

```bash
git ls-files | rg '(^|/)(\.goldw|\.lw3|\.grace-live-wt)(/|$)|%2Ftmp%2F|\.db($|[-.])|src/gold-test'
```

Record OpenCode references:

```bash
rg -n -i 'opencode|agent_runtime_use_opencode_adapter|OPENCODE_' \
  src tests scripts docs/grace docs/SUPERVISOR.md README.md AGENTS.md pyproject.toml docker || true
```

Record control CLI references:

```bash
rg -n 'grace_control\.cli|grace_ctl|python -m grace_control\.cli' \
  src tests scripts docs/grace docs/SUPERVISOR.md README.md AGENTS.md pyproject.toml docker || true
```

Record admin reverse/private dependencies:

```bash
rg -n 'self\._facade|_facade\._hub|_hub\._registry|class .*Mixin' src/grace_control/services/admin_* || true
rg -n '\._artifact_service\s*=|\._session_service\s*=|\._pipeline\s*=' src/grace_control/services/admin_* || true
```

Record lifecycle router infrastructure violations:

```bash
rg -n 'os\.environ|subprocess|get_db\(|\.query\(|supervisor\.json|supervisor\.sock' \
  src/grace_control/api/routers/lifecycle.py
```

Run the current targeted gates and record failures. Do NOT fix unrelated baseline failures before documenting them:

```bash
python3 scripts/grace_lint.py src/grace_control tests scripts
python -m ruff check src/grace_control tests scripts
pytest -q tests/grace_control/api/test_no_cli_business_logic.py || true
pytest -q tests/grace_control/runtime tests/grace_control/agent || true
```

If the project has known pre-existing full-suite failures, record exact count and names before the refactor.

---

# WAVE 1 — REMOVE OPENCODE LEGACY

## 3. Objective

After this block, there must be no live OpenCode runtime implementation, config switch, active profile, env injection, fallback, server manager, event collector, failure classifier or OpenCode-specific test.

Mini-swe remains live.

## 4. First map every live OpenCode dependency

Before deleting files, inspect all hits from:

```bash
rg -n -i 'opencode|agent_runtime_use_opencode_adapter|OPENCODE_' src tests scripts pyproject.toml docker
```

Classify each hit as one of:

- implementation to delete;
- generic code with an OpenCode branch to simplify;
- active profile/config to remove;
- active test to delete or replace;
- historical comment only;
- false positive unrelated to runtime.

Do not start by deleting files and then chasing import errors randomly.

## 5. Delete the OpenCode runtime stack

Physically delete these current files if present:

```text
src/grace_control/runtime/opencode_runtime_adapter.py
src/grace_control/runtime/opencode_command_builder.py
src/grace_control/runtime/opencode_attach_command_builder.py
src/grace_control/runtime/opencode_event_collector.py
src/grace_control/runtime/opencode_failure_classifier.py
src/grace_control/runtime/opencode_server_manager.py
src/grace_control/runtime/opencode_server_state.py
```

Also inspect `src/grace_control/runtime/__init__.py` and remove exports/imports for deleted modules.

Do NOT create stub replacements.

## 6. Remove PacketExecutionAdapter OpenCode branch

File:

`src/grace_control/adapters/packet_executor.py`

Current anti-pattern to remove is the conditional backend creation based on an OpenCode feature flag.

Target behaviour:

```text
if backend was injected -> use injected backend
else -> use the canonical generic backend selection path
```

The adapter must no longer import or dynamically import any `opencode_*` runtime module.

Remove:

- `agent_runtime_use_opencode_adapter` branch;
- dynamic import of `grace_control.runtime.opencode_runtime_adapter`;
- any diagnostics constants imported solely from that runtime stack.

Do NOT change execution/acceptance/recovery behaviour around the backend call.

Immediately run packet-executor focused tests after this edit.

## 7. Remove OpenCode settings

File to inspect first:

`src/grace_control/config/settings.py`

Remove fields that exist only for the deleted OpenCode runtime, including current families equivalent to:

```text
agent_runtime_use_opencode_adapter
opencode_binary
opencode_direct_timeout_seconds
opencode_process_kill_grace_seconds
opencode_json_events_required
opencode_capture_raw_events
opencode_runtime_mode
opencode_server_host
opencode_server_port
opencode_server_url
opencode_server_password
opencode_server_start_timeout_seconds
opencode_server_health_timeout_seconds
opencode_server_restart_on_unhealthy
opencode_server_log_path
opencode_server_pid_path
opencode_server_kill_grace_seconds
```

Search before deleting each setting. If a setting is used only by OpenCode-specific code or OpenCode compatibility inside generic code, remove the consumer too.

Inspect:

`src/grace_control/config/project_config.py`

If there is an `opencode` config section used only to populate deleted settings, remove that schema/config mapping as part of the same block.

Update active config docs accordingly.

Do NOT remove mini-swe/OpenAI-compatible proxy settings merely because the word `OPENAI` appears near old OpenCode settings.

## 8. Remove OpenCode profiles from agent_profiles.yaml

File:

`src/grace_control/config/agent_profiles.yaml`

Rules:

- keep all current mini-swe profiles that invoke `grace_control.runtime.mini_swe_runner`;
- remove profiles whose command invokes the `opencode` binary;
- remove disabled OpenCode profiles too; disabled legacy is still legacy;
- remove old premium/direct/serve-attach profiles if their execution command is OpenCode;
- do not rename mini-swe profile IDs unless a separate reference requires migration;
- do not alter model ladder order except to remove deleted OpenCode entries.

After editing, validate:

```bash
rg -n -i 'opencode' src/grace_control/config/agent_profiles.yaml
```

Expected: zero live hits.

## 9. Simplify AgentProfile only after profile cleanup

File:

`src/grace_control/config/agent_profiles.py`

Inspect fields such as:

- `resume_flag`
- `fork_flag`
- `inject_dir`
- `resume_mode`
- `resume_safe`
- `validate_session_before_use`
- other OpenCode-era knobs

Do NOT blindly delete all of them.

For each field:

1. Search remaining non-OpenCode profiles.
2. Search remaining runtime consumers/tests.
3. If no supported non-OpenCode path uses it, remove it from loader/validation/`to_dict()` and tests.
4. If a remaining generic/mini-swe path genuinely uses it, keep it and remove only OpenCode-specific assumptions/comments.

The goal is to remove dead OpenCode configuration, not to break generic runtime capabilities.

## 10. Remove OpenCode branches from UniversalCliAgentBackend

File:

`src/grace_control/agent/universal_cli_backend.py`

Remove OpenCode-specific environment injection such as current mappings around:

```text
OPENCODE_SERVER_URL
OPENCODE_SERVER_PASSWORD
```

Remove helper functions that exist solely to detect whether a profile references those env vars.

Keep:

- generic executor env handling;
- AgentRunService call;
- mini-swe support;
- generic artifact/stdout/stderr mapping.

## 11. Remove OpenCode branches from AgentRunService

File:

`src/grace_control/services/agent_run_service.py`

Remove logic only needed by OpenCode, including current examples such as:

- OpenCode-specific session ID patterns;
- `_opencode_session_usable`;
- binary-name fallback that auto-detects `opencode` for `inject_dir`;
- comments/contracts that describe OpenCode as a supported runtime.

For generic resume/session code:

- keep it only if at least one remaining supported non-OpenCode profile uses it;
- otherwise remove the dead generic-looking compatibility path too, with tests.

Do not change cwd/worktree safety checks.

## 12. Remove OpenCode tests

Find all OpenCode runtime tests:

```bash
find tests -type f | sort | rg 'opencode|OpenCode'
rg -l -i 'opencode' tests
```

Delete tests whose sole purpose is to preserve removed OpenCode behaviour.

Do not keep deleted behaviour by rewriting those tests to expect a stub.

Add architecture guard tests under an appropriate current test area, for example:

`tests/grace_control/architecture/test_no_opencode_legacy.py`

It must assert at least:

- no `src/grace_control/runtime/opencode_*.py` exists;
- `settings.py` does not define `agent_runtime_use_opencode_adapter` or `opencode_*` fields;
- active `agent_profiles.yaml` has no OpenCode command/profile;
- `packet_executor.py` has no OpenCode runtime import/flag branch;
- active source/tests/scripts do not import OpenCode runtime modules.

Do not scan historical `docs/work/` in this test.

## 13. Update active OpenCode docs only

Update current source-of-truth/operator docs that still present OpenCode as supported. Inspect at least:

```text
docs/grace/RUNBOOK_AGENT_PROFILES.md
docs/grace/RUNBOOK_LOCAL_DEV.md
docs/grace/RUNBOOK_DEBUG_PACKET.md
docs/grace/EXECUTION_BACKENDS.md
docs/SUPERVISOR.md
README.md
AGENTS.md
```

Historical evidence such as `docs/work/EVIDENCE_OPENCODE_*.md` may stay unchanged.

## 14. Wave 1 OpenCode verification

Run:

```bash
rg -n -i 'opencode|agent_runtime_use_opencode_adapter|OPENCODE_' \
  src tests scripts docs/grace docs/SUPERVISOR.md README.md AGENTS.md pyproject.toml docker || true
```

Expected live hits: zero, except negative guard tests may contain banned strings.

Then:

```bash
pytest -q tests/grace_control/runtime tests/grace_control/agent
python3 scripts/grace_lint.py src/grace_control tests scripts
python -m ruff check src/grace_control tests scripts
```

Fix regressions before moving on.

---

# WAVE 1B — REMOVE USER/CONTROL CLI

## 15. Delete the control CLI

Physically delete:

`src/grace_control/cli.py`

Do not replace it with:

- `cli2.py`;
- a shell wrapper;
- a thin HTTP Typer client;
- an import alias;
- a deprecated stub.

The product decision is API-only control.

## 16. Migrate supervisor bootstrap before deleting CLI references

Inspect:

`scripts/live_supervisor.sh`

If it currently invokes:

```text
python -m grace_control.cli start ...
```

change it to invoke the supervisor bootstrap directly, using the canonical module/entry function exposed by `src/grace_control/supervisor.py`.

Preferred shape is equivalent to:

```text
python -m grace_control.supervisor --target-dir ... --source-dir ...
```

Use the actual supported supervisor arguments from the module. Do not invent flags.

Important:

- startup/bootstrap may be a script/systemd concern;
- runtime control after startup is HTTP API only.

## 17. Remove CLI references from lifecycle errors/docs

File:

`src/grace_control/api/routers/lifecycle.py`

Replace user-facing messages such as:

```text
start it with scripts/live_supervisor.sh or python -m grace_control.cli start
```

with bootstrap instructions that do not mention the removed CLI.

Do not refactor the whole lifecycle router yet; that happens in Wave 4.

## 18. Remove Typer if no longer used

Search:

```bash
rg -n '(^| )import typer|from typer' src scripts tests
```

If zero live imports remain after deleting `cli.py`:

- remove `typer` from `pyproject.toml` dev dependencies;
- remove it from `docker/requirements.txt` if present solely for the deleted CLI;
- update lock/requirements files only if this repository tracks them.

Do not remove `rich` or other dependencies without the same evidence.

## 19. Replace old CLI test with removal guard

Current test to inspect:

`tests/grace_control/api/test_no_cli_business_logic.py`

The old contract "CLI may exist but must not contain business logic" is obsolete.

Replace it with an API-only architecture test whose contract is:

- `src/grace_control/cli.py` must not exist;
- no public package script named `grace`, `grace-dev`, `prefect-grace`, `gracectl`, or `grace_ctl` is exposed;
- active scripts/docs do not invoke `grace_control.cli` or `grace_ctl`;
- API/OpenAPI remains available.

Name may be:

`tests/grace_control/api/test_no_control_cli_surface.py`

Delete the obsolete test if replaced.

## 20. Update active docs

At minimum inspect/update:

```text
docs/SUPERVISOR.md
docs/grace/API_FIRST_CONTROL_PLANE.md
docs/grace/RUNBOOK_LOCAL_DEV.md
README.md
AGENTS.md
scripts/live_supervisor.sh
```

Current docs that say "CLI is deprecated but may exist as thin HTTP client" must be updated to "control CLI removed".

Do not edit old task/submission/history docs merely to erase history.

## 21. Wave 1B verification

```bash
rg -n 'grace_control\.cli|grace_ctl|python -m grace_control\.cli' \
  src tests scripts docs/grace docs/SUPERVISOR.md README.md AGENTS.md pyproject.toml docker || true
```

Expected: zero active hits except negative guard tests.

Then:

```bash
pytest -q tests/grace_control/api
python3 scripts/grace_lint.py src/grace_control tests scripts
python -m ruff check src/grace_control tests scripts
```

---

# WAVE 2 — ADMIN CROSS-PROJECT COMPOSITION

## 22. Goal

Replace hidden-member mixins with explicit composition.

Current facade:

`src/grace_control/services/admin_cross_project_service.py`

Current mixins/helpers to inspect:

```text
admin_cross_project_overview_mixin.py
admin_cross_project_query_mixin.py
admin_cross_project_helpers.py
project_client.py
```

## 23. Create CrossProjectTransport

Create:

`src/grace_control/services/admin_cross_project_transport.py`

Class name:

`CrossProjectTransport`

Responsibilities ONLY:

- hold `ProjectRegistry`;
- hold `client_factory`;
- validate fan-out/timeouts;
- list/select project contexts;
- bounded concurrency;
- execute one project request;
- normalize transport/result errors;
- health identity mismatch validation if currently part of the transport boundary;
- capability-unavailable normalization if currently transport-level.

Required public/internal methods equivalent to:

```python
class CrossProjectTransport:
    def list_contexts(self) -> tuple[ProjectContext, ...]: ...
    def select_contexts(self, project: Sequence[str] | str | None) -> tuple[ProjectContext, ...]: ...
    async def fanout(self, contexts, operation_fn, *, operation: str) -> list[Any]: ...
    async def request(self, context: ProjectContext, path: str, params=None, *, operation: str = "read") -> RemoteResult: ...
```

Use the existing normalized remote-result type; move it to this module or a narrow shared contracts module if necessary.

Do not put overview/search DTO composition here.

## 24. Replace overview mixin with service

Rename/rewrite:

`admin_cross_project_overview_mixin.py`

into a non-mixin service, preferred path:

`admin_cross_project_overview_service.py`

Class:

`AdminCrossProjectOverviewService`

Constructor:

```python
__init__(self, transport: CrossProjectTransport)
```

Move existing overview/diagnostics composition logic into it.

It may call only public methods on `transport`.

It must not assume hidden attributes on `self`.

## 25. Replace query mixin with service

Create/rename to:

`admin_cross_project_query_service.py`

Class:

`AdminCrossProjectQueryService`

Constructor:

```python
__init__(self, transport: CrossProjectTransport)
```

Own events/logs/search projections.

No hidden mixin contract.

## 26. Rewrite AdminCrossProjectService as thin facade

`AdminCrossProjectService` should construct or receive:

- one `CrossProjectTransport`;
- one `AdminCrossProjectOverviewService`;
- one `AdminCrossProjectQueryService`.

Its public methods delegate to those owners.

It may expose a read-only `transport` property for application-layer composition if needed by Control Center:

```python
@property
def transport(self) -> CrossProjectTransport:
    return self._transport
```

Do not expose `_registry` as public mutable state.

Delete the old mixin files when no imports remain.

## 27. Add composition guard test

Add a test that fails if:

- `AdminCrossProjectService` inherits `AdminCrossProject*Mixin`;
- active admin cross-project files define a service class ending in `Mixin`;
- overview/query service accesses `_registry`, `_request`, `_fanout` as undeclared hidden members instead of `self._transport`.

Run cross-project tests before continuing.

---

# WAVE 2B — ADMIN CONTROL CENTER DEPENDENCY INVERSION

## 28. Goal

Focused Control Center services must not depend back on the facade that creates them.

Current bad shape to eliminate:

```text
AdminControlCenterProjectService(self_facade)
AdminControlCenterPacketService(self_facade)
AdminControlCenterExplorerService(self_facade)
AdminControlCenterPageService(self_facade)
```

with child calls to `self._facade.*`.

## 29. Create AdminProjectAccess

Create:

`src/grace_control/services/admin_project_access.py`

Class:

`AdminProjectAccess`

Constructor should receive explicit dependencies, preferably:

```python
__init__(
    self,
    transport: CrossProjectTransport,
    *,
    openapi_cache: MutableMapping[str, tuple[float, dict[str, Any]]] | None = None,
)
```

Responsibilities:

- `contexts()` / list configured contexts;
- `context(project_key)` explicit lookup;
- selected-project read via transport;
- own the project-keyed OpenAPI cache used by Control Center explorer;
- only narrow project-access concerns.

Suggested methods:

```python
def contexts(self) -> tuple[ProjectContext, ...]: ...
def context(self, project_key: str) -> ProjectContext: ...
async def read(self, project_key: str, path: str, params=None, *, operation: str = "read") -> dict[str, Any]: ...
@property
def openapi_cache(self) -> MutableMapping[...]: ...
```

Do not include every service in this class. It is not a service locator.

## 30. Stop storing OpenAPI cache on hub private state

Remove patterns equivalent to:

```python
cache = getattr(hub, "_admin_openapi_cache", None)
hub._admin_openapi_cache = cache
```

The cache must be owned by the explicit `AdminProjectAccess` or a dedicated cache collaborator created by the composition root.

No dynamic private attribute injection into `hub`.

## 31. Change focused service constructors

Refactor these files so they receive explicit collaborators and NEVER the facade object:

```text
admin_control_center_project_service.py
admin_control_center_packet_service.py
admin_control_center_explorer_service.py
admin_control_center_page_service.py
```

Delete imports/type-checking imports of `AdminControlCenterService` from child modules.

Typical constructor dependencies should look like:

```text
ProjectService(access, hub, packet_service?)
PacketService(access, hub, artifact/read helpers...)
ExplorerService(access, mutation_service, ...)
PageService(access, hub, ...)
```

Use the smallest actual set required by each owner.

Do NOT pass the facade as a shortcut.

If ProjectService needs PacketService, inject PacketService directly.

If PacketService needs ExplorerService and ExplorerService needs PacketService, do not create a cycle. Extract the shared operation into a lower-level collaborator.

## 32. Keep AdminControlCenterService thin

`src/grace_control/services/admin_control_center.py`

Target responsibilities:

- validate top-level constructor inputs;
- construct explicit collaborators if not injected;
- delegate stable public methods to focused owners;
- preserve public import/method compatibility that remains live.

It must not become the new owner of moved business logic.

Private compatibility methods such as `_packet_page` may remain temporarily only if real tests/callers still use them. If retained, they must delegate directly and be listed in final report with evidence.

Do not add new private compatibility methods.

## 33. Required guard search

After refactor:

```bash
rg -n 'self\._facade|_facade\._hub|_hub\._registry' src/grace_control/services/admin_control_center* src/grace_control/services/admin_project_access.py
```

Expected: zero.

Add an AST/source guard test enforcing this.

Run all Control Center/admin hub tests.

---

# WAVE 3 — ADMIN AGGREGATION CYCLE REMOVAL

## 34. Goal

Eliminate private post-construction collaborator wiring.

Current wiring in `AdminAggregationService` equivalent to:

```python
self._packet._artifact_service = self._artifacts
self._packet._session_service = self._logs
self._pipeline._artifact_service = self._artifacts
```

must be gone.

## 35. Extract PacketRunResolver

Create:

`src/grace_control/services/admin_packet_run_resolver.py`

Class:

`PacketRunResolver`

Move the shared packet/run lookup logic currently exposed indirectly through packet read service callbacks.

It must have no dependency on `AdminAggregationService`.

Suggested responsibilities:

```python
def resolve_packet(...)
def resolve_run(...)
def ordered_runs(...)
```

Only add methods actually needed by multiple services.

## 36. Add narrow read protocols only where needed

Create one small contracts module if necessary:

`src/grace_control/services/admin_read_ports.py`

Examples:

```python
class ArtifactEvidenceReader(Protocol):
    def get_packet_evidence(...): ...

class PacketSessionReader(Protocol):
    def get_packet_sessions(...): ...
```

Do not create a giant protocol mirroring every admin method.

## 37. Constructor-inject every required collaborator

Target wiring in `AdminAggregationService.__init__` should be one-way and complete at construction time.

Example shape:

```text
resolver = PacketRunResolver()
pipeline = AdminPipelineReadService(artifact_reader=...)
artifacts = AdminArtifactReadService(resolver)
logs = AdminLogsReadService(resolver)
packet = AdminPacketReadService(...explicit deps...)
features = AdminFeatureReadService(...explicit deps...)
```

If pipeline and artifacts create a construction cycle, fix the design rather than assigning a private field later. Options:

- make pipeline receive a narrow callable/protocol injected after the artifact reader can be constructed without pipeline;
- move evidence parsing to a lower-level independent `EvidenceReader` used by both;
- move the common read into a new lower-level collaborator.

Preferred solution: lower-level shared reader, not setter injection.

## 38. Delete private setter-style wiring

After refactor:

```bash
rg -n '\._artifact_service\s*=|\._session_service\s*=|\._pipeline\s*=' src/grace_control/services/admin_*
```

There must be no assignment used to inject dependencies after construction.

Internal mutation of actual domain state is not covered by this grep; review hits manually.

Add a guard test.

Run admin aggregation/pipeline/artifact/log tests.

---

# WAVE 4 — LIFECYCLE ROUTER -> SERVICES/PORTS

## 39. Goal

Make `src/grace_control/api/routers/lifecycle.py` a thin HTTP layer.

The router must stop owning:

- target dir resolution from env;
- supervisor state-file parsing;
- supervisor socket transport details;
- Git subprocess version lookup;
- worker DB queries;
- health composition.

## 40. Create RuntimeStateStore

Create:

`src/grace_control/services/runtime_state_store.py`

Responsibilities:

- receive target/runtime directory explicitly/configured;
- locate `supervisor.json`;
- read/parse it;
- return typed/plain state result;
- no FastAPI imports.

Do not read `os.environ` directly here if the config boundary can supply the target path. Environment interpretation belongs in config/composition.

## 41. Create SupervisorControlPort/service

Create:

`src/grace_control/services/supervisor_control_service.py`

Class:

`SupervisorControlService`

Use existing `SupervisorClient` / Unix socket infrastructure.

Responsibilities:

```python
async/sync status
restart(target)
reload()
```

Only include operations that are currently supported and needed.

Do not expose a new CLI.

Convert supervisor transport failures to domain/service errors that router/application layer can map consistently.

## 42. Create WorkerReadService

Create:

`src/grace_control/services/worker_read_service.py`

Responsibilities:

- query Worker rows;
- serialize worker snapshot used by lifecycle/admin health;
- no FastAPI request/response objects.

Reuse elsewhere if a current service duplicates the same worker serialization.

## 43. Create VersionProvider

Preferred path:

`src/grace_control/services/version_provider.py`

Responsibilities:

- return current source/git SHA;
- use existing Git service abstraction if one already exists and is suitable;
- otherwise isolate the subprocess in this one infrastructure service.

Do not leave `subprocess.run(["git", ...])` in the router.

## 44. Create LifecycleService

Create:

`src/grace_control/services/lifecycle_service.py`

Constructor receives:

- `RuntimeStateStore`;
- `SupervisorControlService`;
- `WorkerReadService`;
- `VersionProvider`.

Responsibilities:

- `status()` combined state DTO;
- `versions()` DTO;
- `health_full()` DTO;
- `restart(target)`;
- `reload()`.

Do not put authorization/HTTP Request parsing in this service.

## 45. Rewrite lifecycle router

`src/grace_control/api/routers/lifecycle.py`

Target endpoint shape:

```python
@router.get(...)
async def status(...):
    return lifecycle_service.status()
```

with narrow HTTP exception mapping.

After refactor the router must not contain:

```text
os.environ
subprocess
get_db
.query(
supervisor.json read_text/json.loads
httpx UDS construction
```

If app dependency injection already has a service construction pattern, follow it. Do not introduce a global service locator.

## 46. Remove lifecycle-router imports from admin control dispatcher

Current file to update:

`src/grace_control/api/routers/admin_controls_local.py`

Current legacy dependency equivalent to:

```python
from grace_control.api.routers.lifecycle import _restart_local
from grace_control.api.routers.lifecycle import _reload_local
```

This is router -> router coupling and must be removed.

Inject/use `LifecycleService` or `SupervisorControlService` through the existing admin-control service/composition boundary.

The admin mutation audit/confirmation sequence MUST remain intact.

Do not call the low-level socket directly from `admin_controls_local.py`.

## 47. Lifecycle guard test

Add a test that reads/parses `lifecycle.py` and fails if it imports/uses:

- `subprocess`;
- `os.environ`;
- `get_db`;
- SQLAlchemy `.query` business logic;
- direct `supervisor.json` parsing;
- direct UDS `httpx` construction.

Also test existing lifecycle API response/status behaviour.

Run lifecycle/admin-control tests.

---

# WAVE 5 — TYPED READ MODELS, BOUNDED ONLY

## 48. Goal

Reduce the most dangerous cross-module `dict[str, Any]` contracts without rewriting every dictionary.

## 49. Create a bounded DTO module

Preferred path:

`src/grace_control/services/admin_read_models.py`

Use frozen dataclasses or Pydantic models consistent with current project style.

Prioritize models that cross more than one service boundary:

- `ProjectHealthSnapshot`
- `CrossProjectCoverage`
- `AttentionItem`
- `PipelineStageView`
- `PacketRunSummary`
- `WorkerSnapshot`

Only create a model when at least two components share the contract or when a boundary currently relies on many magic keys.

## 50. Preserve JSON shape

For every converted model:

1. Write characterization test for current JSON keys before changing producer.
2. Introduce typed model.
3. Serialize back to the exact current key names/types.
4. Run API/template tests.

Do not return dataclass reprs/ORM models directly to templates or FastAPI.

Do not rename keys like `project_key`, `fetched_at`, `attention`, `coverage`, `duration_ms`, etc. for style.

## 51. Do not over-convert

Leave local one-function dictionaries alone when typing them adds no boundary value.

This wave is complete when the major shared read contracts are explicit, not when all `dict[str, Any]` disappear.

---

# WAVE 6 — DEAD CODE / REPO HYGIENE

## 52. Audit each candidate, then delete

Initial candidates:

```text
src/hello.py
src/hello_grace.py
tests/test_hello_grace.py
src/grace_control/core/hello.py
src/grace_control/mod.py
tests/grace_control/core/test_mod.py
demo_resources.py
scripts/test_api_integration.py
src/gold-test/
```

For each candidate run searches by:

- path;
- import path;
- exported function/class names;
- basename;
- CI/script references.

Example:

```bash
rg -n 'hello_grace|from hello_grace|import hello_grace' . --glob '!docs/work/**'
rg -n 'grace_control\.mod|register_handler\(|validate_feature\(' . --glob '!docs/work/**'
rg -n 'demo_resources|test_api_integration' . --glob '!docs/work/**'
```

If only its own test references a useless module, that is NOT a reason to keep both. Delete the module and its obsolete test together.

## 53. Old Prefect demo/integration code

`demo_resources.py` and `scripts/test_api_integration.py` currently reference `prefect_grace`-era modules.

If no supported operator workflow invokes them, delete them.

Do not "modernize" dead demo scripts into new product code unless the parent TZ explicitly requires the capability.

## 54. Migration scripts

Inspect:

```text
scripts/migrate_to_grace_package.sh
scripts/validate_migration.sh
scripts/rollback_migration.sh
scripts/MIGRATION_SCRIPTS.md
```

These are candidates, not unconditional deletes.

Delete only if:

- they target obsolete `prefect_grace`/`gracectl` migration paths;
- no active runbook/CI/operator process references them;
- current supported deployments no longer need that migration.

Otherwise classify `MANUAL_REVIEW` in report.

## 55. Remove tracked runtime artifacts

Audit tracked paths such as:

```text
%2Ftmp%2F*
.goldw/
.lw3/
.grace-live-wt/
src/gold-test/
*.db
```

Do not delete real committed fixtures solely by path. Check references/tests first.

For proven runtime/generated state:

- remove from Git index/repository;
- ensure `.gitignore` covers it;
- add repo-hygiene checks so it cannot return.

## 56. Strengthen ci_repo_hygiene.py

File:

`scripts/ci_repo_hygiene.py`

Expand it to detect tracked generated/runtime state.

At minimum cover proven-bad path patterns from this audit.

Keep messages actionable: print exact offending paths.

Do not create a huge generic filesystem scanner with false positives.

## 57. Dead-code audit table

Final report must contain per-candidate columns:

```text
path
decision
delete_confidence_percent
affect_probability_percent
references_found
reason
action
```

Only physically delete candidates with sufficient proof.

---

# WAVE 7 — CI SINGLE SOURCE OF TRUTH

## 58. Goal

Local and GitHub CI must run the same canonical gates instead of maintaining two slightly different implementations.

## 59. Makefile is canonical

Inspect current:

`Makefile`

Target:

- `make test` runs all supported tests, not an accidental subset;
- `make lint` runs Ruff + GraceLint;
- `make docs-check` checks generated docs;
- `make ci` composes canonical test/lint/docs/hygiene gates.

If full `tests/` contains obsolete tests for deleted legacy surfaces, delete those obsolete tests first. Do not preserve them by narrowing `make test`.

## 60. Simplify GitHub Actions

File:

`.github/workflows/ci.yml`

Prefer jobs/steps that call canonical Make targets instead of duplicating Python snippets and policy.

It is acceptable to keep a Python-version matrix, but the actual test/lint/hygiene logic should come from the repository Make/scripts.

Example concept:

```text
install deps
make ci
```

or split canonical Make targets by job if parallel CI is desired:

```text
make test
make lint
make docs-check
python scripts/ci_repo_hygiene.py
```

Do not maintain a second inline implementation of repo hygiene if the script is canonical.

## 61. Final active-doc update

Update current architecture docs to match final state:

- OpenCode runtime removed;
- control CLI removed;
- mini-swe remains current execution path;
- API/OpenAPI is only runtime/operator control surface;
- lifecycle router delegates to service/ports;
- admin services use explicit composition/DI.

Do not rewrite historical submissions/evidence.

---

# FINAL VERIFICATION

## 62. Mandatory legacy scans

Run exactly:

```bash
rg -n -i 'opencode|agent_runtime_use_opencode_adapter|OPENCODE_' \
  src tests scripts docs/grace docs/SUPERVISOR.md README.md AGENTS.md pyproject.toml docker || true

rg -n 'grace_control\.cli|grace_ctl|python -m grace_control\.cli' \
  src tests scripts docs/grace docs/SUPERVISOR.md README.md AGENTS.md pyproject.toml docker || true
```

Allowed results:

- negative architecture tests containing banned terms as test data;
- no active implementation/config/runbook references.

Historical `docs/work/` is intentionally not included.

## 63. Mandatory dependency scans

```bash
rg -n 'self\._facade|_facade\._hub|_hub\._registry' src/grace_control/services/admin_* || true
rg -n 'class .*Mixin' src/grace_control/services/admin_cross_project* || true
rg -n '\._artifact_service\s*=|\._session_service\s*=' src/grace_control/services/admin_* || true
```

Expected: zero architecture violations.

## 64. Lifecycle scan

```bash
rg -n 'os\.environ|subprocess|get_db\(|\.query\(|supervisor\.json|AsyncHTTPTransport' \
  src/grace_control/api/routers/lifecycle.py || true
```

Expected: zero direct infrastructure/business-logic hits in router.

## 65. Size gates

For all touched Python modules:

- <=1000 physical lines;
- no function >4000 estimated tokens;
- target <=800 lines for new focused modules where practical.

Run:

```bash
python3 scripts/grace_lint.py src/grace_control tests scripts
python -m ruff check src/grace_control tests scripts
```

No new allowlist entry is accepted as a fix.

## 66. Test gates

Run focused suites during work, then final:

```bash
make ci
```

If `make ci` fails:

1. compare to recorded baseline;
2. fix every new failure;
3. do not label a new failure "pre-existing" without before-state evidence;
4. include exact remaining pre-existing failures in final report.

## 67. OpenAPI check

Run generated docs/OpenAPI check.

If OpenAPI changes unexpectedly, treat as a regression.

The control CLI removal should not require HTTP route drift.

If an HTTP route is intentionally changed for another reason, STOP and report BLOCKER unless the parent TZ explicitly permits that route change.

---

# WHAT NOT TO DO — COMMON FAILURE MODES

## 68. Wrong: delete every file containing CLI

Do NOT delete:

- `UniversalCliAgentBackend`;
- `AgentRunService`;
- process supervisor used for agent subprocesses;
- mini-swe runner.

Those are internal execution infrastructure, not the removed operator CLI.

## 69. Wrong: keep OpenCode as disabled compatibility

Do not leave:

```text
disabled: true OpenCode profile
agent_runtime_use_opencode_adapter = False
legacy OpenCode import wrapper
OpenCode settings "for compatibility"
```

The decision is physical removal.

## 70. Wrong: split facade into more helpers but keep back-reference

This is NOT accepted:

```python
class NewSmallService:
    def __init__(self, facade):
        self._facade = facade
```

if the service then reads facade private dependencies.

Pass actual narrow collaborators.

## 71. Wrong: solve dependency cycle with setters

Not accepted:

```python
service = Service()
service._other = other
```

Use constructor injection or extract the common lower-level dependency.

## 72. Wrong: router calls another router private helper

Not accepted:

```python
from grace_control.api.routers.lifecycle import _restart_local
```

Routers are transport adapters, not service libraries.

Both routers must call the service layer.

## 73. Wrong: make CI green by narrowing tests

Do not change:

```text
pytest tests
```

to a smaller path just to avoid failures.

Delete obsolete tests only when their product surface was intentionally removed, otherwise fix the regression.

## 74. Wrong: clean all historical docs

Do not spend the packet rewriting hundreds of `docs/work/` historical submissions merely because they mention OpenCode/CLI.

Update current source-of-truth/operator docs; leave history as history.

---

# REQUIRED FINAL REPORT

## 75. Create report

Create:

`docs/work/REPORT_GRACE_ARCHITECTURE_REFACTOR_V2.md`

Required sections:

1. Base SHA / final SHA.
2. Baseline gate results.
3. Wave-by-wave completion table.
4. OpenCode deleted files/settings/profiles/tests.
5. Control CLI deleted files/references/dependencies.
6. Mini-swe regression proof.
7. Admin cross-project old -> new dependency graph.
8. Admin Control Center old -> new dependency graph.
9. Admin aggregation constructor dependency map.
10. Lifecycle/router old -> new owner map.
11. Typed DTOs introduced and exact JSON compatibility proof.
12. Dead-code audit table with confidence percentages.
13. Tracked runtime artifacts removed and hygiene rules added.
14. CI before/after wiring.
15. Module line counts and largest touched function token estimates.
16. Exact tests/gates run.
17. Final legacy/dependency `rg` outputs.
18. OpenAPI drift result.
19. Compatibility facades retained, each with live-reference evidence.
20. Known debt intentionally not addressed.

## 76. Completion statement

Do not write `DONE` unless all parent acceptance criteria are satisfied.

If blocked, return a precise blocker containing:

- file/symbol;
- what requirement cannot be met;
- why;
- evidence/command output;
- smallest decision needed from architect/product owner.

Do not silently preserve legacy to avoid reporting a blocker.