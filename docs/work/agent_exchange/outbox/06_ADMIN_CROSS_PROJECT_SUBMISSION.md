WEB_ORCH_REPORT: SUBMISSION 06_ADMIN_CROSS_PROJECT
WEB_ORCH_STATUS: DONE
WEB_ORCH_COMMIT: 0b82abaf16b1eedb08f58410c9299d37df555f81
WEB_ORCH_CHECKS: PASS

# TZ 06_ADMIN_CROSS_PROJECT

Implemented and pushed the requested cross-project service refactor.

## Change map

- `admin_cross_project_service.py`: stable compatibility facade, 253 lines.
  Preserves `AdminCrossProjectService`, the exact constructor, public read
  methods, `_registry`, `_request`, `_select_contexts` and `_fanout` seams.
- `admin_cross_project_overview_mixin.py`: overview/diagnostics owner, 359
  lines.
- `admin_cross_project_query_mixin.py`: events/logs/search owner, 446 lines.
- No router, schema, mutation-service, acceptance, DB, UI or API route files
  were changed. No lint allowlist entries were added or changed.

The facade MRO keeps `get_projects_overview`, `get_diagnostics`,
`query_events`, `query_logs` and `search` delegated through the two owners;
`get_attention` remains a facade method and calls the public overview seam.
All owner internals continue to call `self._registry`, `self._select_contexts`,
`self._fanout` and `self._request`, so operational monkeypatch targets are not
bypassed.

AST comparison against the clean parent found no missing methods and no
signature/body mismatches for `__init__`, all six public methods, the three
compatibility seams, and the two overview helpers. Largest function sizes by
`len(source)//4`: `query_logs` 1530, `query_events` 1187,
`get_diagnostics` 922; all are below the 4000 limit.

## Verification

- Required focused suites: **27 passed, 1 skipped**.
- Current mutation/control-center, router, OpenAPI and aggregation suites:
  **109 passed**.
- `python3 -m py_compile` for facade and both owners: PASS.
- Targeted Ruff: PASS.
- Targeted `python3 scripts/grace_lint.py`: PASS.
- `git diff --check`: PASS.
- OpenAPI/route semantic checks (`test_admin_router.py`,
  `test_openapi_paths.py`): PASS; no route files changed.
- `make test`: 1584 passed, 2 skipped, 33 failed. The clean parent run with
  the identical command and environment produced the exact same 33 failure
  nodes and failure output set, all outside this packet's files:
  `test_w3_config_cleanup` (2),
  `test_execution_environment_vertical_slice` (1),
  `test_opencode_attach_runtime` (1),
  `test_opencode_runtime_adapter` (3),
  `test_context_builder_safety` (2),
  `test_feature_planning_service` (2),
  `test_feature_planning_store` (9),
  `test_queue_service` (1),
  `test_session_hardening` (3),
  `test_session_resume_followup` (3),
  `test_session_resume_phase2` (3), and
  `test_session_store` (3).
- `make lint`: the worktree and clean parent both stop at
  `.venv/bin/python: No module named ruff`; the required targeted Ruff check
  passed in both applicable source scope and the packet files.
- `make docs-check`: the worktree and clean parent both report the same
  pre-existing drift in exactly `docs/openapi.json`,
  `docs/state-diagram.md` and `docs/packet-states.md`.

The implementation preserves project isolation, registry ordering, disabled
project behavior, bounded concurrency, transport/error classification,
identity checks, 404 capability handling, DTO ordering/filter/cursor behavior,
coverage and attention semantics. The implementation commit was pushed before
this report was created. No next task is included.
