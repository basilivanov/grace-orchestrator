# Task 011 resubmission — Stage 05 review fixes

WEB_ORCH_REPORT: RESUBMISSION 011
WEB_ORCH_STATUS: DONE
WEB_ORCH_COMMIT: 9bb11eca1b9dd32fa0a24c77c420af77444e8684
WEB_ORCH_CHECKS: PASS

Implemented only the requested Stage 05 review fixes:

- Events and Logs now expose opaque, filter-preserving Next/cursor links without mixing `offset`; acceptance uses synthetic data to reach rows beyond page one.
- `source=all` is an explicit no-filter sentinel, source taxonomy maps to project-local streams, and Follow performs bounded HTMX polling while preserving away-from-bottom scroll position.
- Project and packet Git views provide changed-file selectors/links, selected-path context and bounded/truncation state; the exact selected path reaches Stage 02.
- OpenAPI GET execution now exposes bounded scalar path/query definitions, safely URL-encodes path parameters, rejects missing/undeclared selectors before execution, and keeps mutation/non-discovered routes disabled.

Checks:

- Focused Stage 05 plus Task 007–010 isolation/read/aggregation/UI regressions: `89 passed, 2 skipped`.
- New browser follow test is defined and explicitly skipped because this environment has no Playwright (`No module named 'playwright'`).
- Targeted Ruff, `py_compile`, changed/new-file GRACE lint and `git diff --check`: passed.
- Full GRACE lint still reports the pre-existing `GRC005` oversized `admin_control_center.py`; unrelated legacy Admin router tests remain `29 passed, 6 failed`.

Task 012 was not started.
