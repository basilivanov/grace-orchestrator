# TZ 07_FINAL_INTEGRATION_GATE — Grace Local Adopt final integration

Status: READY FOR CODER
Source programme: `TZ_GRACE_LOCAL_ADOPT_REFACTOR_MASTER.md` Wave 3
Source index: `TZ_GRACE_LOCAL_ADOPT_REFACTOR_00_INDEX.md` Final integration gate
Dependencies: all named structural packets 01–06 accepted, including `06_ADMIN_CONTROL_CENTER_ROUTER`

## Coder protocol

You are the Coder for this named TZ. Read and execute **only this file**. Do not invent another task.

Before work:

1. Work in `/opt/grace-orchestrator`.
2. Fast-forward cleanly to `origin/main`; no merge commit.
3. Treat this as a verification/integration packet, not a new refactor wave.

After verification:

1. Commit/push only genuinely necessary, narrowly attributable integration fixes if any. Do not clean unrelated baseline debt.
2. Create only `docs/work/agent_exchange/outbox/07_FINAL_INTEGRATION_GATE_SUBMISSION.md`.
3. Do not create further task/review/state/lock/orchestration metadata.

Submission header must be exactly:

```text
WEB_ORCH_REPORT: SUBMISSION 07_FINAL_INTEGRATION_GATE
WEB_ORCH_STATUS: DONE
WEB_ORCH_COMMIT: <verification-or-fix-sha>
WEB_ORCH_CHECKS: PASS
```

If no code fix is needed, the reported commit may be the current accepted programme head; the submission commit itself is not the implementation SHA.

## Goal

Prove the Local Adopt structural refactor programme is integrated without public-behaviour drift and that the hard structural limits are satisfied repository-wide using the same semantics as GraceLint.

Do **not** start another architectural decomposition. This packet owns verification and only minimal integration repairs proven necessary by the checks below.

## Required target audit

Report physical line counts and largest `len(source)//4` function estimate for every original programme target:

Hard-limit set:

- `src/grace_control/adapters/packet_executor.py`
- `src/grace_control/core/plan_compiler.py`
- `src/grace_control/services/admin_aggregation_service.py`
- `src/grace_control/services/admin_control_center.py`
- `src/grace_control/services/feature_planning_service.py`
- `src/grace_control/services/merge_service.py`

Near-limit set:

- `src/grace_control/api/routers/admin_controls.py`
- `src/grace_control/core/acceptance_pipeline.py`
- `src/grace_control/services/admin_cross_project_service.py`
- `src/grace_control/services/admin_mutation_service.py`
- `src/grace_control/api/routers/admin_control_center.py`

Every target must be <=1000 physical lines and every function/async function, including private ones, <=4000 estimated tokens. Preferred programme headroom should remain materially below the ceilings; flag any target that has regressed close to the hard limit since its packet ACCEPT.

## Repository-wide hard-limit audit

Run GraceLint with **only** `GRC005` and `GRC012` enabled across all Python source covered by the checker, using the same checker/allowlist loading path as normal lint.

Acceptance requires:

- zero remaining `GRC005` violations;
- zero remaining `GRC012` violations, including private functions;
- no `GRC005` or `GRC012` entries anywhere in `.grace/lint_allowlist.yaml`;
- GRC012 still checks private functions while private functions remain exempt from public FUNCTION_CONTRACT requirements.

If any hard-size violation remains, do not hide it, compress it, or add an allowlist. Fix only when it is clearly within the bounded programme scope; otherwise report the concrete blocker for Architect review.

## Compatibility smoke

Verify the preserved public/import surfaces at minimum:

- packet executor facade/imports;
- `PlanCompiler` / `compile_plan`;
- feature-planning facade;
- merge-service facade;
- `AdminAggregationService`;
- `AdminControlCenterService`;
- `AdminCrossProjectService`;
- `AdminMutationService`, `normalize_mutation_result`, `UNKNOWN_OUTCOME_MESSAGE`;
- `AcceptancePipeline`, `run_acceptance_pipeline`, `run_acceptance_stage_replay`;
- `admin_controls.router` and `legacy_admin_action`;
- `admin_control_center.router`, `_service`, `_render`, `_raise_project_not_found` used by UI control routes.

Do not migrate callers in this packet unless a real broken compatibility seam is demonstrated.

## HTTP / OpenAPI / UI compatibility

Run the existing route/OpenAPI/Control Center integration coverage and prove no programme-caused route drift.

At minimum verify:

- Admin JSON route set and aliases remain registered exactly once;
- Control Center 20 HTML/HTMX routes remain registered exactly once with the same signatures/defaults/Query constraints;
- generated OpenAPI semantic content remains unchanged from the accepted programme baseline (the previously established semantic hash was `7d847ff6a70c6ea300f4366ef1cb757dca180dce47ade83c2d7b8bc8c890e2c8`, unless the repository's canonical generator now proves an equivalent normalized semantic representation);
- no DB migration/schema/config/state-machine change was introduced by this programme;
- template/rendering integration remains green.

## Full verification

Run, in this order where practical:

```bash
make lint
make test
make docs-check
make ci
git diff --check
```

Also run:

- targeted Ruff for all programme-touched source modules when available;
- `py_compile` for all programme-touched/new Python modules;
- repository-wide `GRC005 GRC012` audit;
- focused compatibility/import smoke;
- focused acceptance, merge, planning, packet-execution and admin/Control Center suites;
- route/OpenAPI semantic comparison.

For any required broad command that is non-zero, compare it against a **clean parent checkout of the final verification head's parent** with the exact same command/environment and report exact failure-node/output equivalence. Existing environment/baseline failures established by earlier packets may be reported as baseline only when exact equivalence is proven; any new or programme-related failure is a blocker. Do not broaden this packet into fixing unrelated historical test/environment debt merely to make counts green.

Known historical observations from prior accepted packets are not assumptions: re-run them. These have included a repository `.venv` without Ruff, 33 pre-existing test failures, and generated-doc drift. The final packet must freshly prove whether they still exist and whether current/clean-parent results are exactly equivalent.

## No-regression / no-evasion rules

- No test weakening, skip/xfail expansion or changed expected behaviour to fit the refactor.
- No `GRC005`/`GRC012` allowlist entries.
- No line compression or identifier obfuscation to satisfy lint.
- No unrelated dependency/config/schema/UI/product changes.
- No new refactor target outside the original programme list unless Architect issues another named TZ.

## Submission content

Report concisely but completely:

1. verification/fix SHA and whether code changed;
2. table of all 11 original targets with physical lines and largest function token estimate;
3. repo-wide `GRC005/GRC012` audit result and confirmation of no size allowlist entries;
4. focused suite results by domain;
5. import/facade compatibility smoke result;
6. Admin JSON and Control Center route inventories / OpenAPI semantic result;
7. exact `make lint`, `make test`, `make docs-check`, `make ci`, `git diff --check` results;
8. exact clean-parent comparison for every non-zero broad command;
9. targeted Ruff/py_compile results;
10. any remaining baseline debt, explicitly separated from programme regressions;
11. confirmation that no next task was started.

Do not claim final programme completion if a hard-size violation, public-surface regression, new test failure, route/OpenAPI drift, or unproven broad-command difference remains.