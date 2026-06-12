# TZ: Business Feature Auto-Approve / Manual-Approve Mode

Status: READY FOR IMPLEMENTATION
Date: 2026-06-12
Related accepted slice: Business Feature Intake + Planning Observability
Default behavior change: auto-approve by default

## Business decision

When a user submits a new business feature from Admin → New Feature, GRACE should not require a manual approval step by default.

Default behavior:

```text
New Feature → Context Builder → Architect → auto-approve plan → materialize waves/packets → existing queue/worker pipeline
```

Manual approval remains available as an optional mode:

```text
New Feature → Context Builder → Architect → PLAN_READY → human approves → materialize waves/packets
```

Rationale:

- User wants a faster AI-driven workflow.
- Architect should decide the plan and move the work forward automatically.
- If the result is bad, the user will correct/rework later.
- Manual approval should exist for risky/special cases, but not as the default.

## Required product behavior

### 1. Admin UI

In Admin → New Feature form, add an approval mode control.

Required UI:

- Checkbox label: `Auto-approve architect plan`
- Default: checked
- Help text: `If enabled, GRACE will queue the generated plan automatically after Architect finishes.`

Behavior:

- Checked → submit with `approval_mode = "auto"`
- Unchecked → submit with `approval_mode = "manual"`

The user should be able to submit a feature without thinking about approval mode. Default must be auto.

### 2. API contract

Extend `POST /api/features/` request model.

Current:

```python
mode: Literal["draft_plan", "auto_queue"] = "draft_plan"
```

Add:

```python
approval_mode: Literal["auto", "manual"] = "auto"
```

Expected semantics:

- `mode` keeps its existing meaning for compatibility.
- `approval_mode` controls what happens after Architect reaches a valid plan.
- For normal Admin New Feature submit, use `mode="draft_plan"` and `approval_mode="auto"` by default.

Do not remove existing `auto_queue` yet. Treat it as compatibility/legacy shortcut.

### 3. Feature spec persistence

Persist `approval_mode` in `Feature.spec_json`.

Expected persisted shape:

```json
{
  "title": "...",
  "description": "...",
  "target_repo_root": "...",
  "mode": "draft_plan",
  "approval_mode": "auto",
  "origin": "business"
}
```

List/get endpoints should expose `approval_mode` similarly to `mode` and `origin`.

### 4. Background planning auto-approval

After `run_architect()` finishes successfully and feature becomes `PLAN_READY`:

- if `approval_mode == "auto"`, call `approve_plan(feature_id)` automatically;
- if `approval_mode == "manual"`, leave feature in `PLAN_READY`;
- if Architect fails, keep existing `PLAN_FAILED` behavior and do not approve.

Important:

- Auto-approval must happen only after successful `PLAN_READY`.
- Auto-approval must use the same `FeaturePlanningService.approve_plan()` path as manual approval.
- Auto-approval must produce the same materialization result as manual approval: first wave READY, later waves DRAFT.
- Auto-approval must emit an event, e.g. `plan_auto_approved` or include `approval_mode: auto` in `plan_materialized` payload.

### 5. Regenerate behavior

For `POST /api/features/{feature_id}/regenerate-plan`:

- preserve the feature's existing `approval_mode`;
- after regenerated Architect plan succeeds:
  - if `approval_mode == "auto"`, auto-approve;
  - if `approval_mode == "manual"`, leave `PLAN_READY`.

### 6. Compatibility wrapper `/api/architect/plan`

For compatibility path:

- if request contains `approval_mode`, pass it through;
- otherwise default to `auto` for business text;
- predefined waves may continue to materialize immediately because the caller already supplied the plan.

### 7. Admin dashboard display

Feature cards should show approval mode in a compact way:

```text
AUTO-APPROVE
```

or

```text
MANUAL APPROVAL
```

For manual mode, when status is `PLAN_READY`, show/keep an approve action.

For auto mode, once Architect completes, the feature should move to queued/materialized state without the user clicking approve.

## Non-goals

Do not implement complex policy gates yet:

- no risk-based auto/manual switching;
- no approval roles/permissions;
- no multi-step approval;
- no approval comments;
- no UI plan diff editor.

This is only a binary mode:

```text
auto | manual
```

## Required tests

### API tests

1. `POST /api/features/` without `approval_mode` defaults to auto.
2. `POST /api/features/` with `approval_mode="manual"` persists manual mode.
3. Invalid `approval_mode` returns 422.
4. Auto mode: after background planning succeeds, feature is materialized/queued automatically.
5. Manual mode: after background planning succeeds, feature remains `PLAN_READY` and no packets are materialized until approve endpoint is called.
6. Architect failure does not auto-approve.
7. Regenerate preserves approval mode and auto-approves only for auto mode.

### Service tests

1. `FeatureIntakeService.create_feature()` persists `approval_mode`.
2. Auto-approve path calls `approve_plan()` exactly once.
3. Manual path does not call `approve_plan()`.
4. Auto-approved materialization preserves first wave READY / later waves DRAFT.

### UI tests / static tests

1. Admin New Feature form includes an `Auto-approve architect plan` checkbox.
2. Checkbox is checked by default.
3. Submit payload includes `approval_mode="auto"` when checked.
4. Submit payload includes `approval_mode="manual"` when unchecked.
5. No Admin New Feature submit path uses `/api/architect/plan`.

## Acceptance criteria

Implementation is accepted when:

- New Feature default path queues work automatically after Architect succeeds.
- User can uncheck auto-approve and get the old manual `PLAN_READY → approve` behavior.
- Backend state is explicit via `approval_mode`.
- Existing manual approve endpoint still works.
- Existing `/api/architect/plan` compatibility wrapper still works.
- Tests cover auto/manual behavior and UI payload.

## Expected final behavior

Default user flow:

```text
Admin → New Feature → submit → Architect thinks → plan auto-approved → packets enter queue
```

Manual user flow:

```text
Admin → New Feature → uncheck Auto-approve → submit → Architect thinks → PLAN_READY → user approves later
```
