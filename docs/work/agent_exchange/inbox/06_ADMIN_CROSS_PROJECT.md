# TZ 06_ADMIN_CROSS_PROJECT — Grace Local Adopt cross-project read headroom

Status: READY FOR CODER
Source programme: `TZ_GRACE_LOCAL_ADOPT_REFACTOR_MASTER.md`
Source block: `TZ_GRACE_LOCAL_ADOPT_REFACTOR_06_NEAR_LIMIT_FOLLOWUP.md` Part B2
Dependencies: block 05 hard-limit admin service work accepted; 06_ACCEPTANCE_PIPELINE accepted

## Coder protocol

You are the Coder for this named TZ. Read and execute **only this file**. Do not open or start another inbox task/TZ unless the Architect explicitly names it after ACCEPT.

Before editing:

1. Work in `/opt/grace-orchestrator`.
2. Fast-forward sync with GitHub; checkout must be clean and updated from `origin/main` with no merge commit.
3. If fast-forward cannot be done cleanly, stop and report the blocker.

After implementation:

1. Run the required verification below.
2. Commit and push the implementation.
3. Create **only** `docs/work/agent_exchange/outbox/06_ADMIN_CROSS_PROJECT_SUBMISSION.md`.
4. Do not create the next task, review file, state/lock/orchestration metadata or unrelated coordination files.

Submission header must be exactly:

```text
WEB_ORCH_REPORT: SUBMISSION 06_ADMIN_CROSS_PROJECT
WEB_ORCH_STATUS: DONE
WEB_ORCH_COMMIT: <implementation-sha>
WEB_ORCH_CHECKS: PASS
```

If Architect returns REVIEW, read only `docs/work/agent_exchange/inbox/06_ADMIN_CROSS_PROJECT_REVIEW.md`, fix it, and report only to `docs/work/agent_exchange/outbox/06_ADMIN_CROSS_PROJECT_RESUBMISSION.md`.

## Goal

Create substantial structural headroom in:

- `src/grace_control/services/admin_cross_project_service.py`

This is **only block 06 Part B2**. Keep `AdminCrossProjectService` as the stable compatibility facade while extracting coherent cross-project read/composition responsibilities. Do not start mutation-service or router refactors in this packet.

Target:

- facade preferably `<= 650–750` physical lines and with clear headroom below 1000;
- every new/touched function `<= 4000` Grace-estimated tokens, normally `<= 2500–3000` for orchestration;
- each new module `<= 1000`, preferably `<= 800`;
- no arbitrary line slicing, compressed formatting, giant moved-verbatim owner or lint-evasion construction.

## Owned write scope

Primary:

- `src/grace_control/services/admin_cross_project_service.py`
- new focused cross-project read/composition modules under `src/grace_control/services/`
- directly affected cross-project/admin tests when genuinely needed

Optional only for a genuine textual **non-size** GraceLint false positive introduced by moved code:

- `.grace/lint_allowlist.yaml`

Never add GRC005/GRC012 suppression and never obscure identifiers to evade textual lint.

### Explicitly out of scope

Do not modify/refactor in this TZ:

- `src/grace_control/services/admin_mutation_service.py`
- `src/grace_control/api/routers/admin_controls.py`
- `src/grace_control/api/routers/admin_control_center.py`
- accepted block-05 control-center/aggregation services except an unavoidable tiny compatibility fix
- acceptance pipeline files
- DB schema/migrations, settings, state machine, public API schemas/routes, templates/UI

## Stable public surface

Preserve import and constructor compatibility for:

- `grace_control.services.admin_cross_project_service.AdminCrossProjectService`
- `AdminCrossProjectService.__init__(registry, *, client_factory=None, max_concurrency=8, connect_timeout=1.0, read_timeout=3.0)`

Preserve public method names, signatures and observable DTOs for at least:

- `get_projects_overview(...)`
- `query_events(...)`
- `query_logs(...)`
- `search(...)`
- `get_diagnostics(...)`
- `get_attention(...)`

No route/API caller should need to change merely because implementation ownership moved.

## Compatibility seams that are operationally relied on

Before moving internals, search current code/tests for direct private use and preserve demonstrated seams.

At minimum, current settled admin code relies on the Hub internals below and they must remain compatible:

- `hub._registry` — registry identity used by Control Center and mutation service;
- `hub._request(context, path, params=None, *, operation=...)` — selected-project read transport used by Control Center and `AdminMutationService`;
- current client-factory/timeout/concurrency construction semantics.

Also preserve `_select_contexts(...)` and `_fanout(...)` as delegating compatibility methods if current tests/callers exercise them. Do not silently make existing private seams dead wrappers while internal callers bypass monkeypatch targets that tests rely on.

## Required responsibility decomposition

Use current behavior/tests as contract. Exact module names are flexible, but split by responsibility.

Good candidate owners include:

1. **Project/overview composition** — project selection, disabled-project rows, health/diagnostics/latest-event composition, attention/coverage and aggregate card semantics.
2. **Events/search query composition** — bounded per-project reads, merge/order/filter/cursor semantics and project-attributed results.
3. **Logs query composition** — source routing, packet/run/stage/system log selection, bounded tail/cursor/filter/regex semantics.
4. **Diagnostics composition** — per-project diagnostic snapshots, aggregate/coverage/attention semantics.
5. Keep transport/fan-out coordination in the facade or a coherent shared owner only if public/private compatibility remains clear.

Do not duplicate logic already owned by `admin_cross_project_helpers.py`, `ProjectRegistry`, `ProjectClient`, filesystem/runtime services or settled block-05 services. Reuse those boundaries.

## Project-isolation and transport behavior that must not drift

Preserve exactly:

- explicit registry project selection; no ambient/current-project state;
- registry ordering of results;
- unknown explicit project -> existing `KeyError` behavior;
- default selection of enabled projects;
- disabled project behavior, including **no remote read** where the current method promises that;
- bounded concurrent fan-out using the configured max concurrency;
- no Hub-side project DB/filesystem/worktree/Git opening;
- one project failure never reroutes to or contaminates another project;
- health identity mismatch detection;
- transport/HTTP/malformed/capability error classification and safe error text;
- 404 capability handling where currently special-cased;
- exact project attribution fields and canonical Hub detail URLs.

## DTO/query behavior that must not drift

Preserve existing keys, status/partial semantics, ordering, limits and continuation behavior for overview/events/logs/search/diagnostics/attention.

In particular preserve where applicable:

- `projects`, `aggregate`/`aggregates`, `coverage`, `errors`, `attention`, `fetched_at`;
- event ordering by source timestamp and full safe payload/trace identity;
- event cursor project/filter validation and bounded-offset continuation;
- event per-project cap and partial/known-total semantics;
- log source mapping, run/stage/packet selection, bounded tail and cursor semantics;
- log regex error behavior and text/level/trace/time filtering;
- search ordering/filter/project attribution and bounded results;
- diagnostics availability detection, aggregation and missing-data-not-healthy-zero behavior;
- attention severity/reason/source/timestamp/entity fields and ordering;
- existing response fallback/error shapes.

No public HTTP route, method, status code or OpenAPI-visible schema may change.

## Existing authoritative helpers

Inspect and reuse, rather than copy:

- `admin_cross_project_helpers.py` normalization, cursor, coverage, sorting, error and aggregation helpers;
- `admin_control_center_explorer_helpers._event_matches_text` where currently used;
- `ProjectRegistry` for project identity/order/enabled selection;
- `ProjectClient` / current compatible test client boundary;
- settled block-05 `AdminControlCenterService` and `AdminMutationService` usage of Hub `_registry` / `_request`.

If an extracted owner needs transport, prefer an explicit callback/protocol/reference to the facade-owned boundary over importing the facade back from a lower-level helper and creating cycles.

## Regression protection / tests

Existing behavioral tests must not be weakened.

Before coding, discover the actual current callers and tests. At minimum inspect/run relevant coverage including:

- `tests/grace_control/api/test_admin_cross_project_observability.py`;
- `tests/grace_control/api/test_admin_hub_project_foundation.py`;
- `tests/grace_control/api/test_admin_control_center_stage07.py`;
- `tests/grace_control/api/test_admin_control_center_stage07_matrix.py`;
- current mutation/control-center tests that depend on Hub `_registry` / `_request`.

Keep coverage for:

1. explicit multi-project ordering/filtering and unknown-project behavior;
2. disabled-project no-read semantics;
3. refused/timeout/HTTP500/malformed/missing-capability/identity-mismatch isolation;
4. bounded concurrency and no rerouting;
5. overview coverage/aggregate/attention behavior;
6. event merge/filter/cursor/partial semantics;
7. logs source/entity/filter/regex/cursor/tail semantics;
8. search and diagnostics DTOs;
9. Control Center reads through `_request`;
10. mutation service capability/discovery reads through the same selected-project Hub boundary.

Allowed test edits: focused extraction-unit tests, compatibility-import/delegation tests, minimal monkeypatch retargeting when ownership genuinely moves.

Forbidden: deleting/weakening assertions, broad skip/xfail, changing expected DTO/status/error semantics, replacing integration coverage with mocks only, or loosening project isolation.

## Verification

Run directly affected current tests first, then at minimum:

```bash
make test
make lint
make docs-check
git diff --check
```

Also run:

- `.venv/bin/python -m py_compile` on the facade and every touched/new Python module;
- `python3 scripts/grace_lint.py` targeted at the facade and every touched/new module;
- Ruff targeted at touched/new modules when available;
- focused cross-project + Control Center + mutation compatibility tests discovered from current imports.

For every required command that is non-zero, compare the exact failure-node/output set against a **clean parent checkout** using the same environment and exact arguments. Do not merely label historical failures as baseline.

`make lint` may still be blocked by the repository `.venv` missing Ruff; re-attempt it and report the exact current/parent result. Targeted Ruff and GraceLint must still be run.

This service-only packet is not expected to alter OpenAPI. `make docs-check` and a semantic OpenAPI/route comparison should show no new public drift; if non-zero due known generated baseline, prove exact parent equivalence.

## Acceptance criteria

Architect ACCEPT requires:

1. substantial structural headroom in `admin_cross_project_service.py`;
2. no touched/new file >1000 lines and no function >4000 estimated tokens;
3. extraction by coherent read/composition responsibility;
4. stable `AdminCrossProjectService` import, constructor and public methods;
5. `_registry` and `_request` compatibility preserved for settled Control Center/mutation consumers;
6. project isolation, enabled/disabled selection and no-reroute semantics unchanged;
7. concurrency, timeouts, client-factory and transport error semantics unchanged;
8. overview/events/logs/search/diagnostics/attention DTOs, ordering, filters, limits and cursor behavior unchanged;
9. existing helper owners reused, not duplicated;
10. existing tests not weakened;
11. focused tests and targeted GraceLint/Ruff/py_compile pass;
12. every broad non-zero result proven identical to clean parent;
13. no API/DB/config/state/UI/block-06 mutation/router work included;
14. no GRC005/GRC012 suppression or lint-evasion construction.

## Submission content

Report concisely:

- implementation SHA;
- files created/modified;
- before/after physical lines for the facade and sizes of new owners;
- old responsibility -> new owner map;
- largest touched functions using `len(source) // 4`;
- public/private compatibility seams retained;
- tests changed/added and why, confirming no behavioral assertion weakened;
- exact focused test results;
- targeted GraceLint/Ruff/py_compile/diff-check results;
- `make test`, `make lint`, `make docs-check` results and clean-parent comparisons for every non-zero command;
- OpenAPI/route semantic comparison;
- allowlist changes and rationale, if any;
- confirmation that project isolation, ordering, filters/cursors, coverage/attention and Hub transport semantics are unchanged;
- follow-up debt only; do not start `admin_mutation_service.py` or router refactors.