# Task 009 resubmission — review fix-up 2

Review fixes implemented and pushed in commit `7dc8be0e`.

- Overview now validates the diagnostics payload against the canonical Stage 02 field set; structurally malformed successful responses are marked partial, returned as per-project malformed errors and excluded from count aggregates.
- Event and log continuation now uses the merged accessible domain formed by each selected project's bounded prefix (`sum(min(project_total, per_project_cap))`), while retaining deterministic ordering and project/filter-bound cursors.
- Diagnostics keeps health-only partial snapshots visible but excludes unavailable diagnostic counters from aggregate totals and marks the project partial.
- Registry project metadata search is returned even when that project's canonical search endpoint fails; the remote failure remains in `errors`.
- Default overview now includes disabled registry projects as local `disabled` cards, excludes them from remote fan-out and distinguishes them in coverage from failed projects.
- Added acceptance tests for malformed overview diagnostics, both-project continuation beyond one per-project cap, health-only diagnostics, search fallback and disabled overview behavior.

Checks:

- Task 009 acceptance tests: `11 passed`.
- Relevant Task 007–008/Admin/Trace/Events/Diagnostics regressions: `55 passed`.
- Ruff: PASS.
- `py_compile`: PASS.
- GRACE lint: PASS for changed Task 009 service/helper/test files.
- `git diff --cached --check`: PASS.
- The combined 89-test regression command also reports the same 6 pre-existing `test_admin_router.py` legacy expectation failures; no new failure is related to this fix-up.

No Task 010 / Stage 04 work was started.

WEB_ORCH_REPORT: RESUBMISSION 009
WEB_ORCH_STATUS: DONE
WEB_ORCH_COMMIT: 7dc8be0e
WEB_ORCH_CHECKS: PASS
