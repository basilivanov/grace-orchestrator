# Review: Business Feature Intake + Planning Pipeline Waves 1–4

Status: REVIEWED / CONDITIONAL PASS
Date: 2026-06-12
Reviewed commit: `d941190` — `feat: business feature intake + planning pipeline (Waves 1-4)`
Repository: `basilivanov/grace-orchestrator`

## Review basis

This review is based on:

1. the approved TZ: Business Feature Intake + Planning Observability for GRACE Admin;
2. the runner summary for commit `d941190`;
3. the reported green test state:
   - 14 new tests;
   - 600 backend tests green;
   - 756 frontend tests green;
4. the previously accepted architecture review in `docs/work/REVIEW_BUSINESS_FEATURE_INTAKE_PLANNING_OBSERVABILITY.md`.

Important verification note:

The short SHA `d941190` did not resolve through the GitHub connector at review time, so this report treats code/test status as **reported evidence**, not independently re-run evidence. A follow-up verifier should resolve the full commit SHA locally or after GitHub index refresh and attach exact command output.

## Executive verdict

Conditional pass.

The implementation summary matches the intended four-wave architecture:

- Wave 1: DB/API foundation for `Feature` + `FeaturePlanningRun`.
- Wave 2: `FeatureIntakeService` + `FeaturePlanningService`.
- Wave 3: Admin UI path for feature creation and planning detail.
- Wave 4: planning run logs endpoint.
- Feature-level events added.
- New API surface added.
- Reported tests are green.

No blocker is visible from the supplied implementation summary.

However, there are two follow-up verification points before declaring full production acceptance:

1. confirm that Wave 4 implements **live log streaming/write-during-run**, not only a read endpoint;
2. confirm that `/api/architect/plan` is now a compatibility wrapper or deprecated path, not a duplicate planning implementation.

## Scope reviewed

Reported implementation:

| Area | Reported result | Review |
| --- | --- | --- |
| Wave 1 | Feature + FeaturePlanningRun models, Pydantic schemas, migration `0017` | Accepted, requires migration smoke verification |
| Wave 2 | FeatureIntakeService + FeaturePlanningService | Accepted, core architecture direction correct |
| Wave 3 | Admin UI `/admin/features/` list/create/planning detail | Accepted, must not bypass `/api/features` |
| Wave 4 | `GET /api/features/{id}/planning/{run_id}/logs` | Partially accepted; verify actual live streaming separately |
| Events | 10 feature-level events | Accepted |
| Endpoints | Feature create/planning/approve/regenerate/logs + admin features | Accepted |
| Tests | 14 new, 600 backend / 756 frontend green | Accepted as reported evidence |

## Accepted endpoints

The following endpoint set matches the TZ:

```text
POST /api/features
GET /api/features/{id}/planning
POST /api/features/{id}/approve-plan
POST /api/features/{id}/regenerate-plan
GET /api/features/{id}/planning/{run_id}/logs
GET /api/admin/features
```

This is the correct public API direction.

`POST /api/features` must be the primary business-feature intake endpoint.

`/api/architect/plan` must not remain the Admin UI entrypoint.

## Architecture acceptance

Accepted target architecture:

```text
Admin UI / External API
        ↓
POST /api/features
        ↓
FeatureIntakeService
        ↓
FeaturePlanningService
  ├─ Context Builder
  ├─ Architect
  ├─ Draft Plan
  ├─ Approve / Regenerate
  └─ Materialize Waves/Packets
        ↓
Existing Feature/Wave/Packet queue
        ↓
Existing worker/coder/verifier/reviewer/merge pipeline
```

This keeps GRACE API-first and avoids a second control plane.

## Legacy decision

Legacy Prefect / old runtime remains out of scope.

Accepted decision:

```text
Do not call Legacy.
Do not refactor Legacy for this workflow.
Do not add Admin UI dependency on Legacy.
Do not create a compatibility adapter over Legacy.
```

The only compatibility exception remains `/api/architect/plan`, and only if it is a thin wrapper over the new service path.

## Wave-by-wave review

## Wave 1 — DB/API foundation

Verdict: PASS AS REPORTED.

Accepted items:

- `FeaturePlanningRun` model exists.
- Migration `0017` exists.
- Pydantic schemas exist.
- Feature create/planning/approve/regenerate endpoints exist.

Required verifier checks:

```bash
alembic upgrade head
pytest tests/api/test_features_create_business.py -q
pytest tests/api/test_feature_planning_api.py -q
```

Required behavior:

- `POST /api/features` creates a feature in planning lifecycle.
- `GET /api/features/{id}/planning` returns planning state and planning runs.
- `approve-plan` is rejected before a valid plan is ready.
- `approve-plan` materializes waves/packets exactly once.
- Existing queue claiming still sees approved features.

Watch point:

If a new `QUEUED` status was introduced, verify worker claim logic supports it. If not, approved plans should move to existing `NOT_STARTED` semantics.

## Wave 2 — FeatureIntakeService + FeaturePlanningService

Verdict: PASS AS REPORTED.

Accepted items:

- business feature intake was moved into service layer;
- planning orchestration moved into `FeaturePlanningService`;
- context, architect, approve, regenerate are handled by services;
- feature-level events are emitted.

Required verifier checks:

```bash
pytest tests/grace_control/services/test_feature_planning_service.py -q
pytest tests/api/test_feature_planning_failures.py -q
```

Required behavior:

- router remains thin;
- no duplicate planning logic remains in `architect.py`;
- background failures are persisted, not silent;
- architect invalid JSON creates visible failure state;
- context failure either falls back explicitly or fails explicitly;
- regenerate preserves history or clearly marks superseded runs.

Watch point:

The compatibility `/api/architect/plan` path must call the same services. If it still has its own `_warm_context`, `_call_architect_llm`, `_persist_plan`, or private background task, that is architectural drift and must be fixed.

## Wave 3 — Admin UI observability

Verdict: PASS AS REPORTED.

Accepted items:

- Admin UI has feature list/create/planning detail;
- New Feature flow should now target `/api/features`;
- planning detail exists before packets are materialized.

Required verifier checks:

```bash
pytest tests/ui/test_admin_new_feature_intake.py -q
pytest tests/ui/test_admin_planning_observability.py -q
pytest tests/ui/test_admin_plan_approval.py -q
```

Required behavior:

- Admin UI does not call `/api/architect/plan` for new business features.
- Planning feature with zero packets renders correctly.
- Planning stages show useful state: pending/running/done/failed.
- PLAN_READY shows draft plan summary before materialization.
- Approve Plan calls `/api/features/{id}/approve-plan`.
- Existing packet detail remains unchanged.

Watch point:

Do not let this turn into a full plan editor yet. MVP should remain: view JSON, approve, regenerate.

## Wave 4 — Planning logs endpoint

Verdict: PARTIAL PASS / NEEDS VERIFIER CONFIRMATION.

Reported item:

```text
GET /api/features/{id}/planning/{run_id}/logs
```

This endpoint is necessary and accepted.

But the original Wave 4 requirement was stronger:

- logs should be visible while Context Builder / Architect / Coder are still running;
- stdout/stderr must be written incrementally during process execution;
- `ProcessSupervisor` / `AgentRunService` should support write-during-run behavior;
- final `ProcessResult` contract must remain unchanged.

Required verifier checks:

```bash
pytest tests/grace_control/services/test_process_supervisor_streaming.py -q
pytest tests/grace_control/services/test_agent_run_service_streaming_logs.py -q
pytest tests/api/test_feature_planning_logs.py -q
pytest tests/ui/test_admin_live_planning_logs.py -q
```

If only the read endpoint was added and logs are still written after process completion, Wave 4 should be marked incomplete and followed by a small fix wave.

Required behavior:

- stdout is visible before process completion;
- stderr is visible before process completion;
- timeout still kills process group;
- no orphan process after timeout;
- logs endpoint reads only DB-backed paths;
- logs endpoint rejects mismatched `feature_id/run_id`.

## Event review

Reported event names:

```text
feature_submitted
planning_started
context_builder_started
context_builder_completed
context_builder_failed
architect_started
architect_completed
architect_failed
plan_ready
plan_materialized
```

Verdict: ACCEPTED.

Required event shape:

```text
entity_type = feature
entity_id = feature_id
payload_json.stage
payload_json.status
payload_json.duration_ms
payload_json.executor_id
payload_json.model
payload_json.reason/error
trace_id
```

Do not add fake direct columns to `Event` for fields that belong in `payload_json`.

## Test evidence review

Reported:

```text
14 new tests
600 backend tests green
756 frontend tests green
```

Verdict: ACCEPTED AS REPORTED.

Required follow-up evidence to attach in a later verification report:

```bash
git rev-parse HEAD
pytest -q
npm test -- --runInBand
# or the exact frontend command used by the repo
```

The report should record:

```text
tested_code_sha=<full SHA of d941190>
backend_tests=600 green
frontend_tests=756 green
```

## Risks

## Risk 1 — GitHub SHA not independently resolved during review

The short SHA `d941190` did not resolve via the GitHub connector during this review.

Impact:

- this review cannot claim line-level source verification;
- test status is accepted as runner-reported evidence.

Mitigation:

- run a local verifier report with full SHA;
- attach exact test logs or command output.

## Risk 2 — Wave 4 may be endpoint-only

The runner summary mentions the logs endpoint, but not necessarily streaming process output.

Impact:

- Admin may show logs only after process completion;
- original observability requirement would be only partially met.

Mitigation:

- verify `ProcessSupervisor` / `AgentRunService` streaming tests;
- add a small W4-fix if missing.

## Risk 3 — duplicate `/api/architect/plan` path

If old architect background logic remains separate, behavior may drift.

Impact:

- two planning paths;
- inconsistent plan lifecycle;
- hard-to-debug admin behavior.

Mitigation:

- compatibility endpoint must call the same services;
- add regression test that Admin UI does not call `/api/architect/plan`.

## Risk 4 — queue status mismatch

If approved plans use a new status not consumed by worker claim logic, features may never run.

Mitigation:

- either use `NOT_STARTED` after approval;
- or update queue claim logic and tests.

## Required follow-up verifier checklist

Before final production acceptance, run:

```bash
git rev-parse HEAD
git log --oneline -5
pytest -q
# frontend test command used by project
```

Then manually verify:

```text
1. Admin New Feature posts to /api/features.
2. /api/architect/plan is not used by Admin UI.
3. Feature appears as PLANNING before packets exist.
4. Context Builder and Architect stages are visible separately.
5. PLAN_READY shows draft plan summary.
6. Approve materializes waves/packets once.
7. Approved feature enters existing worker queue.
8. Planning logs endpoint rejects invalid/mismatched run IDs.
9. Logs are visible while a planning process is still running.
10. Legacy runtime is not imported or called.
```

## Final decision

Conditional pass.

The implementation can be treated as accepted for architectural direction and reported test health.

Full acceptance requires one additional verifier pass that confirms:

1. the full SHA for `d941190`;
2. no duplicate architect planning path;
3. live streaming logs, not only completed log reads;
4. queue claim compatibility after plan approval.
