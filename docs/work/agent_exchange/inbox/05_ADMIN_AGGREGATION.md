# TZ 05_ADMIN_AGGREGATION — Grace Local Adopt admin aggregation read-side refactor

Status: READY FOR CODER
Source programme: `TZ_GRACE_LOCAL_ADOPT_REFACTOR_MASTER.md`
Source block: `TZ_GRACE_LOCAL_ADOPT_REFACTOR_05_ADMIN_CONTROL_PLANE.md` Part A
Dependency: previous Local Adopt named TZs through `04_MERGE_PIPELINE` — ACCEPTED by Architect

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
4. Create **only** `docs/work/agent_exchange/outbox/05_ADMIN_AGGREGATION_SUBMISSION.md` for the report.
5. Do not create the next task, review file, `state.json`, lock files, orchestration metadata, or any other coordination file.

The submission must contain these exact lines with the real implementation commit SHA:

```text
WEB_ORCH_REPORT: SUBMISSION 05_ADMIN_AGGREGATION
WEB_ORCH_STATUS: DONE
WEB_ORCH_COMMIT: <commit-sha>
WEB_ORCH_CHECKS: PASS
```

If the Architect later returns REVIEW, read only `docs/work/agent_exchange/inbox/05_ADMIN_AGGREGATION_REVIEW.md`, fix that review, and report only to `docs/work/agent_exchange/outbox/05_ADMIN_AGGREGATION_RESUBMISSION.md`.

## Goal

Refactor the hard-limit read-side module `src/grace_control/services/admin_aggregation_service.py` into a bounded, stable `AdminAggregationService` facade backed by coherent read-only owners, **without changing any public admin API/DTO behaviour**.

This packet implements **Part A only** of source block 05. Do not start `admin_control_center.py` (Part B) or any block 06 near-limit work.

Required structural result:

- `admin_aggregation_service.py` must be `<= 1000` physical lines with practical headroom; source target is preferably `<= 500–700` when a thin facade is natural;
- every touched/new function or async function must remain `< 4000` Grace-estimated tokens (`len(source) // 4`), with large orchestration functions normally `<= 2500–3000`;
- every new Python module must be `<= 1000` physical lines, preferably `<= 800`;
- do not merely move an oversized/near-limit method or arbitrary line ranges into a new near-limit file.

## Owned write scope

Primary source:

- `src/grace_control/services/admin_aggregation_service.py`

Expected new focused read-only service modules under `src/grace_control/services/`, for example where current responsibilities justify them:

- overview/system read composition;
- packet/run/detail/pipeline read composition;
- artifact/evidence read composition;
- logs/sessions/search read composition.

Exact names are up to the implementation, but boundaries must be coherent and non-duplicated.

Directly affected admin service/API tests may be changed or extended only as allowed below.

Optional only if moved code produces a genuine textual non-size GraceLint false positive that cannot be fixed naturally:

- `.grace/lint_allowlist.yaml`

Any allowlist change must be narrow, truthful, non-size, and explained. Never add `GRC005` or `GRC012` suppression and never obscure normal identifiers to evade GraceLint.

### Explicitly out of scope

Do not modify/start:

- `src/grace_control/services/admin_control_center.py` or its Part-B refactor;
- block 06 near-limit modules (`admin_controls.py`, `admin_cross_project_service.py`, `admin_mutation_service.py`, router `admin_control_center.py`, `acceptance_pipeline.py`);
- UI redesign or template redesign;
- unrelated product/admin feature work.

Frozen by default:

- `src/grace_control/db/schema.py`
- Alembic migrations
- `src/grace_control/core/contracts.py`
- `src/grace_control/config/settings.py`
- `src/grace_control/core/state_machine.py`
- public API schemas/routes purely to accommodate the refactor

If an unavoidable compatibility reason requires a frozen file, keep it minimal, test it, and explain it in the submission.

## Existing ownership that must be inspected/reused

Before extracting, inspect existing read helpers/services and callers so this packet does not create duplicate DTO/business logic. In particular, account for existing services such as `admin_raw_read_service.py`, `safe_filesystem_service.py`, `size_calculator.py`, session/event/trace services, and current admin routers/callers.

`AdminRawReadService` currently depends on `AdminAggregationService` for canonical packet state-machine/pipeline/recovery/totals summaries. Preserve that dependency boundary or provide an equally compatible facade; do not create a second competing packet-summary implementation.

Existing safe filesystem/path containment and preview policy remain authoritative. Artifact extraction must reuse them rather than introduce a looser filesystem path.

## Required responsibility decomposition

Refactor by read responsibility, not line count alone.

### 1. Stable facade

Keep `grace_control.services.admin_aggregation_service.AdminAggregationService` import and current constructor/public methods compatible.

Routers and other services should not need public route/schema changes just because internals moved. Prefer delegation from the existing facade.

Module-level compatibility helpers that are imported or monkeypatched elsewhere must remain available or be intentionally retargeted with explicit compatibility coverage.

### 2. Overview/system read owner

A coherent owner may contain current read-only composition for:

- packet-state/feature/wave/packet counts;
- worker summaries;
- recent events;
- blocked packet summary;
- system health.

Preserve exact DTO keys, ordering where observable, fallback shapes, limits and timestamps semantics.

### 3. Packet/run/detail read owner

A coherent owner may contain:

- packet detail DTO;
- run list/detail summaries;
- feature/wave/tree summaries;
- packet pipeline/stage derivation;
- size/timing summaries;
- blocking/recommendation read models where packet/run-specific.

Do not duplicate `AdminRawReadService`; keep one authoritative implementation for shared summaries.

### 4. Artifact/evidence read owner

A coherent owner may contain:

- `_classify_artifact` / bounded artifact tree behaviour;
- evidence DTO composition;
- run artifact summary;
- artifact file/preview read orchestration.

Preserve exactly the current safety and limits, including containment, max file/tree/preview bounds, MIME/kind mapping, binary handling, truncation flags, and `None`/empty fallback behaviour. Reuse `SafeFilesystemService` where the current facade already does.

### 5. Logs/sessions/search owner

If sizeable enough, extract coherent read-only handling for packet logs, sessions, search or related read lookup surfaces. Do not create tiny one-function modules merely to reduce line count.

Preserve current tail/filter/regex semantics, source selection, limits and fallback DTOs.

## Behaviour that must remain unchanged

This is refactor-only. Preserve current observable behaviour, including:

- every current admin HTTP path and method;
- request schemas and response DTO keys/shapes;
- HTTP status/not-found/error mapping;
- `AdminAggregationService` public import, constructor and method signatures;
- `None` versus empty-list/empty-dict fallbacks;
- packet/feature/wave/run ordering where observable;
- packet state/pipeline/stage derivation;
- run/evidence/artifact/log/session/search/health DTO keys;
- artifact MIME/kind/preview/truncation behaviour;
- filesystem/path safety and physical-path exposure policy;
- read-only semantics: this service must not acquire mutation/control responsibility;
- project/local data semantics used by current callers;
- OpenAPI/admin route surface.

Do not “clean up” odd legacy values or DTO shapes in this packet unless an existing test proves they are incorrect; compatibility is the goal.

## Regression protection

Existing behavioural/API tests are the contract and must not be weakened. Before coding, inspect all current source/tests that instantiate/import `AdminAggregationService`, call its methods, depend on its private/module helpers, or monkeypatch symbols in `admin_aggregation_service`.

At minimum preserve or add coverage for current behaviours where they exist:

1. overview counts/state/worker/recent-event/blocked/health DTOs;
2. packet detail and state-machine/pipeline/timing/totals data;
3. feature tree and wave detail ordering/counts;
4. run list/detail DTOs and not-found selectors;
5. evidence DTO and acceptance-stage command summaries;
6. artifact tree bounds, type/MIME classification and truncation;
7. artifact file/preview safe-path rejection and binary/text behaviour;
8. packet logs tail/filter/source selection and fallback DTO;
9. sessions/search/read-only lookups;
10. `AdminRawReadService` compatibility with the facade;
11. public admin API DTO/status compatibility.

Allowed test edits:

- add focused unit tests for an extracted read owner;
- minimally retarget an internal monkeypatch when ownership genuinely moved;
- add facade/import compatibility tests.

Forbidden:

- deleting behavioural assertions;
- renaming/removing expected DTO fields;
- changing expected `None`/empty fallback shapes to simplify code;
- broad `skip`/`xfail` additions;
- replacing API/integration coverage with mocks only.

## API/OpenAPI stability

Because this read service feeds the admin UI directly, `make docs-check` is required.

If `docs/openapi.json` changes, inspect the semantic diff. A pure internal refactor must not add/remove/change admin routes or schemas. Unexpected OpenAPI drift is a blocker, not a generated-file update to accept blindly.

Do not modify routers simply to match a changed internal DTO. Preserve the DTO instead.

## Lint / structural guardrails

Accepted block 01 semantics are authoritative:

- `GRC005`: violation only when a Python file has `> 1000` physical lines;
- `GRC012`: violation only when `len(function_source) // 4 > 4000`;
- `GRC012` applies to public/private sync/async functions;
- no `GRC005`/`GRC012` allowlist suppressions.

MASTER preferred headroom remains an architectural acceptance target; do not park the facade or a new owner immediately below hard limits when a coherent further extraction exists.

## Required verification

First identify and run the smallest directly affected current admin service/API test modules from actual imports/calls. Do not invent a test filename.

At minimum also run:

```bash
make test
make lint
make docs-check
git diff --check
```

And run:

- `.venv/bin/python -m py_compile` on `admin_aggregation_service.py` and every touched/new read-side Python module;
- `scripts/grace_lint.py` targeted at `admin_aggregation_service.py` and every touched/new read-side Python module;
- current tests directly exercising aggregation DTOs, admin routers that expose them, artifact/evidence/log/session reads, and `AdminRawReadService` compatibility.

The repository currently has known baseline/environment debt outside this packet (including Ruff availability in the provided environment and a stable broad-suite failure set). Do not assume any failure is baseline from history. If any required broad or directly affected command is non-zero, compare the **exact failure-node/output set** against a clean parent checkout using the same environment and exact command arguments. Report whether the sets are identical. Any new failure attributable to this packet is a blocker.

Do not claim an individual command passed when it failed. `WEB_ORCH_CHECKS: PASS` may only mean the TZ-specific implementation is green with separately proven baseline/environment blockers reported precisely.

## Acceptance criteria

Architect ACCEPT requires all of the following:

1. `admin_aggregation_service.py <= 1000` lines with practical headroom; target preferably `<= 500–700`.
2. No touched/new function exceeds 4000 estimated tokens; large orchestration/read-composition functions have practical headroom.
3. No new Python module exceeds 1000 lines; avoid near-limit parking where coherent further extraction exists.
4. Responsibilities are extracted coherently, not by arbitrary line slicing/compression.
5. `AdminAggregationService` public import/constructor/method signatures remain compatible.
6. Existing admin DTO shapes, ordering, fallbacks, status/not-found behaviour and read-only semantics remain unchanged.
7. Artifact/evidence/log safety, limits, MIME/kind/truncation and path containment remain unchanged.
8. Existing dedicated read/safe-filesystem/raw-read owners are reused rather than duplicated.
9. Existing behavioural/API tests are not weakened.
10. Directly affected tests pass, or any non-zero set is proven identical to a clean parent baseline.
11. Targeted GraceLint and `py_compile` pass for every touched/new source file.
12. `make docs-check` shows no semantic OpenAPI/admin route drift, or any environment-only blocker is proven against clean parent.
13. No `GRC005/GRC012` suppression or lint-evasion construction is introduced.
14. Diff contains no Part B/block 06 or unrelated product/API/DB/config/state-machine/UI redesign work.
15. Any broad-suite non-zero result is proven against the clean parent rather than merely labelled pre-existing.

## Submission content

Keep `05_ADMIN_AGGREGATION_SUBMISSION.md` concise but include:

- exact implementation commit SHA;
- files created/modified;
- before/after physical line count for `admin_aggregation_service.py`;
- largest function(s) in every touched/new module using `len(source) // 4`;
- old responsibility -> new owner map;
- existing services/helpers reused rather than copied;
- public facade/re-exports/patch points retained or intentionally retargeted;
- tests changed/added and why;
- confirmation no behavioural assertion was weakened;
- confirmation DTO/fallback/read-only/path-safety semantics remain stable;
- exact verification commands/results;
- `make docs-check` / OpenAPI semantic-diff result;
- any baseline/environment failures with clean-parent comparison evidence;
- any narrow non-size allowlist change and rationale;
- any known follow-up debt, without starting Part B or another named TZ.
