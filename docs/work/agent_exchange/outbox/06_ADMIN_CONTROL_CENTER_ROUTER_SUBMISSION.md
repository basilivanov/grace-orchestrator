WEB_ORCH_REPORT: SUBMISSION 06_ADMIN_CONTROL_CENTER_ROUTER
WEB_ORCH_STATUS: DONE
WEB_ORCH_COMMIT: e7764521d74c454c0b364f3b77a332620b011c37
WEB_ORCH_CHECKS: PASS

# TZ 06_ADMIN_CONTROL_CENTER_ROUTER

Implemented and pushed the requested Control Center router decomposition.

Implementation parent: `2fe790288e8a052fb6498f1282d2c71f1aa5d7ab`.
Implementation commit: `e7764521d74c454c0b364f3b77a332620b011c37`.

## Structure

- `admin_control_center.py`: stable facade, router registration, compatibility seams; reduced from 982 to 615 lines.
- `admin_control_center_dashboard.py` (146 lines): dashboard/project shell and entity deep-link owners.
- `admin_control_center_project.py` (361 lines): packet and selected-project explorer owners.
- `admin_control_center_global.py` (172 lines): global Events, Logs and Search owners.
- `admin_control_center_partials.py` (192 lines): project/system HTMX partial owners.
- `admin_control_center_rendering.py` (247 lines): rendering, URL and status-icon helpers.

The facade still exports `router`, `_service`, `_render`, `_render_fragment`,
`_render_project_partial`, `_cc_url`, `_cc_query_url`, `_partial_url`,
`_status_icon`, `_raise_project_not_found` and `_templates`. Callback bridges
keep owner modules independent while preserving the accepted service boundary,
project isolation, empty-registry fallback, 404 behavior, template contexts,
HTMX fragment behavior and URL/query semantics. No services, templates, JSON
routers or tests were changed.

The largest function by the packet metric `len(source)//4` is
`partial_project_impl` at 355; all owner functions are below the required
4000 threshold and orchestration functions remain below the requested range.

## Contract preservation

AST comparison against the clean parent reports `PARENT_ROUTE_COUNT=20`,
`CURRENT_ROUTE_COUNT=20`, and `ROUTES_EQUAL=True`. Method/path/function names,
route signatures, Query defaults/constraints and `response_class=HTMLResponse`
are unchanged for:

`/admin`, `/admin/projects`, `/admin/_partial/projects`,
`/admin/p/{project_key}`, `/admin/p/{project_key}/feature/{feature_id}`,
`/admin/p/{project_key}/wave/{wave_id}`,
`/admin/p/{project_key}/packet/{packet_id}`,
`/admin/p/{project_key}/system`, `/admin/p/{project_key}/maintenance`,
`/admin/p/{project_key}/git`, `/admin/p/{project_key}/files`,
`/admin/p/{project_key}/api`, `/admin/p/{project_key}/events`,
`/admin/p/{project_key}/logs`, `/admin/events`, `/admin/logs`, `/admin/search`,
`/admin/p/{project_key}/_partial/content`, `/admin/_partial/project`, and
`/admin/p/{project_key}/_partial/system`.

The generated OpenAPI operation objects for all 20 paths compare equal to the
clean parent. Template rendering and route behavior are covered by the
focused UI/API suite. The only lint allowlist change is a narrow `GRC103`
entry for read-only FastAPI `request.app.state` access in the facade; no
`GRC005` or `GRC012` entry was added.

## Checks

- Focused UI/API suite: `86 passed, 3 skipped`.
- Targeted Ruff on the facade and five owners: PASS.
- Targeted `python3 scripts/grace_lint.py` on the facade and five owners: PASS.
- `python3 -m py_compile` on all six router modules: PASS.
- `git diff --check`: PASS.
- `make test` current checkout: `1584 passed, 2 skipped, 33 failed`.
- Identical `make test` on clean parent: `1584 passed, 2 skipped, 33 failed`,
  with the same 33 pre-existing failures.
- `make lint` current and clean parent: exit 2 before Ruff because the
  repository `.venv` has no `ruff` module; direct targeted Ruff passes.
- `make docs-check` current and clean parent: exit 2 with identical existing
  drift in `docs/openapi.json`, `docs/state-diagram.md` and
  `docs/packet-states.md`.
- Broad GRACE-lint current/parent: both exit 1 with 1088 legacy violations;
  unchanged file/rule sets are equal (401), and changed/new router files add
  zero violations.

User-provided untracked files were preserved. No next task is included.
