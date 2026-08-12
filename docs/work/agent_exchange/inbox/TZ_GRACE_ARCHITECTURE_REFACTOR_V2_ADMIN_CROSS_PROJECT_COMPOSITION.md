# TZ_GRACE_ARCHITECTURE_REFACTOR_V2_ADMIN_CROSS_PROJECT_COMPOSITION — Packet 3: explicit cross-project composition

## Packet identity

- `TZ_NAME`: `TZ_GRACE_ARCHITECTURE_REFACTOR_V2_ADMIN_CROSS_PROJECT_COMPOSITION`
- Role: Coder
- Repository: `/opt/grace-orchestrator`
- Upstream: `origin/main`
- Parent programme: `docs/work/TZ_GRACE_ARCHITECTURE_REFACTOR_V2.md`
- Normative implementation details: `docs/work/WORKER_GRACE_ARCHITECTURE_REFACTOR_V2.md`, Wave 2 only.
- Previous named packet `TZ_GRACE_ARCHITECTURE_REFACTOR_V2_CONTROL_CLI_REMOVAL` is ACCEPTED.
- Implement **only Wave 2 — Admin cross-project composition** in this packet.
- Do **not** start Wave 2B Control Center dependency inversion, Wave 3 aggregation cycle removal, Wave 4 lifecycle extraction, typed DTO work, dead-code cleanup, or CI consolidation.

This packet is self-contained. Do not invent or start the next packet. Only Architect ACCEPT authorizes the next named TZ.

## Mandatory sync before any work

Before inspecting implementation files or changing anything:

```bash
cd /opt/grace-orchestrator
git switch main
git fetch origin main
git merge --ff-only origin/main
git status --short
git rev-parse HEAD
```

Record the synced base SHA and initial `git status --short` in the submission.

Preserve unrelated pre-existing untracked files. Do not run `git reset --hard` or `git clean`. Do not create web-orch `state.json`, lock files, orchestration metadata, or any other repository-side protocol state.

## Objective

Replace the hidden-inheritance contract of cross-project Admin reads with explicit composition while preserving the existing public facade and all external DTO/API behavior.

Current shape on `main`:

```text
AdminCrossProjectService
    inherits AdminCrossProjectOverviewMixin
    inherits AdminCrossProjectQueryMixin
    owns hidden members:
        _registry
        _client_factory
        _max_concurrency
        _connect_timeout
        _read_timeout
        _select_contexts(...)
        _fanout(...)
        _request(...)

Overview/Query mixins call those hidden members as if they were local API.
```

Target shape:

```text
AdminCrossProjectService                # stable thin facade
    -> CrossProjectTransport            # selection/fan-out/request/error isolation
    -> AdminCrossProjectOverviewService # overview/diagnostics projection
    -> AdminCrossProjectQueryService    # events/logs/search projection
```

No mixins. No child service may rely on undeclared members inherited from or injected through facade state.

## Product/architecture invariants

1. Preserve the public import/class name `AdminCrossProjectService`.
2. Preserve its current constructor compatibility:
   - `registry`
   - optional `client_factory`
   - `max_concurrency`
   - `connect_timeout`
   - `read_timeout`
3. Preserve public method names, argument signatures and JSON shapes for:
   - `get_projects_overview`
   - `get_attention`
   - `get_diagnostics`
   - `query_events`
   - `query_logs`
   - `search`
4. Preserve project selection semantics, including registry order, disabled-project behavior, explicit `all`, and unknown-project `KeyError` behavior.
5. Preserve bounded concurrency and deterministic output ordering.
6. Preserve per-project failure isolation, identity-mismatch normalization and capability-unavailable handling.
7. Admin Hub must continue to access projects through project-local API/runtime boundaries. Do not add direct cross-project DB/filesystem/Git access.
8. Do not change API routes, response fields, templates, packet semantics, database schema, project registry semantics, or mutation/security behavior.
9. Do not create a generic service locator, `BaseService`, dependency bag, manager factory, or new global registry.
10. No new GRC005/GRC012 allowlist entries. No touched source file may exceed 1000 physical lines; target <=800 where practical.

## Current files to inspect before editing

At minimum inspect:

```text
src/grace_control/services/admin_cross_project_service.py
src/grace_control/services/admin_cross_project_overview_mixin.py
src/grace_control/services/admin_cross_project_query_mixin.py
src/grace_control/services/admin_cross_project_helpers.py
src/grace_control/services/project_client.py
src/grace_control/config/project_registry.py
src/grace_control/api/routers/admin_hub.py
src/grace_control/services/admin_control_center.py

tests/grace_control/api/test_admin_cross_project_observability.py
tests/grace_control/api/test_admin_hub_project_foundation.py
tests/grace_control/api/test_admin_control_center_stage07.py
tests/grace_control/api/test_admin_control_center_stage07_matrix.py
```

The last Control Center files are compatibility consumers/regressions only. Do not refactor their dependency structure in this packet.

## Required implementation

### 1. Create `CrossProjectTransport`

Create:

`src/grace_control/services/admin_cross_project_transport.py`

Class:

`CrossProjectTransport`

It owns exactly the transport/selection boundary currently hidden inside `AdminCrossProjectService`:

- immutable `ProjectRegistry` reference;
- project context listing/selection;
- `client_factory`;
- `max_concurrency`;
- connect/read timeout policy used to construct `ProjectClient`;
- bounded fan-out;
- one-project request dispatch;
- response normalization;
- health identity-mismatch validation;
- capability-unavailable normalization for existing operations;
- per-project transport/client failure isolation and existing structured log behavior.

Required methods equivalent to:

```python
class CrossProjectTransport:
    def list_contexts(self) -> tuple[ProjectContext, ...]: ...
    def select_contexts(
        self,
        project: Sequence[str] | str | None,
    ) -> tuple[ProjectContext, ...]: ...

    async def fanout(
        self,
        contexts: Sequence[ProjectContext],
        operation_fn: Callable[[ProjectContext], Awaitable[Any]],
        *,
        operation: str,
    ) -> list[Any]: ...

    async def request(
        self,
        context: ProjectContext,
        path: str,
        params: Mapping[str, Any] | None = None,
        *,
        operation: str = "read",
    ) -> RemoteResult: ...
```

Names may vary only slightly when required by current contracts, but responsibilities must not drift.

The current `_RemoteResult` may stay in `admin_cross_project_helpers.py` or move to a narrow contracts/transport module. Do not duplicate it and do not create two competing normalized result types.

### 2. Replace overview mixin with explicit service

Remove the inheritance-based production class from:

`src/grace_control/services/admin_cross_project_overview_mixin.py`

Preferred final file:

`src/grace_control/services/admin_cross_project_overview_service.py`

Class:

`AdminCrossProjectOverviewService`

Constructor:

```python
def __init__(self, transport: CrossProjectTransport) -> None:
    self._transport = transport
```

Move the current overview/diagnostics projection behavior into this service.

Rules:

- use `self._transport.list_contexts()` / `select_contexts()` / `fanout()` / `request()`;
- do not access `_registry`, `_request`, `_fanout`, `_select_contexts` as undeclared local members;
- preserve disabled project cards, coverage math, aggregate semantics, attention ordering, malformed-response handling and timestamps/DTO keys;
- projection helpers that are pure can remain in `admin_cross_project_helpers.py`.

Delete the old mixin file once no active import depends on it. Do not retain a compatibility `Mixin` alias.

### 3. Replace query mixin with explicit service

Replace:

`src/grace_control/services/admin_cross_project_query_mixin.py`

with preferred final file:

`src/grace_control/services/admin_cross_project_query_service.py`

Class:

`AdminCrossProjectQueryService`

Constructor:

```python
def __init__(self, transport: CrossProjectTransport) -> None:
    self._transport = transport
```

Move current `query_events`, `query_logs`, `search` behavior without changing public DTOs or bounds.

Preserve exactly the existing important semantics:

- deterministic project order;
- bounded event fetches/cursors;
- bounded log tail behavior;
- regex validation behavior;
- packet/run/stage log route selection;
- capability-unavailable normalization;
- project attribution on merged rows;
- search result ordering/coverage/error isolation;
- invalid cursor/filter mismatch errors.

Delete the old query mixin when no imports remain. Do not leave a shim class ending in `Mixin`.

### 4. Rewrite `AdminCrossProjectService` as thin facade

`src/grace_control/services/admin_cross_project_service.py` must no longer inherit the overview/query behavior.

Target ownership:

```python
class AdminCrossProjectService:
    def __init__(...):
        self._transport = CrossProjectTransport(...)
        self._overview = AdminCrossProjectOverviewService(self._transport)
        self._query = AdminCrossProjectQueryService(self._transport)
```

Constructor injection of already-built collaborators is allowed if useful for tests, but do not break the current constructor used by application code.

Public methods delegate only:

- `get_projects_overview` -> overview service
- `get_diagnostics` -> overview service
- `get_attention` -> overview result or overview service
- `query_events` -> query service
- `query_logs` -> query service
- `search` -> query service

A read-only property is allowed if the next wave needs it:

```python
@property
def transport(self) -> CrossProjectTransport:
    return self._transport
```

Do not expose mutable `_registry` state as a new public API.

The facade must not re-grow copies of selection/fanout/request implementations merely to preserve tests. Update tests to inject/observe the explicit transport boundary instead.

### 5. Keep Control Center Wave 2B frozen

Do not alter the architecture of:

```text
src/grace_control/services/admin_control_center.py
src/grace_control/services/admin_control_center_project_service.py
src/grace_control/services/admin_control_center_packet_service.py
src/grace_control/services/admin_control_center_explorer_service.py
src/grace_control/services/admin_control_center_page_service.py
```

If a minimal import/property compatibility adjustment is unavoidable because those files reach a now-removed private member, document it explicitly in the submission. Do not remove their `self._facade` dependencies yet; that is the next named packet.

## Required architecture guard

Add a focused architecture regression test, preferred path:

`tests/grace_control/architecture/test_admin_cross_project_composition.py`

It must fail if any of these regressions return:

1. `AdminCrossProjectService` inherits a class whose name ends with `Mixin`.
2. Active `admin_cross_project_*` production modules define `AdminCrossProject*Mixin` classes.
3. `AdminCrossProjectOverviewService` or `AdminCrossProjectQueryService` accesses hidden local members `_registry`, `_request`, `_fanout`, `_select_contexts` instead of going through `self._transport`.
4. Old files `admin_cross_project_overview_mixin.py` / `admin_cross_project_query_mixin.py` remain after successful migration.
5. `CrossProjectTransport` is missing the registry selection + bounded fan-out + request responsibilities.

Prefer AST/introspection assertions over fragile whole-file string matching where practical.

## Required regression proof

At minimum run:

```bash
PYTHONPATH=src .venv/bin/pytest -q tests/grace_control/api/test_admin_cross_project_observability.py
PYTHONPATH=src .venv/bin/pytest -q tests/grace_control/api/test_admin_hub_project_foundation.py
PYTHONPATH=src .venv/bin/pytest -q tests/grace_control/api/test_admin_control_center_stage07.py tests/grace_control/api/test_admin_control_center_stage07_matrix.py
PYTHONPATH=src .venv/bin/pytest -q tests/grace_control/architecture/test_admin_cross_project_composition.py
```

Also run relevant existing Admin/API regressions affected by imports/wiring.

Run:

```bash
python3 scripts/grace_lint.py <changed-python-files-and-tests>
ruff check <changed-python-files-and-tests>
python3 -m py_compile <changed-python-files>
git diff --check
```

If repository-wide baseline lint remains non-zero, report before/after evidence and prove no new violations in touched files. Do not broaden this packet into unrelated lint cleanup.

## Explicit structural verification

Before submission run searches equivalent to:

```bash
rg -n 'class AdminCrossProject.*Mixin|AdminCrossProjectOverviewMixin|AdminCrossProjectQueryMixin' src tests || true
rg -n 'self\._registry|self\._request|self\._fanout|self\._select_contexts' \
  src/grace_control/services/admin_cross_project_* || true
```

Interpretation:

- zero production mixin classes/imports are expected;
- `CrossProjectTransport` may of course own its explicit `_registry` internally;
- overview/query services must not own hidden `_registry/_request/_fanout/_select_contexts` members;
- historical `docs/work/` references are not part of this zero-hit rule.

## Acceptance criteria

PASS only if all are true:

1. `AdminCrossProjectService` uses composition, not mixin inheritance.
2. `CrossProjectTransport` is the single owner of selection/fan-out/request transport behavior.
3. Overview service depends only on explicit `CrossProjectTransport` plus pure helpers.
4. Query service depends only on explicit `CrossProjectTransport` plus pure helpers.
5. Old overview/query mixin production files are deleted with no compatibility aliases.
6. Existing `AdminCrossProjectService` public constructor and methods remain compatible.
7. Existing overview/diagnostics/events/logs/search DTO shapes and error semantics remain compatible.
8. Bounded concurrency and deterministic project ordering remain intact.
9. Offline/partial/disabled/identity-mismatch/capability-unavailable behavior remains isolated and attributed.
10. No direct cross-project DB/filesystem/Git access is introduced.
11. Control Center Wave 2B is not started.
12. Architecture guard passes.
13. Relevant Admin/API regressions pass or only exact documented pre-existing baseline failures remain.
14. No new size/lint allowlist exception is introduced.

## Required submission

After implementation, commit and push to `origin/main`.

Create only:

`docs/work/agent_exchange/outbox/TZ_GRACE_ARCHITECTURE_REFACTOR_V2_ADMIN_CROSS_PROJECT_COMPOSITION_SUBMISSION.md`

The submission must begin with these exact lines:

```text
WEB_ORCH_REPORT: SUBMISSION TZ_GRACE_ARCHITECTURE_REFACTOR_V2_ADMIN_CROSS_PROJECT_COMPOSITION
WEB_ORCH_STATUS: DONE
WEB_ORCH_COMMIT: <full-commit-sha>
WEB_ORCH_CHECKS: PASS
```

Then report concisely:

- synced base SHA and initial status;
- implementation commit SHA;
- files created/deleted/rewired;
- proof that public facade signatures/DTOs stayed compatible;
- architecture-guard result;
- exact targeted test counts;
- lint/compile/diff-check results;
- any baseline failures with before/after proof;
- any unavoidable Control Center compatibility touch (expected: none/minimal).

Do not create a resubmission unless Architect creates `docs/work/agent_exchange/inbox/TZ_GRACE_ARCHITECTURE_REFACTOR_V2_ADMIN_CROSS_PROJECT_COMPOSITION_REVIEW.md`.
