# 06_ADMIN_CONTROLS_ROUTER submission

WEB_ORCH_REPORT: SUBMISSION 06_ADMIN_CONTROLS_ROUTER
WEB_ORCH_STATUS: DONE
WEB_ORCH_COMMIT: 5a2b6ec00cc9f94004c1f7e3d3418c50258fc22b
WEB_ORCH_CHECKS: PASS

## Implementation

The stable import and router facade remain in `src/grace_control/api/routers/admin_controls.py`.
The former 999-line module is now 675 lines. Route bodies were moved to focused owners:

- `admin_controls_hub.py` — Hub catalog, selected-project mutation, selected-project OpenAPI, and maintenance proxy (194 lines).
- `admin_controls_local.py` — local action dispatch, legacy adapter, and domain action adapter (368 lines).
- `admin_controls_maintenance.py` — local maintenance snapshot and bounded cleanup (189 lines).
- `admin_controls_openapi.py` — same-app OpenAPI safety gate, dispatch, and response decoding (226 lines).

All function source-size checks are below the packet limits. The largest owner functions are:

- `dispatch_local_action_impl`: 1,371 source chars / 4 = 342 tokens (rounded by the packet formula).
- `local_control_action_impl`: 1,160 / 4 = 290.
- `local_openapi_control_impl`: 1,288 / 4 = 322.
- `local_maintenance_cleanup_impl`: 897 / 4 = 224.

## Route compatibility

The parent and current AST route declarations are both exactly 10, with identical `(path, method, function)` entries:

- `GET /api/admin-hub/projects/{project_key}/controls`
- `POST /api/admin-hub/projects/{project_key}/controls`
- `POST /api/admin-hub/projects/{project_key}/control`
- `POST /api/admin-hub/projects/{project_key}/openapi-control`
- `POST /api/admin-hub/projects/{project_key}/api-control`
- `GET /api/admin-hub/projects/{project_key}/maintenance`
- `POST /api/admin/control/action`
- `GET /api/admin/maintenance/snapshot`
- `POST /api/admin/maintenance/cleanup`
- `POST /api/admin/control/openapi`

Route function signatures, defaults, decorator order, aliases, operation names, body declarations, and response annotations compare equal to the parent. `router` and `legacy_admin_action` remain import-compatible. The facade passes current module globals into owners, retaining monkeypatch seams for `_dispatch_local_action`, `record_event`, maintenance helpers, OpenAPI helpers, action/prefix policies, and masking.

## Semantics and scope

Authorization, project isolation, confirmation, audit-before/after, failure/unknown status mapping, bounded cleanup, dangerous OpenAPI path rejection, same-app dispatch, header forwarding, and legacy payload adaptation were moved without changing their behavior. The implementation does not touch `admin_control_center.py`, accepted mutation/cross-project services, DB/config/state/UI, or tests, and adds no allowlist entry.

## Verification

- Focused Stage 06, review-seam, Stage 07/matrix, admin-router, OpenAPI, maintenance, and legacy-pipeline tests: **106 passed, 1 skipped**.
- Full `make test`: **1584 passed, 2 skipped, 33 failed**; a clean parent worktree with the identical command produced the same counts and the same 33 pre-existing failures, with no packet-related failure.
- Targeted Ruff: passed.
- Targeted `python3 scripts/grace_lint.py` on the five changed router modules: passed.
- Targeted `py_compile`: passed.
- `git diff --check`: passed.
- `make lint`: current and clean parent both exit 2 because the shared `.venv` has no `ruff` module.
- `make docs-check`: current and clean parent both exit 2 with identical normalized diagnostics for the existing drift in `docs/openapi.json`, `docs/state-diagram.md`, and `docs/packet-states.md`.

No tests or assertions were weakened. No next task is proposed.
