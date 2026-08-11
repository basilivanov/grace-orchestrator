# Task 011 resubmission — Stage 05 review fixes

WEB_ORCH_REPORT: RESUBMISSION 011
WEB_ORCH_STATUS: DONE
WEB_ORCH_COMMIT: 3ef3f04058b884d504c4ad9814796d520e174bc5
WEB_ORCH_CHECKS: PASS

Implemented only the requested Stage 05 review fixes:

- Events and Logs now expose opaque, filter-preserving Next/cursor links without mixing `offset`; acceptance uses synthetic data to reach rows beyond page one.
- `source=all` is an explicit no-filter sentinel, source taxonomy maps to project-local streams, and Follow performs bounded HTMX polling while preserving away-from-bottom scroll position.
- Project and packet Git views provide changed-file selectors/links, selected-path context and bounded/truncation state; the exact selected path reaches Stage 02.
- OpenAPI GET execution now exposes bounded scalar path/query definitions, safely URL-encodes path parameters, rejects missing/undeclared selectors before execution, and keeps mutation/non-discovered routes disabled.

Latest review fixes:

- Follow polling keeps the existing filter/project/tail/follow/wrap URL state and
  uses `hx-select="#bounded-log-viewer"` with `hx-swap="outerHTML"`, so the
  production HX response swaps only one viewer rather than duplicating the Logs
  heading and filter form. The exact `/admin/logs` HX endpoint test asserts one
  filter form, one viewer and the selector; the browser scroll guard remains
  covered by the bounded browser acceptance test.
- OpenAPI path discovery now rejects network-path references, schemes,
  authorities, query-bearing templates, fragments and backslashes. The common
  `ProjectClient` boundary rejects alternate authorities before HTTPX transport,
  so project credentials cannot be forwarded to `//other-host/collect`.
- Added deterministic discovered-path and transport-level regressions for the
  cross-origin trap while retaining ordinary parameterized GET coverage.

Checks:

- Focused Stage 05 plus Task 007–010 isolation/read/aggregation/UI regressions: `91 passed, 2 skipped`.
- New browser follow test is defined and explicitly skipped because this environment has no Playwright (`No module named 'playwright'`).
- Targeted Ruff, `py_compile`, changed-file GRACE lint and `git diff --check`: passed.
- Repository-wide GRACE lint still reports existing legacy canon violations; the
  changed-file lint is clean. Unrelated legacy Admin router tests remain
  `29 passed, 6 failed` (the six failures are outside this review scope).

Task 012 was not started.
