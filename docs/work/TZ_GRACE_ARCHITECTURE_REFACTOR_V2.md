# TZ — GRACE Architecture Refactor V2

Status: READY FOR CODER
Type: architecture refactor / legacy removal / maintainability hardening
Repository: `basilivanov/grace-orchestrator`
Primary scope: `src/grace_control/`, `tests/`, active operator/developer docs, CI/hygiene
Date: 2026-08-12

## 1. Goal

Refactor GRACE after the Local Adopt size split so that the system is not only under file/function limits, but also has clear ownership, explicit dependencies, one canonical control surface, less legacy, fewer hidden compatibility seams, and lower coupling between admin/runtime/control components.

This programme is NOT another arbitrary file-splitting exercise. The previous structural refactor reduced oversized modules. This programme must reduce architectural coupling and remove obsolete surfaces.

Primary outcomes:

1. Remove OpenCode-specific runtime code as unused legacy.
2. Remove the user/control CLI surface. GRACE Control Plane is API-first; HTTP/OpenAPI is the only operator/control interface after process bootstrap.
3. Preserve the currently used mini-swe execution path. Do NOT confuse the removed control CLI with the internal generic CLI/subprocess backend used by mini-swe.
4. Remove reverse dependencies such as child service -> facade -> private field.
5. Remove mixin decomposition that relies on hidden `self` members.
6. Remove post-construction private collaborator mutation used to solve cycles.
7. Move lifecycle/router business logic into explicit services/ports so routers are thin bindings.
8. Introduce typed read models at the highest-risk admin boundaries instead of passing unconstrained nested `dict[str, Any]` everywhere.
9. Remove high-confidence dead code, stale migration/demo helpers, and tracked runtime artifacts.
10. Make `make ci` the single canonical CI gate and eliminate duplicated CI logic.

## 2. Explicit product/architecture decisions

These decisions are final for this TZ. The coder must not preserve compatibility for removed surfaces unless explicitly required below.

### 2.1 Control Plane is API-only

The canonical runtime/operator surface is FastAPI/OpenAPI.

Remove the control CLI implemented by:

- `src/grace_control/cli.py`
- references to `python -m grace_control.cli ...`
- references to `grace_ctl ...`
- CLI-only tests and active docs
- CLI-only dependency `typer` if no remaining live import requires it

Do NOT create a new replacement CLI, thin wrapper, shell alias, or second control surface.

Important bootstrap exception:

- The supervisor/process must still be startable by deployment/systemd/dev bootstrap.
- A bootstrap script may invoke `grace_control.supervisor` directly because an HTTP API cannot start itself before the process exists.
- After startup, status/restart/reload/control operations must go through the HTTP API, not a CLI.

### 2.2 OpenCode runtime is legacy and must be removed

OpenCode-specific runtime is not used and must not be retained behind a feature flag.

Delete OpenCode-specific runtime implementation and references, including at minimum the current files:

- `src/grace_control/runtime/opencode_runtime_adapter.py`
- `src/grace_control/runtime/opencode_command_builder.py`
- `src/grace_control/runtime/opencode_attach_command_builder.py`
- `src/grace_control/runtime/opencode_event_collector.py`
- `src/grace_control/runtime/opencode_failure_classifier.py`
- `src/grace_control/runtime/opencode_server_manager.py`
- `src/grace_control/runtime/opencode_server_state.py`

Also remove OpenCode-specific:

- settings fields and environment variables;
- profile fields/commands/extras used only for OpenCode;
- OpenCode profiles in `agent_profiles.yaml`;
- feature flags such as `agent_runtime_use_opencode_adapter`;
- OpenCode-only fallback logic in generic execution services;
- OpenCode-only session parsing/validation;
- OpenCode-only tests;
- OpenCode instructions from active docs/runbooks.

Historical evidence documents under `docs/work/` may remain if they are clearly historical and are not linked as current source of truth. Active docs must not recommend OpenCode.

### 2.3 Mini-swe remains in scope and must continue to work

Do NOT delete these merely because they spawn a CLI/subprocess:

- `src/grace_control/runtime/mini_swe_runner.py`
- `src/grace_control/agent/universal_cli_backend.py`
- `src/grace_control/services/agent_run_service.py`
- generic process/env/render/artifact services used by mini-swe

This internal execution mechanism is not the removed user/control CLI.

If OpenCode compatibility logic exists inside generic mini-swe/CLI execution services, remove only the OpenCode-specific branches while preserving generic behaviour.

### 2.4 No new generic framework layer

Do not introduce vague abstractions such as:

- `BaseService`
- `BaseRepository`
- `ManagerFactory`
- global service locator
- dependency registry dictionary

New abstractions must represent a real domain boundary and have narrow names/contracts.

## 3. Architectural problems to fix

### 3.1 Admin Control Center is still a distributed monolith

The structural split created focused files, but child services still reach back through the facade and its private state.

Bad dependency shapes to eliminate:

```text
child service -> self._facade -> self._facade._hub -> self._facade._hub._registry
child service -> self._facade._read(...)
child service -> self._facade._packet_page(...)
```

The facade may delegate outward. Focused services must not depend back on the facade that constructs them.

### 3.2 Cross-project mixins hide required interfaces

`AdminCrossProjectService` currently composes behaviour through mixins that assume hidden members such as `_registry`, `_request`, `_fanout`, `_select_contexts`.

Replace hidden inheritance contracts with explicit composition.

### 3.3 Admin aggregation wiring mutates private collaborators after construction

Patterns like:

```text
self._packet._artifact_service = ...
self._packet._session_service = ...
self._pipeline._artifact_service = ...
```

must disappear.

All required collaborators must be supplied through constructors or narrow explicit interfaces.

### 3.4 Lifecycle router owns business/infrastructure logic

`api/routers/lifecycle.py` currently performs work that belongs below the HTTP layer, including environment resolution, filesystem state reads, Git subprocess/version logic, DB queries and health DTO composition.

Routers must become thin request/response bindings.

### 3.5 Too many untyped internal admin contracts

Large nested dictionaries are passed through read services, cross-project aggregation, control-center composition and templates.

Introduce typed read models where they materially protect boundaries. Do not rewrite the entire project to Pydantic in one wave.

### 3.6 Repository still contains obsolete/demo/runtime artifacts

High-confidence candidates include hello/demo modules, old Prefect demos/integration scripts, stale migration tooling and tracked runtime/test state.

Every deletion must be evidence-based, but tests must not be treated as proof that a useless production module is useful when the test exists only for that module.

## 4. Target architecture

### 4.1 Control plane

Target:

```text
HTTP/OpenAPI
    -> FastAPI router
        -> application/service
            -> explicit domain/infrastructure port
                -> DB / supervisor socket / filesystem / git / remote project API
```

Rules:

- routers do not call `subprocess`;
- routers do not read `os.environ` directly;
- routers do not open DB sessions for aggregation/business decisions;
- routers do not read supervisor files directly;
- routers do not construct complex DTOs from infrastructure data;
- scripts are bootstrap/dev/CI wrappers only;
- no runtime business command is exposed as a CLI.

### 4.2 Admin Control Center

Target:

```text
AdminControlCenterService                 # thin compatibility/application facade
    -> AdminControlCenterProjectService
    -> AdminControlCenterPacketService
    -> AdminControlCenterExplorerService
    -> AdminControlCenterPageService

Focused services depend on explicit collaborators, not on the facade.
```

Introduce one narrow access boundary for project-scoped reads/control required by these services. Suggested name:

`AdminProjectAccess`

It may own/receive:

- immutable project registry access;
- project context lookup;
- project-local read request dispatch;
- authorized mutation dispatch if needed;
- project-keyed OpenAPI cache.

It must NOT be a general service locator.

### 4.3 Cross-project admin

Target composition:

```text
AdminCrossProjectService                 # stable facade
    -> CrossProjectTransport             # select/fan-out/request/error isolation
    -> AdminCrossProjectOverviewService  # overview/diagnostics projections
    -> AdminCrossProjectQueryService     # events/logs/search projections
```

No mixins.

`CrossProjectTransport` must explicitly own:

- registry;
- project selection;
- bounded concurrency;
- client factory;
- timeout policy;
- response normalization;
- per-project error isolation.

Overview/query services receive the transport object through their constructor.

### 4.4 Admin read aggregation

Create explicit small shared collaborators instead of circular back-wiring.

At minimum isolate:

- packet/run resolution;
- artifact/evidence reads;
- log/session reads;
- pipeline projection.

A suggested dependency direction:

```text
PacketRunResolver                  # lowest-level shared read helper
ArtifactReadService -> PacketRunResolver
LogsReadService    -> PacketRunResolver
PipelineReadService -> narrow ArtifactEvidenceReader protocol
PacketReadService   -> PipelineReadService + narrow readers
AdminAggregationService -> focused services
```

No focused service may receive `AdminAggregationService` itself.

No private dependency is assigned after object construction.

### 4.5 Lifecycle/supervisor

Target:

```text
lifecycle router
    -> LifecycleService
        -> SupervisorControlPort
        -> RuntimeStateStore
        -> WorkerReadService
        -> VersionProvider
```

Suggested responsibilities:

- `SupervisorControlPort`: status/restart/reload over existing supervisor control socket/client.
- `RuntimeStateStore`: read/parse supervisor state file only.
- `WorkerReadService`: DB worker snapshot only.
- `VersionProvider`: current source/version lookup through existing Git abstraction or one isolated implementation.
- `LifecycleService`: compose status, versions and health DTOs; call authorized supervisor operations.

The router only validates HTTP input/security and delegates.

### 4.6 Runtime

Target live runtime set after this programme:

- mini-swe runtime;
- generic execution backend abstractions actually used by mini-swe;
- mock/test backend;
- API backend only if genuinely used elsewhere;
- NO OpenCode-specific runtime stack.

Do not create a new OpenCode compatibility adapter.

## 5. Refactor invariants

These must remain true through all waves unless a wave explicitly changes the stated legacy surface.

1. Packet lifecycle/state transition semantics are unchanged.
2. Acceptance/reviewer/verifier/recovery semantics are unchanged.
3. Merge semantics are unchanged.
4. DB schema is unchanged unless a separate approved migration is proven necessary; this programme is expected to require no DB migration.
5. Current packet/feature/wave IDs and persisted state values remain stable.
6. Current API routes and response contracts remain stable except routes explicitly proven legacy and separately listed in the coder submission. Removing the control CLI is not permission to break HTTP APIs.
7. OpenAPI remains the canonical public contract.
8. Mini-swe remains operational.
9. No OpenCode feature flag, fallback or compatibility alias remains in active source/config/tests.
10. No control CLI remains.
11. No new file may exceed Local Adopt limits: <=1000 physical lines.
12. No function/async function may exceed the existing GRC012 4000 estimated-token limit.
13. Touched modules should target <=800 lines where practical.
14. No new `GRC005`/`GRC012` allowlist exception is allowed.
15. Do not hide coupling by moving code to `_helpers.py` while retaining the same reverse/private dependencies.

## 6. Work programme and order

### Wave 0 — Baseline and dependency inventory

Before deleting or moving code:

- capture base SHA;
- capture `git status --short`;
- run targeted/current gates and record pre-existing failures;
- `rg` every OpenCode/control-CLI symbol/path;
- map imports of admin facade/mixins/private members;
- map references to dead-code candidates;
- identify tracked runtime artifacts with `git ls-files`;
- create a short before-state section in the final report.

No refactor should start from guessed references.

### Wave 1 — Remove OpenCode legacy and control CLI

This wave is intentionally early so later architecture does not preserve obsolete seams.

Required results:

- delete OpenCode runtime stack;
- remove OpenCode profiles/config/settings/fallbacks/tests;
- remove `src/grace_control/cli.py`;
- migrate supervisor bootstrap away from `python -m grace_control.cli start`;
- migrate active docs from `grace_ctl`/CLI operations to HTTP API examples;
- remove `typer` if unused;
- add guard tests that prevent OpenCode/control CLI from returning.

Mini-swe must still pass its focused runtime tests after this wave.

### Wave 2 — Admin dependency inversion

Required results:

- focused Control Center services do not store or call `self._facade`;
- no child service reaches `_hub._registry` through a parent facade;
- introduce explicit project access collaborator(s);
- replace cross-project mixins with composition;
- facade remains thin and stable where public import compatibility matters.

### Wave 3 — Admin aggregation cycle removal

Required results:

- zero post-construction writes to private collaborator fields;
- explicit constructor injection;
- shared low-level packet/run resolver extracted if needed;
- narrow protocols/interfaces used where two read services need only one capability;
- business/read projection logic has exactly one owner.

### Wave 4 — Lifecycle/router cleanup and API-only control

Required results:

- lifecycle router contains no direct `os.environ` read;
- lifecycle router contains no `subprocess`;
- lifecycle router contains no direct SQLAlchemy aggregation/query logic;
- lifecycle router contains no supervisor state-file parsing;
- lifecycle service/ports own these responsibilities;
- API continues to provide canonical status/restart/reload/control operations.

### Wave 5 — Typed admin boundary models

Introduce typed DTOs only where they reduce cross-module ambiguity.

Priority models:

- project health/status snapshot;
- cross-project coverage;
- attention item;
- packet/run summary used across multiple read services;
- pipeline stage view;
- lifecycle/worker snapshot if currently repeated.

Rules:

- JSON output shape must stay compatible;
- if Pydantic is used, serialize with explicit stable aliases/field names;
- do not convert every helper dictionary in one sweep;
- do not move ORM entities directly into API/template contracts.

### Wave 6 — Dead code and repository hygiene

Audit and remove high-confidence dead code.

Initial candidates requiring proof:

- `src/hello.py`
- `src/hello_grace.py`
- `tests/test_hello_grace.py`
- `src/grace_control/core/hello.py`
- `src/grace_control/mod.py`
- `tests/grace_control/core/test_mod.py`
- `demo_resources.py`
- `scripts/test_api_integration.py`
- `src/gold-test/`
- tracked DB/runtime paths such as `%2Ftmp%2F*`, `.goldw/`, `.lw3/`, `.grace-live-wt/`
- stale package migration scripts/docs if they have no supported operator use

For each candidate, prove references and classify:

- `DELETE_NOW`
- `KEEP_USED`
- `KEEP_HISTORICAL_DOC`
- `MANUAL_REVIEW`

Do not delete migrations merely because their names contain `legacy`.

Extend repo hygiene so accidentally tracked runtime state fails CI.

### Wave 7 — CI single source of truth and final compatibility retirement

Required results:

- `.github/workflows/ci.yml` delegates to canonical Make targets instead of reimplementing checks inline where practical;
- `make ci` is the authoritative local/CI gate;
- `make test` does not silently exclude supported tests;
- obsolete tests belonging only to deleted legacy surfaces are removed;
- active docs match the new architecture;
- generated OpenAPI/docs are checked for unexpected drift;
- final repository-wide `rg` shows no active OpenCode/control CLI references.

## 7. Legacy removal rules

### OpenCode

Do not retain:

- deprecated wrapper modules;
- re-export aliases;
- disabled profile entries;
- `if settings.agent_runtime_use_opencode_adapter` branches;
- OpenCode env injection in generic backend;
- OpenCode session ID parser/validator;
- OpenCode server URL/password fields;
- tests asserting OpenCode compatibility.

A historical document may contain the word `opencode`; active source/config/runbooks must not.

### Control CLI

Do not retain:

- `grace_ctl` command examples;
- `python -m grace_control.cli` examples;
- a hidden alias script that forwards to HTTP;
- Typer app only to keep old commands alive.

Replace active operational instructions with API calls or deployment bootstrap instructions.

### Compatibility facades

Compatibility is allowed only for live Python imports/API contracts that still have real consumers.

Do not keep a compatibility facade just because a historical test imports it. Migrate/delete obsolete tests when the underlying surface is intentionally removed by this TZ.

## 8. Tests and guardrails to add

At minimum add focused regression/architecture tests equivalent to:

- `test_no_opencode_runtime_modules_remain`
- `test_no_opencode_active_profiles_or_settings`
- `test_packet_executor_has_no_opencode_runtime_flag_branch`
- `test_no_control_cli_module_or_active_references`
- `test_no_grace_ctl_or_grace_control_cli_in_active_docs_and_scripts`
- `test_admin_control_center_children_do_not_depend_on_facade_private_state`
- `test_admin_cross_project_uses_composition_not_hidden_mixins`
- `test_admin_read_services_have_no_post_init_private_dependency_wiring`
- `test_lifecycle_router_has_no_subprocess_env_or_direct_db_business_logic`
- `test_runtime_artifacts_are_not_tracked`
- `test_ci_uses_canonical_make_gate`

Tests may use AST/import inspection where that provides a stable architectural guard. Avoid brittle full-file string tests unless checking a banned legacy identifier.

## 9. Verification policy

After each wave run directly affected tests plus:

```bash
python3 scripts/grace_lint.py src/grace_control tests scripts
python -m ruff check src/grace_control tests scripts
```

Run the relevant mini-swe execution tests after Wave 1.

Run admin/control tests after Waves 2-5.

Final:

```bash
make ci
```

Also run explicit repository searches:

```bash
rg -n "grace_control\.cli|grace_ctl|python -m grace_control\.cli" src tests scripts docs README.md AGENTS.md
rg -n "opencode|OpenCode|OPENCODE|agent_runtime_use_opencode_adapter" src tests scripts docs/grace README.md AGENTS.md
rg -n "_facade\._hub|self\._facade\._|class .*Mixin" src/grace_control/services/admin_*
rg -n "\._artifact_service\s*=|\._session_service\s*=" src/grace_control/services
```

Interpretation:

- historical `docs/work/` references to OpenCode/old CLI are allowed only when clearly historical;
- active source/config/tests/scripts/runbooks must have zero OpenCode/control-CLI references after completion, except a deliberate negative guard test that checks banned names.

## 10. Coder constraints

The coder is not allowed to:

- redesign packet semantics;
- change business states/reason codes as cleanup;
- invent new runtime providers;
- remove mini-swe;
- replace the admin UI with a new framework;
- perform a formatting sweep;
- rename public API fields for consistency;
- add broad exception swallowing;
- solve import cycles with global registries/service locators;
- keep deleted legacy via hidden aliases;
- weaken tests to make refactor regressions pass;
- add lint allowlist entries for size/architecture regressions.

If a required deletion reveals a live dependency, migrate that dependency in the same wave rather than restoring the legacy module by default.

## 11. Acceptance criteria

PASS only if all are true:

1. OpenCode-specific runtime source is physically removed.
2. No OpenCode active profile, setting, feature flag, env injection or runtime fallback remains.
3. Mini-swe execution path remains operational.
4. `src/grace_control/cli.py` is physically removed.
5. Active docs/scripts no longer instruct operators to use `grace_ctl` or `python -m grace_control.cli`.
6. Supervisor still has an explicit deployment/dev bootstrap path that does not require the removed CLI.
7. HTTP/OpenAPI is the only post-bootstrap operator/control surface.
8. Admin Control Center focused services have no reverse dependency on the facade.
9. Cross-project admin uses composition, not hidden-member mixins.
10. Admin aggregation has no post-construction private collaborator wiring.
11. Lifecycle router is thin and contains no direct subprocess/env/DB aggregation/state-file business logic.
12. New typed boundary models preserve JSON/API/template compatibility.
13. High-confidence dead code/runtime artifacts are removed and repo hygiene prevents recurrence.
14. CI has one canonical local/remote gate path based on `make ci`.
15. No touched source file exceeds 1000 physical lines.
16. No touched function exceeds the GRC012 4000-token estimate.
17. No new GRC005/GRC012 allowlist exception exists.
18. Supported tests are not weakened or silently excluded.
19. `make ci` passes, or any pre-existing failure is documented with exact before/after proof and no new failure is introduced.
20. Final report contains ownership mapping, deleted legacy inventory, compatibility decisions and exact commands/results.

## 12. Required final report

Create:

`docs/work/REPORT_GRACE_ARCHITECTURE_REFACTOR_V2.md`

It must contain:

- base SHA and final SHA;
- each wave status;
- deleted files;
- migrated references;
- old responsibility -> new owner mapping;
- active compatibility facades retained and proof they are still needed;
- dead-code audit table with decision/confidence/evidence;
- before/after module line counts for major touched files;
- final architecture diagram in text;
- API/OpenAPI drift result;
- exact tests/gates run and results;
- final `rg` legacy scans;
- known debt intentionally left out of scope.

## 13. Companion coder document

The step-by-step implementation instructions are in:

`docs/work/WORKER_GRACE_ARCHITECTURE_REFACTOR_V2.md`

The worker document is normative for execution details. This master TZ is normative for architecture, removals, invariants and acceptance.