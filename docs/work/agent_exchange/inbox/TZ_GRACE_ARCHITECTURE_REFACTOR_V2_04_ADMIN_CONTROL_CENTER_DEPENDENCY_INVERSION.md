# TZ_GRACE_ARCHITECTURE_REFACTOR_V2_04_ADMIN_CONTROL_CENTER_DEPENDENCY_INVERSION — Packet 04: explicit Control Center dependencies

## Packet identity

- `TZ_NAME`: `TZ_GRACE_ARCHITECTURE_REFACTOR_V2_04_ADMIN_CONTROL_CENTER_DEPENDENCY_INVERSION`
- Role: Coder
- Repository: `/opt/grace-orchestrator`
- Upstream: `origin/main`
- Parent source: `docs/work/TZ_GRACE_ARCHITECTURE_REFACTOR_V2.md`
- Normative detail: Architecture Refactor V2 Wave 2B — Admin Control Center dependency inversion only.
- Previous new-cycle packet `TZ_GRACE_ARCHITECTURE_REFACTOR_V2_03_ADMIN_CROSS_PROJECT_COMPOSITION` is ACCEPTED.
- Historical agent-exchange packets from earlier cycles are evidence only. Do not edit or reuse their submission/review files.

Implement only this named packet. Do not start Admin aggregation-cycle removal, lifecycle extraction, typed admin read models, dead-code cleanup, CI consolidation, or broad mutation-service refactoring.

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

Record synced base SHA and initial status in the submission. Preserve unrelated untracked files. Do not use `git reset --hard`, `git clean`, destructive checkout, repo-side `state.json`, lock files, or orchestration metadata.

## Current-state rule

This new cycle verifies/refines a repository that may already contain an earlier accepted implementation of this architecture.

1. Current synced `main` is authoritative.
2. Do not recreate facade backreferences/private Hub coupling merely because the parent TZ describes the historical starting point.
3. Audit actual current code before changing anything.
4. If every acceptance criterion is already satisfied, run the required verification and submit a **verified no-op** using the synced `HEAD` as `WEB_ORCH_COMMIT`.
5. Do not manufacture source edits merely to produce a diff.
6. If a gap exists, make only the smallest in-scope correction, commit/push it, and report the actual implementation SHA.

## Objective

Ensure Admin Control Center uses a one-way, explicit dependency graph instead of child-service → facade → Hub/private-state backreferences.

Target shape:

```text
AdminControlCenterService                # thin composition root + stable public facade
    -> AdminProjectAccess                # project context/read/cache boundary
    -> AdminControlCenterProjectShell    # shared shell/selector owner where needed
    -> AdminControlCenterProjectService  # explicit dependencies only
    -> AdminControlCenterPacketService   # explicit dependencies only
    -> AdminControlCenterExplorerService # explicit dependencies only
    -> AdminControlCenterPageService     # explicit dependencies only
    -> AdminMutationService              # injected only where mutation is required
```

No focused child service may receive `AdminControlCenterService`, store `self._facade`, reach `._facade._hub`, or depend on post-construction private collaborator mutation.

## Frozen invariants

Preserve:

- public import/class `AdminControlCenterService`;
- live constructor compatibility `AdminControlCenterService(hub: AdminCrossProjectService)`;
- public methods/argument shapes/DTO behavior for dashboard, project, system, maintenance, events, logs, files, Git, API and search pages;
- existing HTTP routes/templates/OpenAPI contracts;
- project ordering and disabled/offline behavior;
- filesystem path safety, bounded reads, Git/OpenAPI explorer safety and masking;
- mutation confirmation/security semantics;
- project-local API/runtime boundary — no direct cross-project DB/filesystem/Git access;
- DB schema/Alembic;
- packet lifecycle/execution/reviewer/recovery/merge semantics;
- Packet 03 explicit `AdminCrossProjectService.transport` boundary.

Do not introduce `BaseService`, a service locator, dependency bag, manager factory, global registry, new GRC005/GRC012 allowlist entries, or a replacement control CLI.

## Audit before edits

Inspect at minimum:

```text
src/grace_control/services/admin_control_center.py
src/grace_control/services/admin_project_access.py
src/grace_control/services/admin_control_center_project_shell.py
src/grace_control/services/admin_control_center_project_service.py
src/grace_control/services/admin_control_center_packet_service.py
src/grace_control/services/admin_control_center_explorer_service.py
src/grace_control/services/admin_control_center_page_service.py
src/grace_control/services/admin_cross_project_service.py
src/grace_control/services/admin_cross_project_transport.py
src/grace_control/services/admin_mutation_service.py
src/grace_control/api/routers/admin_control_center.py
src/grace_control/api/routers/admin_hub.py
```

Some of the preferred extracted files may already exist. Treat current code as authoritative.

Run structural inventory:

```bash
rg -n 'self\._facade|_facade\._hub|_hub\._registry|_hub\._request|_hub\._client_factory|_admin_openapi_cache' \
  src/grace_control/services/admin_control_center*.py \
  src/grace_control/services/admin_project_access.py || true

rg -n '\._artifact_service\s*=|\._session_service\s*=|\._pipeline\s*=|\._packet\s*=|\._explorer\s*=' \
  src/grace_control/services/admin_control_center*.py || true
```

Classify any remaining private compatibility delegate as:

```text
LIVE_EXTERNAL_COMPAT
CHILD_ONLY_BRIDGE
DEAD
```

Do not guess; prove callers with search/tests.

## Required target state

### 1. `AdminProjectAccess` is the narrow project-access boundary

`src/grace_control/services/admin_project_access.py` should own only:

- configured project context listing/resolution through `CrossProjectTransport`;
- one selected-project read through transport;
- normalization to the existing Control Center read-result dict;
- project-keyed OpenAPI cache ownership/access.

It must not import/refer to focused Control Center services, mutation services, templates, DB models, Git readers, or filesystem readers.

Expected public capability equivalent to:

```python
contexts() -> tuple[ProjectContext, ...]
context(project_key: str) -> ProjectContext
read(project_key, path, *, params=None, operation="read") -> dict[str, Any]
openapi_cache -> MutableMapping[...]
```

Preserve unknown-project `KeyError` and existing normalized keys:

```text
ok
payload
error
error_class
http_status
headers
```

### 2. No dynamic cache injection onto Hub

Control Center must not create/mutate `hub._admin_openapi_cache` or an equivalent private cache field on `AdminCrossProjectService` after construction.

Cache ownership belongs to `AdminProjectAccess` or another narrow Control Center-owned collaborator.

### 3. Focused child services have explicit constructor dependencies

`AdminControlCenterProjectService`, `AdminControlCenterPacketService`, `AdminControlCenterExplorerService`, and `AdminControlCenterPageService` must not:

- accept `AdminControlCenterService` as constructor dependency;
- store/use `self._facade`;
- access `_facade._hub`, `_hub._registry`, `_hub._request`, `_hub._client_factory`;
- use facade private methods as an implicit service locator.

Inject only the concrete collaborators each service actually needs, such as `AdminProjectAccess`, shared project-shell/selector owner, `AdminCrossProjectService` public read facade, `AdminMutationService`, or focused sibling service where the graph remains acyclic.

### 4. Shared project shell/selector logic has a narrow owner

If current code has `AdminControlCenterProjectShell` or equivalent, it may own only reusable shell/selector/context-card composition needed to break Project ↔ Packet ↔ Explorer cycles.

It must not become a generic helper bag or service locator.

### 5. Composition is complete at construction time

No post-construction private dependency wiring such as:

```python
project._packet = packet
packet._explorer = explorer
child._service = sibling
```

between focused services.

All dependencies must be provided in constructors. Ordinary internal state initialization inside an object's own `__init__` is fine.

### 6. `AdminControlCenterService` remains thin

It should:

- validate/store top-level Hub input;
- construct `AdminProjectAccess` and focused collaborators in acyclic order;
- construct one `AdminMutationService(hub)` if required;
- delegate stable public methods to focused owners;
- retain only proven external compatibility delegates.

Child-only bridge methods such as `_read`, `_context`, `_explorer_shell`, `_project_card`, `_cards`, `_context_info`, `_selector_projects`, `_selector_current` should be absent if no external caller remains.

Do not move child business logic back into the facade.

### 7. Mutation internals remain frozen

`AdminMutationService` may continue to depend on temporary private compatibility seams of `AdminCrossProjectService` if current accepted architecture still requires them.

Do not rewrite mutation mixins/security/confirmation flows in this packet. This packet only ensures Control Center children no longer depend on reverse facade/private Hub state.

## Required architecture guard

A durable architecture test must prove directly or equivalently:

1. focused Control Center child classes do not store/use `self._facade`;
2. focused child constructors do not accept `AdminControlCenterService`;
3. child modules do not reach `_facade._hub`, `_hub._registry`, `_hub._request`, `_hub._client_factory`;
4. `AdminControlCenterService.__init__` does not inject `_admin_openapi_cache` onto Hub;
5. `AdminProjectAccess` does not depend on focused services/service-locator style collaborators;
6. no post-construction private collaborator assignment wires Project/Packet/Explorer/Page services together;
7. composition root constructs the explicit collaborators needed by the graph.

Preferred existing/new path:

`tests/grace_control/architecture/test_admin_control_center_dependency_inversion.py`

If an equivalent strong guard already exists and passes, do not duplicate it.

## Required verification

Run at minimum:

```bash
PYTHONPATH=src .venv/bin/pytest -q \
  tests/grace_control/architecture/test_admin_control_center_dependency_inversion.py

PYTHONPATH=src .venv/bin/pytest -q \
  tests/grace_control/api/test_admin_cross_project_observability.py \
  tests/grace_control/api/test_admin_hub_project_foundation.py \
  tests/grace_control/api/test_admin_control_center_stage07.py \
  tests/grace_control/api/test_admin_control_center_stage07_matrix.py
```

Also discover/run any current tests directly exercising:

```text
AdminControlCenterService
AdminControlCenterProjectService
AdminControlCenterPacketService
AdminControlCenterExplorerService
AdminControlCenterPageService
AdminProjectAccess
```

Then run:

```bash
make lint
make docs-check
make hygiene
python3 -m py_compile <changed-python-files-if-any>
git diff --check
```

For baseline-aware lint, report canonical `make lint` success separately from raw Ruff/GraceLint debt.

Run final structural scans:

```bash
rg -n 'self\._facade|_facade\._hub|_hub\._registry|_hub\._request|_hub\._client_factory' \
  src/grace_control/services/admin_control_center*.py \
  src/grace_control/services/admin_project_access.py || true

rg -n '_admin_openapi_cache' \
  src/grace_control/services/admin_control_center*.py \
  src/grace_control/services/admin_project_access.py || true
```

Explain any legitimate cache field owned locally by `AdminProjectAccess`; dynamic Hub injection is forbidden.

## Submission protocol

If corrections are required, commit and push them and use the full 40-character implementation SHA. If current `main` already satisfies the packet, use synced `HEAD` and state `verified no-op` explicitly.

Create only:

`docs/work/agent_exchange/outbox/TZ_GRACE_ARCHITECTURE_REFACTOR_V2_04_ADMIN_CONTROL_CENTER_DEPENDENCY_INVERSION_SUBMISSION.md`

It MUST begin exactly:

```text
WEB_ORCH_REPORT: SUBMISSION TZ_GRACE_ARCHITECTURE_REFACTOR_V2_04_ADMIN_CONTROL_CENTER_DEPENDENCY_INVERSION
WEB_ORCH_STATUS: DONE
WEB_ORCH_COMMIT: <full-40-character-implementation-sha>
WEB_ORCH_CHECKS: PASS
```

Then include:

- synced base SHA and initial status;
- implementation SHA or verified-no-op statement;
- final dependency graph/composition evidence;
- `AdminProjectAccess` ownership evidence;
- facade/private-state structural scan results;
- any retained compatibility seam and exact caller;
- exact targeted test counts/check results;
- changed paths, or `none` for verified no-op.

Do not create/start the next packet. Wait for Architect ACCEPT/REVIEW.

## Acceptance criteria

Architect ACCEPT requires all of:

1. Control Center child services have explicit one-way constructor dependencies.
2. No focused child stores/uses `self._facade` or reaches Hub private state.
3. `AdminProjectAccess` is the narrow project context/read/cache boundary and not a service locator.
4. No dynamic OpenAPI cache injection occurs on `AdminCrossProjectService`.
5. Project/Packet/Explorer/Page dependency graph is acyclic and complete at construction time.
6. No post-construction private collaborator mutation is used to wire focused services.
7. `AdminControlCenterService` remains a thin composition root/facade.
8. Public Control Center behavior/routes/DTOs/path-safety/mutation confirmation remain compatible.
9. No direct cross-project DB/filesystem/Git access is introduced.
10. Mutation internals and later waves are not refactored here.
11. Architecture/regression checks pass and are truthfully reported.
12. No API/DB/lifecycle/packet-state/merge semantic drift or lint allowlist expansion is introduced.
13. Submission follows the exact named-file protocol with a full SHA.
