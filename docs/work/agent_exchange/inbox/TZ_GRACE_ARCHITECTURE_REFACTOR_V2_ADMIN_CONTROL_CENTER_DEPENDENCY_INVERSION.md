# TZ_GRACE_ARCHITECTURE_REFACTOR_V2_ADMIN_CONTROL_CENTER_DEPENDENCY_INVERSION — Packet 4: explicit Control Center dependencies

## Packet identity

- `TZ_NAME`: `TZ_GRACE_ARCHITECTURE_REFACTOR_V2_ADMIN_CONTROL_CENTER_DEPENDENCY_INVERSION`
- Role: Coder
- Repository: `/opt/grace-orchestrator`
- Upstream: `origin/main`
- Parent programme: GRACE Architecture Refactor V2
- Previous named packet `TZ_GRACE_ARCHITECTURE_REFACTOR_V2_ADMIN_CROSS_PROJECT_COMPOSITION` is ACCEPTED.
- Implement **only Admin Control Center dependency inversion (Wave 2B)** in this packet.
- Do **not** start Admin Aggregation cycle removal, lifecycle-router extraction, typed admin DTO work, dead-code cleanup, CI consolidation, mutation-service mixin refactor, or any later wave.

This named packet is self-contained. Do not invent or read another packet as implementation authority. Only Architect ACCEPT authorizes the next named TZ.

## Mandatory sync before any work

Before inspecting implementation files or editing anything:

```bash
cd /opt/grace-orchestrator
git switch main
git fetch origin main
git merge --ff-only origin/main
git status --short
git rev-parse HEAD
```

Record the synced base SHA and initial `git status --short` in the submission.

Preserve unrelated pre-existing untracked files, including `.env.bak-mini-endpoint-20260705170600` and `parse_list.py` if still present. Do not run `git reset --hard` or `git clean`.

Do not create `state.json`, lock files, orchestration metadata, or other repository-side web-orch state.

---

# Objective

Remove the reverse dependency:

```text
AdminControlCenterService
    constructs child service with `self`
        -> child stores `self._facade`
            -> child reaches back into facade
                -> facade reaches into hub private state / sibling child
```

The accepted Wave 2 transport already provides the explicit boundary:

```text
AdminCrossProjectService.transport -> CrossProjectTransport
```

After this packet the Control Center composition must be one-way:

```text
AdminControlCenterService                 # thin composition root + stable public facade
    -> AdminProjectAccess                 # project context/read/cache boundary
    -> AdminControlCenterProjectService   # explicit deps only
    -> AdminControlCenterPacketService    # explicit deps only
    -> AdminControlCenterExplorerService  # explicit deps only
    -> AdminControlCenterPageService      # explicit deps only
    -> AdminMutationService               # injected only where mutation is required
```

No focused child service may receive `AdminControlCenterService` or use `self._facade`.

---

# Current problems that MUST be removed

On the accepted base, examples include:

```python
AdminControlCenterProjectService(self)
AdminControlCenterPacketService(self)
AdminControlCenterExplorerService(self)
AdminControlCenterPageService(self)
```

Child modules currently contain patterns equivalent to:

```python
self._facade._hub._registry.list_projects()
self._facade._hub.get_projects_overview(...)
self._facade._context(project_key)
self._facade._read(project_key, ...)
self._facade._packet_page(...)
self._facade.files_page(...)
self._facade._explorer_shell(...)
self._facade.dashboard()
self._facade._selector_current(...)
```

`AdminControlCenterService.__init__` also currently stores the OpenAPI cache dynamically on Hub private state with logic equivalent to:

```python
cache = getattr(hub, "_admin_openapi_cache", None)
if not isinstance(cache, dict):
    cache = {}
    hub._admin_openapi_cache = cache
```

All of the above reverse/private coupling must be removed from the Control Center graph.

Important: `AdminMutationService` and its existing mutation mixins still use temporary private compatibility seams on `AdminCrossProjectService` (`_registry`, `_request`, `_client_factory`). **Do not refactor that mutation architecture in this packet.** It is outside Wave 2B. Control Center code must simply stop depending on those private Hub seams directly.

---

# Product / behavior invariants

1. Preserve the public import/class name `AdminControlCenterService`.
2. Preserve the live constructor shape `AdminControlCenterService(hub: AdminCrossProjectService)` unless adding optional keyword-only collaborator injection without breaking existing callers.
3. Preserve all current public method names/signatures/DTO shapes, including:
   - `contexts`
   - `dashboard`
   - `project_page`
   - `system_page`
   - `maintenance_page`
   - `events_page`
   - `logs_page`
   - `files_page`
   - `git_page`
   - `api_page`
   - `search_page`
4. Preserve routes/templates; do not edit HTTP route contracts unless a minimal import/wiring change is required.
5. Preserve project selection order and disabled/offline behavior.
6. Preserve filesystem path safety, Git/OpenAPI explorer safety, masking, bounded reads, cursor behavior and mutation confirmation policy.
7. Hub/project access remains API/runtime-boundary only. Do not open another project's SQLite/filesystem/Git directly.
8. No database schema changes.
9. No process-global project/settings mutation.
10. Do not change packet lifecycle/runtime semantics.
11. No generic `BaseService`, service locator, dependency dictionary, manager factory or global registry.
12. No new GRC005/GRC012 allowlist exceptions. Touched source files remain <=1000 physical lines; target <=800 where practical.

---

# Mandatory inventory before editing

Inspect at least:

```text
src/grace_control/services/admin_control_center.py
src/grace_control/services/admin_control_center_project_service.py
src/grace_control/services/admin_control_center_packet_service.py
src/grace_control/services/admin_control_center_explorer_service.py
src/grace_control/services/admin_control_center_page_service.py
src/grace_control/services/admin_cross_project_service.py
src/grace_control/services/admin_cross_project_transport.py
src/grace_control/services/admin_mutation_service.py
src/grace_control/services/admin_mutation_transport.py
src/grace_control/api/routers/admin_control_center.py
src/grace_control/api/routers/admin_hub.py
```

Before changing code, record every current Control Center facade-backreference:

```bash
rg -n 'self\._facade|_facade\._hub|_hub\._registry|_hub\._request|_hub\._client_factory' \
  src/grace_control/services/admin_control_center*.py
```

Also inventory private compatibility methods on `AdminControlCenterService` and classify each as:

```text
LIVE_EXTERNAL_COMPAT     # real caller/test outside child services
CHILD_ONLY_BRIDGE        # exists only because child services call facade
DEAD                     # no active caller
```

Do not guess. Use `rg`/tests/imports.

---

# Required implementation

## 1. Create `AdminProjectAccess`

Create:

`src/grace_control/services/admin_project_access.py`

Class:

`AdminProjectAccess`

Preferred constructor:

```python
from collections.abc import MutableMapping

class AdminProjectAccess:
    def __init__(
        self,
        transport: CrossProjectTransport,
        *,
        openapi_cache: MutableMapping[str, tuple[float, dict[str, Any]]] | None = None,
    ) -> None:
        ...
```

It is a **narrow project-access boundary**, not a service locator.

Responsibilities only:

- list immutable configured contexts in registry order;
- resolve one explicit project context by key;
- perform one selected-project read through `CrossProjectTransport.request`;
- normalize that `_RemoteResult` into the exact dict shape currently returned by `AdminControlCenterService._read`;
- own/expose the project-keyed OpenAPI cache used by explorer code.

Expected API equivalent to:

```python
def contexts(self) -> tuple[ProjectContext, ...]: ...
def context(self, project_key: str) -> ProjectContext: ...

async def read(
    self,
    project_key: str,
    path: str,
    *,
    params: Mapping[str, Any] | None = None,
    operation: str,
) -> dict[str, Any]: ...

@property
def openapi_cache(self) -> MutableMapping[str, tuple[float, dict[str, Any]]]: ...
```

Implementation rules:

- `contexts()` should use the accepted transport/registry boundary, not `hub._registry`.
- `context(project_key)` must preserve current unknown-key `KeyError` behavior.
- `read()` must preserve the exact current normalized keys:
  - `ok`
  - `payload`
  - `error`
  - `error_class`
  - `http_status`
  - `headers`
- no direct DB/fs/Git access;
- no mutation methods;
- no references to ProjectService/PacketService/ExplorerService/PageService.

## 2. Move OpenAPI cache ownership off Hub private state

Delete the dynamic Hub mutation pattern from `AdminControlCenterService.__init__`:

```python
getattr(hub, "_admin_openapi_cache", ...)
hub._admin_openapi_cache = ...
```

Create the cache in the Control Center composition root and pass it to `AdminProjectAccess`, or let `AdminProjectAccess` create it.

There must be no `_admin_openapi_cache` attribute injected into `AdminCrossProjectService` by Control Center code after this packet.

The existing cache TTL/key semantics must remain compatible.

## 3. Refactor `AdminControlCenterProjectService`

File:

`src/grace_control/services/admin_control_center_project_service.py`

It must no longer:

- import `AdminControlCenterService` for constructor typing;
- accept `facade`;
- store `self._facade`;
- reach `._hub._registry`;
- call facade private `_context`, `_read`, `_packet_page`, `_explorer_shell` etc.

Inject the smallest real collaborators.

Expected dependency set is approximately:

```text
AdminProjectAccess
AdminCrossProjectService              # only for public overview reads if still needed
packet-page callable/service          # only if project_page really needs it
```

Prefer concrete narrow collaborators over callbacks when there is a real domain owner.

ProjectService should use:

- `access.contexts()` / `access.context()` for registry context;
- `access.read()` for selected-project reads;
- public Hub methods for cross-project overview if required.

Do not create a dependency from ProjectService back to `AdminControlCenterService`.

## 4. Refactor `AdminControlCenterPacketService`

File:

`src/grace_control/services/admin_control_center_packet_service.py`

Replace every `self._facade._read(...)` with explicit project access.

Packet tabs that currently call public facade explorer methods (for example Files/Git) must receive the actual explorer collaborator or a narrower lower-level collaborator directly.

Do not solve dependency order by setting private fields after construction.

No pattern like:

```python
packet._explorer = explorer
project._packet = packet
```

after object creation unless it is ordinary immutable constructor assignment inside `__init__`. Post-construction dependency mutation is forbidden.

## 5. Refactor `AdminControlCenterExplorerService`

File:

`src/grace_control/services/admin_control_center_explorer_service.py`

It must receive explicit dependencies instead of facade. Likely real dependencies include:

```text
AdminProjectAccess
project-shell/selector collaborator or ProjectService
AdminMutationService
```

Use `AdminProjectAccess.openapi_cache` for the existing OpenAPI cache.

Do not instantiate `AdminMutationService` repeatedly per request. Construct it at the composition root and inject it.

Preserve all existing path-safety/OpenAPI discovery/mutation gating behavior.

## 6. Refactor `AdminControlCenterPageService`

File:

`src/grace_control/services/admin_control_center_page_service.py`

It must not use:

```python
self._facade._hub...
self._facade.dashboard()
self._facade._selector_current(...)
```

Inject the actual dependencies, expected approximately:

```text
AdminCrossProjectService
project/dashboard/selector collaborator
```

Do not duplicate dashboard or selector business logic just to avoid injection.

## 7. Resolve the Project ↔ Packet ↔ Explorer dependency graph without a cycle

Current behavior creates an implicit cycle through facade methods:

```text
ProjectService.project_page -> facade._packet_page -> PacketService
PacketService Files/Git tabs -> facade.files_page/git_page -> ExplorerService
ExplorerService shell/context -> facade._explorer_shell/_context -> ProjectService/access
```

Do **not** reproduce this as constructor cycle:

```text
ProjectService -> PacketService -> ExplorerService -> ProjectService
```

Choose a narrow lower-level owner for the shared shell/selector behavior if needed.

A valid solution may extract a narrowly named collaborator such as a project-shell/selector builder that owns only:

- project context metadata merge;
- selector project rows/current project row;
- explorer shell composition from access + Hub overview.

Do not create a vague `_helpers.py` object or `AdminServices` dependency bag.

If no extraction is needed because existing functions can become pure helpers with explicit arguments, that is also acceptable.

The final dependency graph must be acyclic and complete at construction time.

## 8. Keep `AdminControlCenterService` thin

File:

`src/grace_control/services/admin_control_center.py`

Target responsibilities:

- validate top-level Hub input;
- construct `AdminProjectAccess` and focused collaborators in acyclic order;
- construct one `AdminMutationService(hub)` if needed by ExplorerService;
- delegate stable public methods to focused owners;
- retain only proven live private compatibility delegates.

It must not become a replacement business-logic god object.

Private methods currently used only by child services should disappear once children have explicit dependencies.

Examples expected to disappear unless a real external caller is proven:

```text
_read
_context
_explorer_shell
_project_card
_cards
_context_info
_selector_projects
_selector_current
```

`_packet_page` / `_scope_rows_to_run` may remain temporarily **only if an actual caller outside focused child services exists**. If retained, submission must list each method and the exact caller/test requiring it.

Do not add any new private compatibility method.

## 9. Do not refactor mutation internals in this packet

`AdminMutationService` may continue to depend on `AdminCrossProjectService` and its temporary private Hub compatibility seams.

Allowed:

```python
mutation_service = AdminMutationService(hub)
explorer_service = AdminControlCenterExplorerService(..., mutation_service=mutation_service)
```

Not allowed in this packet:

- rewriting AdminMutationService mixins;
- changing mutation confirmation/security semantics;
- removing Hub private seams that mutation still genuinely needs;
- broad mutation architecture cleanup.

That work must be separately authorized if needed.

---

# Required architecture guard

Add a focused test, preferred path:

`tests/grace_control/architecture/test_admin_control_center_dependency_inversion.py`

It must fail if:

1. Any focused Control Center child class stores/uses `self._facade`.
2. Child modules import `AdminControlCenterService` only to use it as constructor dependency.
3. Active Control Center child modules contain `_facade._hub`, `_hub._registry`, `_hub._request`, or `_hub._client_factory` access.
4. `AdminControlCenterService.__init__` injects `_admin_openapi_cache` dynamically onto Hub.
5. `AdminProjectAccess` grows references to focused services (service-locator regression).
6. Focused child constructors accept `AdminControlCenterService`.
7. Post-construction private dependency assignment is introduced between Project/Packet/Explorer/Page services.

Prefer AST/introspection assertions to broad fragile string checks.

After refactor this search MUST be zero in the named scope:

```bash
rg -n 'self\._facade|_facade\._hub|_hub\._registry|_hub\._request|_hub\._client_factory' \
  src/grace_control/services/admin_control_center*.py \
  src/grace_control/services/admin_project_access.py
```

Historical docs are excluded.

Also verify:

```bash
rg -n '_admin_openapi_cache' src/grace_control/services/admin_control_center*.py src/grace_control/services/admin_project_access.py
```

Expected: zero dynamic Hub state injection. A cache field owned by `AdminProjectAccess` may have a different internal name.

---

# Required regression proof

At minimum run the complete existing Control Center / Hub regression surface relevant to this graph, including:

```bash
PYTHONPATH=src .venv/bin/pytest -q \
  tests/grace_control/api/test_admin_cross_project_observability.py \
  tests/grace_control/api/test_admin_hub_project_foundation.py \
  tests/grace_control/api/test_admin_control_center_stage07.py \
  tests/grace_control/api/test_admin_control_center_stage07_matrix.py
```

Discover and run all other tests whose filenames/content exercise:

```text
AdminControlCenterService
AdminControlCenterProjectService
AdminControlCenterPacketService
AdminControlCenterExplorerService
AdminControlCenterPageService
```

Run the new architecture guard.

Also run:

```bash
ruff check <all changed Python files>
python3 scripts/grace_lint.py <all changed Python files>
python3 -m py_compile <all changed production Python files>
git diff --check
```

If repository-wide lint has pre-existing failures, do not clean unrelated debt. Prove all touched files pass packet-scoped lint/checks.

No new size/canon allowlist entry is allowed.

---

# Explicit structural verification before submission

Run and report results equivalent to:

```bash
rg -n 'self\._facade|_facade\._hub|_hub\._registry|_hub\._request|_hub\._client_factory' \
  src/grace_control/services/admin_control_center*.py \
  src/grace_control/services/admin_project_access.py || true

rg -n 'AdminControlCenterService' \
  src/grace_control/services/admin_control_center_project_service.py \
  src/grace_control/services/admin_control_center_packet_service.py \
  src/grace_control/services/admin_control_center_explorer_service.py \
  src/grace_control/services/admin_control_center_page_service.py || true

rg -n '_admin_openapi_cache' \
  src/grace_control/services/admin_control_center*.py \
  src/grace_control/services/admin_project_access.py || true
```

Expected:

- zero facade-backreference hits;
- zero child constructor/type-dependency on `AdminControlCenterService`;
- zero Hub dynamic OpenAPI-cache injection;
- any remaining private compatibility methods on top-level facade are explicitly proven by real external callers.

---

# Acceptance criteria

PASS only if all are true:

1. `AdminProjectAccess` exists as a narrow explicit boundary over `CrossProjectTransport`.
2. OpenAPI cache is owned by explicit Control Center composition, not injected onto Hub private state.
3. ProjectService does not receive/store the Control Center facade.
4. PacketService does not receive/store the Control Center facade.
5. ExplorerService does not receive/store the Control Center facade.
6. PageService does not receive/store the Control Center facade.
7. No focused child reaches `_facade._hub`, `_hub._registry`, `_hub._request`, or `_hub._client_factory`.
8. The focused dependency graph is acyclic and constructor-complete.
9. No post-construction private collaborator wiring is introduced.
10. Public `AdminControlCenterService` constructor/method signatures remain compatible.
11. Existing page/packet/explorer JSON contracts and safety semantics remain compatible.
12. No route/schema/project-registry/mutation-policy behavior changes.
13. Mutation internals are not broadened into this refactor.
14. Architecture guard passes.
15. Relevant Control Center/Admin Hub regressions pass.
16. Touched files pass packet-scoped Ruff/GraceLint/py_compile/diff-check.
17. No later Wave 3+ work is started.

---

# Required submission protocol

After implementation:

1. Commit the implementation.
2. Push to `origin/main`.
3. Create **only**:

`docs/work/agent_exchange/outbox/TZ_GRACE_ARCHITECTURE_REFACTOR_V2_ADMIN_CONTROL_CENTER_DEPENDENCY_INVERSION_SUBMISSION.md`

Do not create another task/review/state file.

The submission must begin with these exact lines:

```text
WEB_ORCH_REPORT: SUBMISSION TZ_GRACE_ARCHITECTURE_REFACTOR_V2_ADMIN_CONTROL_CENTER_DEPENDENCY_INVERSION
WEB_ORCH_STATUS: DONE
WEB_ORCH_COMMIT: <full-commit-sha>
WEB_ORCH_CHECKS: PASS
```

Then report:

- synced base SHA;
- initial git status and preserved unrelated files;
- exact changed/added/deleted files;
- dependency graph before/after;
- all removed facade-backreferences;
- ownership of OpenAPI cache after refactor;
- any retained private `AdminControlCenterService` compatibility method with exact live caller evidence;
- tests/checks with exact pass/fail counts;
- final forbidden-reference scans;
- confirmation that Wave 3+ was not started.

Do not invent the next packet. Only Architect ACCEPT authorizes it.
