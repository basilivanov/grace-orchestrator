# Review: Business Feature Intake + Planning Observability

Status: REVIEWED / READY FOR IMPLEMENTATION WITH REQUIRED GUARDS
Date: 2026-06-12
Scope: Business Feature Intake + feature-level planning observability for GRACE Admin

## Source under review

Reviewed TZ: `Business Feature Intake + Planning Observability for GRACE Admin`.

The TZ defines a four-wave implementation plan:

1. API + DB foundation.
2. FeaturePlanningService extraction.
3. Admin UI observability.
4. Live logs for planning and agent runs.

## Executive summary

The proposed direction is architecturally correct.

The key decision is accepted:

- Business-feature submission must move from direct `/api/architect/plan` usage to a higher-level `/api/features` intake endpoint.
- `/api/architect/plan` should remain only as a compatibility/internal wrapper.
- Feature-level planning must be observable before packets exist.
- Context Builder and Architect must become first-class feature-level stages.
- Existing packet queue / worker / coder / verifier / reviewer / merge pipeline must remain unchanged.
- Legacy Prefect / old runtime must not be expanded or used for this workflow.

Main required correction: avoid introducing a parallel queue or second control plane. All new capability must stay behind FastAPI/OpenAPI and service-layer orchestration.

## Legacy decision

Decision: do not refactor Legacy Prefect / old runtime into this feature.

Required behavior:

- no new imports from legacy runtime;
- no admin UI route depends on legacy;
- no feature intake path depends on legacy;
- no compatibility adapter over legacy for business-feature intake;
- if useful behavior exists only in legacy, reimplement the small idea in a new tested service instead of importing it.

Accepted compatibility exception:

- keep `/api/architect/plan` temporarily;
- convert it into a thin compatibility wrapper over `FeatureIntakeService` / `FeaturePlanningService`;
- do not keep duplicate background planning logic inside `architect.py`.

## Architecture review

### Accepted target architecture

```text
Admin UI / External API
        ↓
POST /api/features
        ↓
FeatureIntakeService
        ↓
FeaturePlanningService
  ├─ Context Builder stage
  ├─ Architect stage
  ├─ save draft plan
  └─ materialize plan on approval
        ↓
existing Feature / Wave / Packet queue
        ↓
existing worker / coder / verifier / reviewer / merge pipeline
```

### Why this is correct

The current problem is not that the Architect endpoint exists. The problem is that the UI is using a low-level planning endpoint as the public business-feature intake flow.

The correct abstraction boundary is:

- `/api/features` = user/business-level intent;
- `FeatureIntakeService` = feature creation and lifecycle start;
- `FeaturePlanningService` = context + architect + draft plan + materialization;
- existing packet execution pipeline = implementation after plan approval.

This keeps the runtime API-first and avoids creating another orchestrator path.

## Wave review

## Wave 1 — API + DB foundation

Verdict: ACCEPTED WITH REQUIRED CLARIFICATIONS.

### Accepted scope

- Add `FeaturePlanningRun` or equivalent feature-level stage table.
- Add `POST /api/features`.
- Add `GET /api/features/{feature_id}/planning`.
- Add `POST /api/features/{feature_id}/approve-plan`.
- Add `POST /api/features/{feature_id}/regenerate-plan` if cheap; otherwise defer after approval path works.
- Keep `/api/architect/plan` as compatibility only.

### Required clarification: feature statuses

The TZ proposes statuses:

```text
NOT_STARTED
PLANNING
PLAN_READY
PLAN_FAILED
QUEUED
ACTIVE
DEGRADED
DONE
ARCHIVED
```

This is acceptable, but implementation must not break current queue behavior.

Required rule:

- `PLANNING`, `PLAN_READY`, and `PLAN_FAILED` are pre-queue statuses.
- `NOT_STARTED` remains the compatibility queued/not-yet-active status if existing claim logic depends on it.
- `QUEUED` may be introduced only if all existing claim/admin logic is updated and covered by tests.

Safer MVP option:

```text
PLANNING → PLAN_READY → NOT_STARTED
PLANNING → PLAN_FAILED
```

Use `QUEUED` only if the current queue code already supports it or the wave explicitly updates claim logic.

### Required clarification: plan storage

`Feature.spec_json.plan_json` is acceptable for MVP, but the schema must be documented.

Minimum expected structure:

```json
{
  "planning": {
    "mode": "draft_plan",
    "latest_run_id": "fpr_...",
    "plan_json": {
      "waves": []
    }
  }
}
```

Do not scatter draft plan state across unrelated fields.

### Required acceptance additions

Add these Wave 1 acceptance checks:

- OpenAPI contains all new endpoints.
- `POST /api/features` does not create placeholder packets in `draft_plan` mode.
- `approve-plan` is rejected unless `Feature.status == PLAN_READY`.
- `approve-plan` is safe against double materialization.
- Existing admin feature list does not crash on a feature with zero waves/packets.

## Wave 2 — FeaturePlanningService

Verdict: ACCEPTED / MOST IMPORTANT WAVE.

This is the architectural core. Wave 2 must remove orchestration from `architect.py`.

### Accepted scope

- Add `FeatureIntakeService`.
- Add `FeaturePlanningService`.
- Move `_warm_context`, `_call_architect_llm`, `_persist_plan`, and background planning orchestration out of router code.
- Persist feature-level stage runs.
- Emit feature-level events.
- Reuse the same service from `/api/architect/plan` compatibility endpoint.

### Required design rule

Router files must stay thin:

```text
parse request → call service → return DTO
```

No long background orchestration closures inside router modules.

### Required event semantics

Feature-level events must have:

```text
entity_type = "feature"
entity_id = feature_id
payload_json.stage
payload_json.status
payload_json.duration_ms
payload_json.executor_id
payload_json.model
payload_json.reason/error
trace_id
```

Do not add fake columns to `Event`; read event details from `payload_json`.

### Required failure behavior

Accepted:

- Context Builder failure may fall back and still allow Architect to run.
- Architect failure must set `PLAN_FAILED`.
- Materialization failure must keep `PLAN_READY` and expose the error.

Required addition:

- background task exceptions must be persisted and visible in API/admin;
- no silent failed background tasks.

### Required acceptance additions

Add these Wave 2 checks:

- `architect.py` no longer contains planning persistence logic.
- compatibility `/api/architect/plan` and new `/api/features` use the same service code path.
- invalid architect JSON is persisted as failed run with stderr/error.
- feature events appear in chronological order.
- materialization creates deterministic wave/packet order.

## Wave 3 — Admin UI observability

Verdict: ACCEPTED WITH SCOPE CONTROL.

The admin UI should show feature planning clearly, but this wave must not become a full plan editor.

### Accepted scope

- New Feature form posts to `/api/features`.
- Show planning stages for `PLANNING`, `PLAN_READY`, `PLAN_FAILED`.
- Show elapsed duration for running stages.
- Show model/executor/error/log links.
- Show plan summary at `PLAN_READY`.
- Add `Approve Plan`, `Regenerate`, and `View JSON`.

### Required UI rule

Planning feature detail must be feature-level, not packet-level.

Use separate planning tabs:

```text
Planning
Plan JSON
Events
Logs
```

Do not overload packet run tabs before packets exist.

### Required scope reduction

Do not build full JSON edit UI in this wave.

MVP is:

- view JSON;
- approve;
- regenerate.

Manual JSON editing can be a later feature.

### Required acceptance additions

Add these Wave 3 checks:

- New Feature form no longer calls `/api/architect/plan`.
- A planning feature with zero packets renders correctly.
- `PLAN_READY` feature renders wave/packet summary from draft plan, not from materialized packets.
- `Approve Plan` updates dashboard after materialization.
- Existing packet detail tabs still work.
- Admin JS syntax is covered by test/guard.

## Wave 4 — Live logs for planning and agent runs

Verdict: ACCEPTED, BUT SHOULD BE IMPLEMENTED AFTER WAVES 1-3 ARE STABLE.

Wave 4 is useful, but it is not required to prove the new intake architecture. It should not block the creation of `/api/features`, planning state, and plan approval.

### Accepted scope

- Add streaming mode to `ProcessSupervisor`.
- Update `AgentRunService` to write stdout/stderr while the process is still running.
- Store planning logs under feature planning run directories.
- Add planning logs endpoint.
- UI polls planning logs.

### Required compatibility rule

Streaming must not change the final `ProcessResult` contract.

The final result must still contain:

- stdout;
- stderr;
- return code/status;
- timeout state;
- duration.

Existing packet run logs must keep working.

### Required security rule

Planning logs endpoint must only read paths from DB records.

Do not allow arbitrary path query parameters.

Tail limit must be capped.

### Required acceptance additions

Add these Wave 4 checks:

- stdout is visible before process completion;
- stderr is visible before process completion;
- timeout still kills process group;
- no orphan process remains after timeout;
- packet logs endpoint remains compatible;
- planning logs endpoint rejects mismatched `feature_id/run_id`.

## Blockers before implementation

None blocking the overall direction.

Implementation may begin with Wave 1.

## Major risks

### Risk 1 — Breaking queue semantics with new `QUEUED` status

If current worker claiming logic expects `NOT_STARTED`, introducing `QUEUED` may make approved features invisible to the queue.

Mitigation:

- either map approved draft plans to `NOT_STARTED` in MVP;
- or update all claim/admin status logic and add regression tests.

### Risk 2 — Duplicate planning implementations

Keeping both `/api/features` and `/api/architect/plan` with separate logic will create drift.

Mitigation:

- extract service first;
- make `/api/architect/plan` a wrapper.

### Risk 3 — Placeholder packets in draft mode

Current architect background flow creates placeholder wave/packet to make UI show something immediately. That is wrong for draft-plan mode.

Mitigation:

- in `draft_plan`, Feature may have zero waves/packets;
- admin must render planning state from `FeaturePlanningRun`, not fake packets.

### Risk 4 — Silent background failures

Background task exceptions may not be visible if not persisted.

Mitigation:

- every planning stage has a DB run row;
- every failure updates status and error;
- admin reads from planning state endpoint.

### Risk 5 — UI grows into plan editor too early

The important feature is observability and approval, not editing.

Mitigation:

- Wave 3 only implements View JSON, Approve, Regenerate.

## Required tests summary

Minimum required test groups:

```text
tests/api/test_features_create_business.py
tests/api/test_feature_planning_api.py
tests/api/test_feature_planning_failures.py
tests/api/test_feature_planning_logs.py

tests/grace_control/services/test_feature_planning_store.py
tests/grace_control/services/test_feature_planning_service.py
tests/grace_control/services/test_process_supervisor_streaming.py
tests/grace_control/services/test_agent_run_service_streaming_logs.py

tests/ui/test_admin_new_feature_intake.py
tests/ui/test_admin_planning_observability.py
tests/ui/test_admin_plan_approval.py
tests/ui/test_admin_live_planning_logs.py
```

Minimum regression tests:

- existing feature list still works;
- existing packet detail still works;
- existing worker claim logic still works;
- existing packet logs still work;
- existing `/api/architect/plan` compatibility behavior still works.

## Recommended implementation order

Use this exact order:

1. Wave 1: DB + API endpoints + tests.
2. Wave 2: extract services and route both new/old endpoints through them.
3. Wave 3: admin UI uses new API and displays planning state.
4. Wave 4: streaming logs.

Do not start Wave 4 before Wave 1-3 are green.

## Final verdict

Approved for implementation.

Required architectural constraints:

- no new legacy dependency;
- no second control plane;
- no duplicate planning path;
- no fake packet placeholder in draft-plan mode;
- feature-level planning state must be persisted;
- approval is the only point where waves/packets are materialized in draft mode;
- existing packet execution pipeline remains unchanged.
