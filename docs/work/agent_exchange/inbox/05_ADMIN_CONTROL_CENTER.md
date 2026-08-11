# TZ 05_ADMIN_CONTROL_CENTER — Grace Local Adopt admin control-center service refactor

Status: READY FOR CODER
Source programme: `TZ_GRACE_LOCAL_ADOPT_REFACTOR_MASTER.md`
Source block: `TZ_GRACE_LOCAL_ADOPT_REFACTOR_05_ADMIN_CONTROL_PLANE.md` Part B
Dependency: `05_ADMIN_AGGREGATION` — ACCEPTED by Architect

## Coder protocol

You are the Coder for this named TZ. Read and execute **only this file**. Do not open or start another inbox task/TZ unless the Architect explicitly names it after ACCEPT.

Before editing anything:

1. Work in `/opt/grace-orchestrator`.
2. Fast-forward sync with GitHub. The checkout must be clean and updated from `origin/main`; use fast-forward-only sync and do not create a merge commit.
3. If the checkout cannot fast-forward cleanly, stop and report the blocker; do not overwrite local work.

After implementation:

1. Run the required verification below.
2. Commit the implementation.
3. Push the commit to GitHub.
4. Create **only** `docs/work/agent_exchange/outbox/05_ADMIN_CONTROL_CENTER_SUBMISSION.md` for the report.
5. Do not create the next task, review file, `state.json`, lock files, orchestration metadata, or any other coordination file.

The submission must contain these exact lines with the real implementation commit SHA:

```text
WEB_ORCH_REPORT: SUBMISSION 05_ADMIN_CONTROL_CENTER
WEB_ORCH_STATUS: DONE
WEB_ORCH_COMMIT: <commit-sha>
WEB_ORCH_CHECKS: PASS
```

If the Architect later returns REVIEW, read only `docs/work/agent_exchange/inbox/05_ADMIN_CONTROL_CENTER_REVIEW.md`, fix that review, and report only to `docs/work/agent_exchange/outbox/05_ADMIN_CONTROL_CENTER_RESUBMISSION.md`.

## Goal

Refactor the hard-limit service `src/grace_control/services/admin_control_center.py` into a bounded `AdminControlCenterService` compatibility facade backed by coherent control-center owners, **without changing any public admin route, DTO, security, project-isolation, mutation or explorer behaviour**.

This packet implements **Part B only** of source block 05. Do not start block 06 near-limit work.

Required structural result:

- `src/grace_control/services/admin_control_center.py` must be `<= 1000` physical lines with practical headroom; source target is preferably `<= 600–800`, and substantially smaller is appropriate if it becomes a thin coordinator;
- every touched/new function or async function must remain `<= 4000` Grace-estimated tokens (`len(source) // 4`), with large orchestration functions normally `<= 2500–3000`;
- the current `_packet_page(...)` responsibility is itself a decomposition target: do not simply move it intact into another near-limit function/module;
- every new Python module must be `<= 1000` physical lines, preferably `<= 800`;
- do not reduce line count by compression, giant expressions, dynamic service-locator tricks, or obscured identifiers.

## Owned write scope

Primary source:

- `src/grace_control/services/admin_control_center.py`

Expected new focused service modules under `src/grace_control/services/` where current responsibilities justify them. Coherent candidates include:

- project/dashboard/read-shell composition;
- packet drill-down/tab orchestration;
- explorer orchestration for Files/Git/API pages;
- system/maintenance/events/logs/search page composition;
- a bounded OpenAPI discovery/cache owner if it is a real independent responsibility.

Directly affected admin service/API tests may be changed or extended only as allowed below.

Optional only if moved code produces a genuine textual non-size GraceLint false positive that cannot be fixed naturally:

- `.grace/lint_allowlist.yaml`

Any allowlist change must be narrow, truthful, non-size, and explained. Never add `GRC005` or `GRC012` suppression. Do not hide identifiers with `getattr`, `__dict__`, split strings, dynamic imports or similar constructions merely to satisfy textual lint.

### Explicitly out of scope

Do not modify/refactor the block-06 near-limit targets in this TZ:

- `src/grace_control/api/routers/admin_controls.py`
- `src/grace_control/services/admin_cross_project_service.py`
- `src/grace_control/services/admin_mutation_service.py`
- `src/grace_control/api/routers/admin_control_center.py`
- `src/grace_control/core/acceptance_pipeline.py`

Do not reopen Part A (`admin_aggregation_service.py` and its new read owners) unless a concrete, test-backed compatibility blocker proves it unavoidable.

Do not perform a UI/template redesign, route rewrite, auth redesign, API feature addition, schema migration, config cleanup, or unrelated lint cleanup.

Frozen by default:

- `src/grace_control/db/schema.py`
- Alembic migrations
- `src/grace_control/core/contracts.py`
- `src/grace_control/config/settings.py`
- `src/grace_control/core/state_machine.py`
- public API schemas/routes solely to accommodate the refactor

If an unavoidable compatibility reason requires a frozen file, keep it minimal, test it, and explain it in the submission.

## Existing ownership that must be inspected and reused

Before coding, produce a short ownership map of the current facade and these existing owners/helpers. Reuse them; do not create competing copies of their rules:

- `admin_control_center_helpers.py` — pure project/dashboard/entity/timeline/pipeline normalization and secret masking adapters;
- `admin_control_center_explorer_helpers.py` — pure explorer path, artifact, Git/OpenAPI normalization and request-materialization helpers;
- `admin_control_local_helpers.py` — local control identity, strict audit and local OpenAPI request helpers;
- `admin_control_security.py` — authorization/same-origin/operator-data masking boundary;
- `AdminCrossProjectService` — project registry, cross-project fan-out, bounded project requests, events/logs/search reads;
- `AdminMutationService` — authoritative mutation/control/OpenAPI mutation owner;
- existing Git/filesystem/admin APIs — authoritative remote capability boundaries.

The existing helper modules above are **not automatic refactor targets**. Do not rewrite them merely because they are nearby. Only change one if a moved responsibility genuinely belongs there, the change stays bounded, and tests demonstrate compatibility.

## Required responsibility decomposition

Refactor by use case, not arbitrary line ranges.

### 1. Stable compatibility facade

Keep `grace_control.services.admin_control_center.AdminControlCenterService` import and constructor compatible.

The router must continue to call the same public service methods with the same signatures and receive the same view-model shapes:

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

Preserve any existing private seam demonstrably imported, called or monkeypatched by current code/tests. Prefer delegating wrappers from the facade over a flag-day migration.

### 2. Project/dashboard shell owner

A coherent owner may contain:

- dashboard composition/filtering/order;
- project context/card/selector composition;
- shared explorer/project shell construction;
- project-local bounded read result normalization.

Preserve explicit registry `project_key` identity. Never introduce ambient/global current-project state.

### 3. Packet drill-down owner

The current `_packet_page(...)` is a large multi-tab orchestration function and must receive real responsibility decomposition rather than being copied wholesale.

A packet-focused owner may coordinate:

- canonical packet detail/blocking/raw/run/stage reads;
- run/stage selection and run scoping;
- timeline filtering;
- sessions/diagnostics/evidence/log/artifact tab reads;
- packet control availability via the existing `AdminMutationService` owner;
- stale-base/lease/pipeline normalization through existing helpers;
- delegation to Files/Git explorer owners rather than duplicating them.

Split further into coherent helpers/owners when needed so no new packet drill-down function simply parks near the 4000-token limit. Keep selected-run/stage validation, packet ownership checks and DTO fallback semantics unchanged.

### 4. Explorer owner(s)

A coherent explorer owner may coordinate current project-scoped:

- filesystem page reads (`/api/admin/fs/*`);
- Git page reads (`/api/admin/git/*`);
- OpenAPI discovery/cache/GET exploration.

Reuse `admin_control_center_explorer_helpers.py` for path safety and normalization. Preserve:

- logical-root/path validation before remote file reads;
- changed-file/path restrictions for Git diff reads;
- bounded preview/tail/query/body limits;
- secret masking;
- capability/error-class/http-status fields;
- OpenAPI exact discovered-path/method validation;
- per-project OpenAPI cache semantics and TTL.

Do not create a lower-level helper that can perform an unscoped project read or bypass the Hub.

### 5. Mutation boundary must remain authoritative

`AdminControlCenterService.api_page(...)` currently delegates non-GET execution to `AdminMutationService(self._hub).execute_openapi(...)` only behind explicit control/mutation gating.

After extraction:

- mutations must still go through `AdminMutationService`;
- do not duplicate confirmation, audit or authorization policy in a new control-center owner;
- GET exploration remains read-only;
- mutation execution must remain impossible when `control_mode` / `allow_mutation` do not permit it;
- existing request/body/confirmation limits and error codes remain stable.

Do not move security enforcement out of its existing authoritative owners or make it optional.

### 6. System/maintenance/events/logs/search composition

These page methods may stay in the facade if already bounded, or move to one coherent read-page owner if that creates a useful responsibility boundary. Do not create a collection of tiny one-method modules solely to reduce line count.

Preserve query filters, pagination/cursor fields, dashboard selector context, masking and error propagation exactly.

## Behaviour that must remain unchanged

This is refactor-only. Preserve current observable behaviour, including:

- every current HTTP path/method and OpenAPI route/schema;
- `AdminControlCenterService` public import, constructor and public method signatures;
- project registry order and explicit project selection;
- disabled-project behaviour: no remote read when current code suppresses it;
- project isolation: no request may silently switch to another project or open another project's DB/filesystem;
- dashboard filters, ordering, coverage/errors/attention fields;
- feature/wave/packet selection and missing-entity behaviour;
- packet tab names and tab fallback;
- selected run/stage scoping and validation;
- events/logs filters, limits, cursor/follow/wrap fields;
- file logical-root and relative-path safety;
- Git repository/worktree/changed-file/diff DTOs and path restrictions;
- artifact/evidence/log preview bounds and source labels;
- system/maintenance/capabilities/lease/wait DTOs;
- secret masking;
- OpenAPI discovery/cache/path/query/body/confirmation semantics;
- read-only vs mutation boundary;
- `AdminMutationService` control availability and execution semantics;
- not-found/error-class/http-status/fallback mappings consumed by templates;
- template/UI view-model keys.

No browser-visible DTO field should be renamed/removed merely to simplify extraction.

## Regression protection

Existing behavioural/API tests are the contract and must not be weakened. Before coding, inspect all current source/tests that instantiate/import `AdminControlCenterService`, call its methods, depend on private/module helpers, or monkeypatch symbols in `admin_control_center`.

At minimum preserve or add coverage for current behaviours where they exist:

1. dashboard project ordering/filtering/attention/offline/disabled behaviour;
2. explicit project selection and project isolation;
3. feature/wave/packet selection and missing entity handling;
4. packet detail/run/stage/timeline/evidence/log/artifact/raw tab composition;
5. selected-run/stage scoping cannot cross packet/run identity;
6. filesystem root/path traversal rejection and disabled-project no-read behaviour;
7. Git changed-path and diff restrictions;
8. API explorer discovers only OpenAPI operations, GET remains read-only, mutation requires control mode + authorized mutation path and still delegates to `AdminMutationService`;
9. system/maintenance/events/logs/search DTO and error compatibility;
10. secret masking and capability/error metadata;
11. OpenAPI/admin route surface unchanged.

The existing matrix coverage around `AdminControlCenterService` and current control-center API/router tests are directly affected. Run the real test modules discovered from imports; do not invent test filenames.

Allowed test edits:

- add focused tests for newly extracted owners;
- minimally retarget an internal monkeypatch when ownership genuinely moved;
- add facade/import/delegation compatibility coverage.

Forbidden:

- deleting behavioural/security assertions;
- broad skip/xfail additions;
- changing expected DTO/status/error results merely to fit refactored code;
- replacing integration/API security coverage with mocks only.

## API/OpenAPI stability

`make docs-check` is required.

If `docs/openapi.json` changes, inspect the semantic diff. A pure internal service refactor must not add/remove/change admin routes or schemas. Unexpected OpenAPI drift is a blocker, not a generated-file update to accept blindly.

Do not edit the near-limit router just to accommodate a changed internal service contract; preserve the service contract instead.

## Lint / structural guardrails

Accepted block 01 semantics are authoritative:

- `GRC005`: violation only when a Python file has `> 1000` physical lines;
- `GRC012`: violation only when `len(function_source) // 4 > 4000`;
- `GRC012` applies to public/private sync/async functions;
- no `GRC005/GRC012` allowlist suppressions.

MASTER preferred headroom is an architectural target. Do not park the facade or a new owner at 999 lines or move `_packet_page` into a 3999-token replacement when a coherent extraction exists.

This repository contains some historical textual-lint workarounds outside this packet's owned target. Do **not** expand TZ05 Part B into a generic cleanup campaign. For code you move or newly write in this packet, however, do not introduce new identifier-obscuring lint-evasion. Use a narrow truthful non-size allowlist entry only for a genuine textual false positive.

## Required verification

First identify and run the smallest directly affected current control-center service/API test modules from actual imports/calls.

At minimum also run:

```bash
make test
make lint
make docs-check
git diff --check
```

And run:

- `.venv/bin/python -m py_compile` on `admin_control_center.py` and every touched/new control-center Python module;
- `scripts/grace_lint.py` targeted at `admin_control_center.py` and every touched/new control-center Python module;
- current tests directly exercising `AdminControlCenterService`, project isolation, Files/Git/API explorers, mutation gating/security, and router/template view-model compatibility.

The repository currently has known baseline/environment debt outside this packet. Do not assume any non-zero command is baseline from history. If any required broad or directly affected command is non-zero, compare the **exact failure-node/output set** against a clean parent checkout using the same environment and exact command arguments. Report whether the sets are identical. Any new failure attributable to this packet is a blocker.

`make lint` currently may be blocked by the repository `.venv` lacking Ruff; re-attempt it and report the exact result. Do not claim it passed if it did not.

For `make docs-check`, if the known generated-doc drift remains, compare the exact changed generated files and semantic OpenAPI result with the clean parent. No new semantic OpenAPI drift is allowed.

## Acceptance criteria

Architect ACCEPT requires all of the following:

1. `admin_control_center.py <= 1000` lines with practical headroom; preferred `<= 600–800` unless a clearly justified stable facade needs more.
2. Current `_packet_page` hard/near-limit debt is genuinely decomposed; no touched/new function exceeds 4000 estimated tokens and large orchestration functions have practical headroom.
3. No new Python module exceeds 1000 lines; avoid near-limit parking where a coherent boundary remains.
4. Responsibilities are extracted coherently, not by arbitrary line slicing/compression.
5. `AdminControlCenterService` public import/constructor/public signatures remain compatible.
6. Existing project selection/isolation/disabled-project semantics remain unchanged.
7. Filesystem/Git/OpenAPI path safety and bounded-read semantics remain unchanged.
8. Mutation/control execution still delegates to the authoritative `AdminMutationService`/security/audit owners; no bypass is introduced.
9. Existing helper/security/cross-project owners are reused rather than duplicated.
10. Existing DTO keys, fallback/error/capability fields, tab selection and template-facing behaviour remain unchanged.
11. Existing behavioural/security/API tests are not weakened.
12. Directly affected tests pass, or any non-zero set is proven identical to a clean parent baseline.
13. Targeted GraceLint and `py_compile` pass for every touched/new source file.
14. `make docs-check` shows no semantic OpenAPI/admin route drift, or any environment/baseline-only drift is proven against clean parent.
15. No `GRC005/GRC012` suppression or new lint-evasion construction is introduced.
16. Diff contains no block 06, Part A rewrite, unrelated UI/product/API/DB/config/state-machine work.
17. Any broad-suite non-zero result is proven against the clean parent rather than merely labelled pre-existing.

## Submission content

Keep `05_ADMIN_CONTROL_CENTER_SUBMISSION.md` concise but include:

- exact implementation commit SHA;
- files created/modified;
- before/after physical line count for `admin_control_center.py`;
- largest function(s) in every touched/new module using `len(source) // 4`;
- old responsibility -> new owner map, including explicit treatment of `_packet_page`;
- existing helpers/services reused rather than copied;
- public facade/private patch seams retained or intentionally retargeted;
- tests changed/added and why;
- confirmation no behavioural/security assertion was weakened;
- confirmation project isolation, path safety, mutation gating and DTO/fallback semantics remain stable;
- exact verification commands/results;
- `make docs-check` / OpenAPI semantic-diff result;
- any broad/direct baseline failures with clean-parent comparison evidence;
- any narrow non-size allowlist change and rationale;
- any known follow-up debt, without starting block 06 or another named TZ.
