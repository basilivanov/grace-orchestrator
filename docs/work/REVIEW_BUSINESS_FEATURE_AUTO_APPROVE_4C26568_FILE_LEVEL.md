# File-level review: Business Feature Auto-Approve Mode

Status: REVIEWED / CONDITIONAL PASS — DEFAULT ADMIN FLOW ACCEPTED, EDGE CLEANUP REMAINS
Date: 2026-06-12
Reviewed commit: `4c26568`
Base: `cb2cea8`
Scope: file-level review of `cb2cea8..4c26568`
TZ: `docs/work/TZ_BUSINESS_FEATURE_AUTO_APPROVE_MODE.md`

## Diff scope

GitHub compare for `cb2cea8..4c26568` shows one implementation commit touching:

```text
src/grace_control/api/routers/architect.py
src/grace_control/api/routers/features.py
src/grace_control/services/feature_intake_service.py
src/grace_control/services/feature_planning_service.py
src/grace_control/ui/static/admin.js
tests/api/test_architect_background.py
tests/api/test_features_api.py
tests/grace_control/services/test_feature_planning_store.py
```

Reported local evidence from implementer:

```text
56 tests pass
```

This review accepts the reported test result as local evidence and verifies the source/test changes at file level.

## Executive verdict

Conditional pass.

The main business requirement is implemented:

```text
Admin → New Feature → Auto-approve checked by default → Context Builder → Architect → approve_plan() → queued packets
```

Manual mode is also implemented for the main `/api/features` background path:

```text
Admin → New Feature → Auto-approve unchecked → Context Builder → Architect → PLAN_READY, no packets materialized
```

So the core product decision is accepted.

Remaining issues are edge/UI cleanup, not blockers for the default workflow:

1. `/api/architect/plan` synchronous business-text path still approves unconditionally and does not honor `approval_mode="manual"`.
2. `GET /api/features/{id}` does not expose `approval_mode` as a top-level field, only inside `spec_json`.
3. Admin dashboard feature card does not show an AUTO/MANUAL approval badge yet.

## Accepted implementation

## 1. API request model has explicit approval mode

`FeatureCreateRequest` now includes:

```python
approval_mode: Literal["auto", "manual"] = "auto"
```

This satisfies the API contract and gives Pydantic 422 behavior for invalid values.

Verdict: PASS.

## 2. List endpoint exposes approval mode

`GET /api/features/` now emits:

```python
"approval_mode": f.spec_json.get("approval_mode", "auto")
```

Verdict: PASS.

## 3. Feature intake persists approval mode

`FeatureIntakeService.create_feature()` now accepts `approval_mode`, persists it in `spec_json`, includes it in the `feature_submitted` event payload, and returns it in the create result.

Verdict: PASS.

## 4. Main `/api/features` background path auto-approves

For `draft_plan`, the router captures `request.approval_mode`; after context builder + architect finish, it calls `approve_plan(feature_id)` when mode is `auto`.

Manual mode skips that call, so the feature remains `PLAN_READY`.

Verdict: PASS.

## 5. Regenerate preserves approval mode

`regenerate-plan` reads `approval_mode` from the feature spec and uses it after regenerated planning succeeds.

Auto mode auto-approves; manual mode stays at `PLAN_READY`.

Verdict: PASS.

## 6. Event includes approval mode

`FeaturePlanningService.approve_plan()` now includes `approval_mode` in the `plan_materialized` event payload.

Verdict: PASS.

## 7. Admin New Feature checkbox exists and defaults to auto

Admin New Feature form now includes a checked checkbox:

```text
Auto-approve architect plan
```

Submit payload sends:

```json
"approval_mode": "auto" | "manual"
```

Verdict: PASS.

## 8. Tests cover the main behavior

Added/updated tests cover:

- default approval mode is auto;
- manual mode persists;
- invalid approval mode returns 422;
- auto mode materializes to queued;
- manual mode leaves `PLAN_READY` and does not materialize packets;
- list endpoint exposes approval mode;
- service persist/default behavior;
- event payload includes approval mode;
- architect background tests use manual mode to keep old expected `PLAN_READY` behavior.

Verdict: PASS.

## Remaining issues

## P1-1 — `/api/architect/plan` synchronous business-text path ignores manual mode

In `architect.py`, background business-text mode honors `_approval_mode` and only auto-approves when `_approval_mode == "auto"`.

But synchronous business-text mode still runs:

```python
plan = await planning.run_architect(...)
approval = planning.approve_plan(feature_id)
```

unconditionally.

Impact:

- default Admin flow is not affected;
- normal `/api/features` flow is not affected;
- async `/api/architect/plan` flow is not affected;
- but a compatibility caller using `/api/architect/plan` with `background=false` and `approval_mode="manual"` will still get materialized/queued.

Required cleanup:

- if `_approval_mode == "manual"`, return the generated plan/context with feature left in `PLAN_READY`;
- only call `approve_plan()` for `_approval_mode == "auto"`;
- add one test for `/api/architect/plan` sync manual mode.

## P1-2 — single feature endpoint does not expose top-level approval_mode

`GET /api/features/` exposes `approval_mode`, but `GET /api/features/{feature_id}` currently returns `spec_json` and does not expose `approval_mode` as a sibling field.

Impact:

- data is present inside `spec_json`;
- but the TZ asked list/get endpoints to expose it similarly to mode/origin.

Required cleanup:

- add `approval_mode` top-level in `get_feature()` response;
- optionally add `mode` and `origin` top-level for symmetry;
- add a small API test.

## P1-3 — dashboard card does not show approval mode badge

Admin New Feature form has the checkbox, but the dashboard feature card does not show compact:

```text
AUTO-APPROVE
MANUAL APPROVAL
```

Impact:

- submit behavior works;
- operator visibility is weaker than TZ requested.

Required cleanup:

- use `f.approval_mode` from list endpoint in `renderDashboard()`;
- show a small badge in `feat-sub`.

## Non-blocking notes

## Broad catch can turn auto-approve failure into PLAN_FAILED

The `/api/features` background task wraps planning + auto-approval in one try/except. If Architect succeeds but `approve_plan()` fails for a materialization-specific reason, feature is set to `PLAN_FAILED`.

This is acceptable for now because the status signals the feature did not reach queue, but a future refinement could distinguish:

```text
PLAN_READY + AUTO_APPROVE_FAILED
```

Not required for this slice.

## Final decision

```text
CONDITIONAL PASS
```

Accepted as implemented for the main Admin New Feature auto-approve default workflow.

Recommended small follow-up patch:

1. honor `approval_mode="manual"` in `/api/architect/plan` synchronous business-text path;
2. expose `approval_mode` top-level in `GET /api/features/{id}`;
3. show AUTO/MANUAL badge in dashboard feature cards;
4. add tests for the three items above.
