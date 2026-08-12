WEB_ORCH_REPORT: SUBMISSION 07_FINAL_INTEGRATION_GATE
WEB_ORCH_STATUS: DONE
WEB_ORCH_COMMIT: 61b1574ec9b26d9846819698c35cbef6a9b12fc0
WEB_ORCH_CHECKS: PASS

# TZ 07 final integration gate

## Result and scope

Verification was run at `61b1574ec9b26d9846819698c35cbef6a9b12fc0`, with
`origin/main` at the same commit. The commit is the final verification packet
commit on top of the accepted programme head `fdce791711346e1b79229caefb74d663438c925d`.
No source-code integration fix was necessary. This submission adds only this
required report; no source, test, schema, migration, runtime configuration,
state-machine or UI product code was changed.

## Original programme target audit

The function estimate below uses the same source-line estimate as GraceLint:
the joined function source length divided by four, rounded down. The complete
AST audit includes private and async functions.

| Target | Physical lines | Largest function | Estimate | Limit result |
| --- | ---: | --- | ---: | --- |
| `src/grace_control/adapters/packet_executor.py` | 764 | `execute` | 2684 | PASS |
| `src/grace_control/core/plan_compiler.py` | 302 | `compile_plan` | 1349 | PASS |
| `src/grace_control/services/admin_aggregation_service.py` | 388 | `__init__` | 221 | PASS |
| `src/grace_control/services/admin_control_center.py` | 564 | `project_page` | 328 | PASS |
| `src/grace_control/services/feature_planning_service.py` | 416 | `normalize_architect_plan` | 1088 | PASS |
| `src/grace_control/services/merge_service.py` | 668 | `merge_packet` | 2462 | PASS |
| `src/grace_control/api/routers/admin_controls.py` | 673 | `_confirmation_allowed` | 295 | PASS |
| `src/grace_control/core/acceptance_pipeline.py` | 673 | `run` | 1604 | PASS |
| `src/grace_control/services/admin_cross_project_service.py` | 253 | `_request` | 554 | PASS |
| `src/grace_control/services/admin_mutation_service.py` | 190 | `execute` | 791 | PASS |
| `src/grace_control/api/routers/admin_control_center.py` | 615 | `partial_project_query` | 257 | PASS |

All 11 targets are materially below both hard limits: 1000 physical lines and
4000 estimated tokens per function. No target is close to either ceiling and
no size allowlist is used.

## Repository-wide GraceLint size audit

- Coverage: 252 Python files under `src/`.
- Checker path: `grace_control.tools.grace_lint.checker.lint_file`.
- Allowlist path: `.grace/lint_allowlist.yaml`.
- Enabled rules: only `GRC005,GRC012`; function contracts were skipped only
  so the audit isolates the requested rules. `GRC012` is evaluated before the
  private-function contract exemption, so private functions remain checked.
- Result: `SELECTED_RULE_VIOLATIONS=0`.
- `.grace/lint_allowlist.yaml`: no `GRC005` or `GRC012` entries.

The CLI wrapper was also run with the same requested rule selection. Its
existing unconditional module-map pairing check reports one unrelated
`GRC003` at `src/grace_control/api/auth.py`; the checker-level selected-rule
result above is the authoritative GRC005/GRC012 result and remains zero.

## Compatibility and focused suites

Import smoke passed for `PacketExecutionAdapter`/`ExecutionResult`,
`PlanCompiler`/`compile_plan`, `FeaturePlanningService`, `MergeService`,
`AdminAggregationService`, `AdminControlCenterService`,
`AdminCrossProjectService`, `AdminMutationService`,
`normalize_mutation_result`, `UNKNOWN_OUTCOME_MESSAGE`, `AcceptancePipeline`,
`run_acceptance_pipeline`, `run_acceptance_stage_replay`,
`admin_controls.router`, `legacy_admin_action`,
`admin_control_center.router`, `_service`, `_render`, and
`_raise_project_not_found`: `IMPORT_SMOKE=PASS`.

Focused results by domain:

- Packet executor, acceptance and PlanCompiler: `267 passed, 1 skipped`.
- Admin JSON, Control Center API/router, OpenAPI and UI: `82 passed, 3 skipped`.
- Merge pipeline: `12 passed`.
- Feature-planning service/store: `12 passed, 11 failed` in both current and
  clean-parent checkouts. Every failure node is identical; the failure is the
  known environment `PermissionError` while creating `/tmp/grace_planning_logs`.
- Combined focused command: `373 passed, 4 skipped, 11 failed`; the 11
  planning failures are exactly reproduced by the clean parent.

No focused packet, acceptance, merge, admin, Control Center, route or UI
regression was found.

## HTTP, route and OpenAPI compatibility

Admin JSON route inventory contains exactly 10 registrations, with no
duplicates:

- `GET /api/admin-hub/projects/{project_key}/controls` → `project_controls`;
- `POST /api/admin-hub/projects/{project_key}/control` and
  `POST /api/admin-hub/projects/{project_key}/controls` → `project_control`;
- `POST /api/admin-hub/projects/{project_key}/api-control` and
  `POST /api/admin-hub/projects/{project_key}/openapi-control` →
  `project_openapi_control`;
- `GET /api/admin-hub/projects/{project_key}/maintenance` →
  `project_maintenance`;
- `POST /api/admin/control/action` → `local_control_action`;
- `GET /api/admin/maintenance/snapshot` → `local_maintenance_snapshot`;
- `POST /api/admin/maintenance/cleanup` → `local_maintenance_cleanup`;
- `POST /api/admin/control/openapi` → `local_openapi_control`.

Control Center route inventory contains exactly 20 registrations, with no
duplicates:

- `GET /admin` → `admin_landing`;
- `GET /admin/projects` → `admin_projects`;
- `GET /admin/_partial/projects` → `partial_projects`;
- `GET /admin/p/{project_key}` → `project_overview`;
- `GET /admin/p/{project_key}/feature/{feature_id}` → `project_feature`;
- `GET /admin/p/{project_key}/wave/{wave_id}` → `project_wave`;
- `GET /admin/p/{project_key}/packet/{packet_id}` → `project_packet`;
- `GET /admin/p/{project_key}/system` → `project_system`;
- `GET /admin/p/{project_key}/maintenance` → `project_maintenance`;
- `GET /admin/p/{project_key}/git` → `project_git`;
- `GET /admin/p/{project_key}/files` → `project_files`;
- `GET /admin/p/{project_key}/api` → `project_api`;
- `GET /admin/p/{project_key}/events` → `project_events`;
- `GET /admin/p/{project_key}/logs` → `project_logs`;
- `GET /admin/events` → `admin_events`;
- `GET /admin/logs` → `admin_logs`;
- `GET /admin/search` → `admin_search`;
- `GET /admin/p/{project_key}/_partial/content` → `partial_project`;
- `GET /admin/_partial/project` → `partial_project_query`;
- `GET /admin/p/{project_key}/_partial/system` → `partial_system`.

AST and runtime comparisons against the clean parent show identical route
sets, signatures, defaults, Query constraints and aliases. The canonical
`app.openapi()` semantic representation has 168 paths and SHA-256
`7d847ff6a70c6ea300f4366ef1cb757dca180dce47ade83c2d7b8bc8c890e2c8` in both
current and parent checkouts. Template/rendering integration is green in the
focused Admin/API/UI suite.

The programme source diff contains 62 Python modules. Apart from source,
tests and exchange documentation, the only programme metadata path is the
existing `.grace/lint_allowlist.yaml`; there are no DB/Alembic migrations,
schema changes, runtime configuration changes or state-machine changes. The
final verification commit itself changes only the packet inbox document.

## Broad verification and clean-parent comparison

The commands were run in the requested order. Every non-zero result was
re-run with the exact same command and shared Python environment in a clean
checkout of `HEAD^` (`fdce791711346e1b79229caefb74d663438c925d`).

| Command | Current checkout | Clean parent | Comparison |
| --- | --- | --- | --- |
| `make lint` | exit 2: repository `.venv` has no `ruff` module | same exit 2 and message | exact environment failure |
| `make test` | exit 2: `1584 passed, 2 skipped, 33 failed` | same exit 2 and counts | identical 33 failure nodes and causes |
| `make docs-check` | exit 2: drift in `docs/openapi.json`, `docs/state-diagram.md`, `docs/packet-states.md` | same exit 2 and same three files | identical generated-doc baseline drift |
| `make ci` | exit 2 at the `make test` gate with the same 1584/2/33 result | same exit 2 at the same gate | identical failure node set/output cause |
| `git diff --check` | PASS, exit 0 | not needed for final report | no whitespace errors |

The full 33-test failure node set and failure causes are identical between
current and parent; only nondeterministic timestamps, temporary paths,
generated IDs and warning counts vary in output. No failure is attributable to
the final integration packet or to the accepted refactor programme.

## Targeted static checks

- Targeted Ruff over all 62 programme-touched Python modules: current and
  parent both exit 1 with 91 existing findings; output SHA-256 is identical in
  both (`f8a522f8d31792d84ee95d840a9f1d8f3588da247f05d99036c31b34bc9f9667`).
  The final router target subset itself passes; the full-programme non-zero
  result is unchanged baseline lint debt.
- `python3 -m py_compile` over all 62 programme-touched modules: PASS in both
  current and parent.
- `git diff --check`: PASS.

## Remaining baseline debt

The remaining non-zero checks are pre-existing and exactly reproduced by the
clean parent: missing Ruff in the repository virtualenv, 33 full-suite test
failures (including the 11 planning-log permission failures), three generated
documentation drift files, 91 targeted-Ruff findings in the broader
programme-touched set, and the CLI wrapper's unrelated unconditional GRC003
report. None is a new integration regression, and no baseline debt was
modified or hidden.

No next task was started or proposed.
