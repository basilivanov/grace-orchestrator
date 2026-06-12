# File-level review: Business Feature Intake follow-up

Status: REVIEWED / FAIL — CORE BLOCKERS REMAIN
Date: 2026-06-12
Reviewed commit: `74ce713`
Base: `c47e3e4`
Scope: file-level review of `c47e3e4..74ce713`

## Diff scope

GitHub compare for `c47e3e4..74ce713` shows one commit and these changed files:

```text
src/grace_control/api/routers/features.py
src/grace_control/core/gate_resolver.py
src/grace_control/db/__init__.py
src/grace_control/services/feature_intake_service.py
src/grace_control/services/feature_planning_service.py
src/grace_control/ui/static/admin.js
tests/api/test_features_api.py
tests/grace_control/services/test_feature_planning_store.py
```

This is a real follow-up over the previous skeleton and it closes some issues, but it still does not implement the approved Waves 1–4.

## Executive verdict

Fail.

The follow-up improves the skeleton, but the core architecture is still incomplete:

- Admin now posts to `/api/features`.
- Draft mode now starts a background planning task.
- Approve now sets first-wave packets to `ready` and feature status to lowercase `queued`.
- SQLite startup now creates `feature_planning_runs` if missing.
- Two test files were added.

However, the main product promise remains unimplemented:

- Context Builder is still a stub.
- Architect is still a stub.
- `/api/architect/plan` is still the old duplicate implementation, not a compatibility wrapper.
- Wave 4 is still only a logs read endpoint, not live streaming.
- Added tests mostly validate the stub behavior and do not catch the main regressions.

Therefore this commit is **not acceptable as Waves 1–4 complete**.

## Progress since previous review

## Fixed / improved

### 1. Admin no longer submits New Feature to `/api/architect/plan`

`submitBiz()` now calls:

```javascript
fetch(apiUrl('/api/features'), ...)
```

This closes the previous P0 about the New Feature form using the wrong endpoint.

### 2. `draft_plan` now starts background planning

`POST /api/features` creates the feature, then for `draft_plan` starts `_background_planning()` via `asyncio.create_task()`.

This is directionally correct, although the actual planning logic is still stubbed.

### 3. Approve now uses queue-compatible status/state

`approve_plan()` now sets:

```python
state=PacketState.READY.value if is_first_wave else PacketState.DRAFT.value
feature.status = "queued"
```

This closes the earlier uppercase `QUEUED` and all-`DRAFT` issue.

### 4. SQLite table creation added

`db/__init__.py` now contains `CREATE TABLE IF NOT EXISTS feature_planning_runs ...` in `_SQLITE_TABLE_CREATIONS`.

This helps local SQLite runtime, but it is not a full migration strategy.

### 5. Tests added

Two test files were added:

```text
tests/api/test_features_api.py
tests/grace_control/services/test_feature_planning_store.py
```

This is progress, but the tests are not strong enough for acceptance.

## Blocking findings

## P0-1 — Context Builder is still a hardcoded stub

Expected:

- use real `ContextCollector` / context-bundle behavior;
- respect `target_repo_root`;
- persist useful context result;
- emit started/completed/failed events.

Actual:

`run_context_builder()` returns:

```python
{
    "repo_root": ".",
    "feature_id": feature_id,
    "files_scanned": 0,
    "summary": "Context collection stub — Wave 1",
}
```

Impact:

The feature cannot actually inspect repository context before Architect planning.

Required fix:

- extract/reuse real `_warm_context()` behavior from `architect.py` into `FeaturePlanningService` or a dedicated service;
- use `target_repo_root` from feature spec;
- persist context summary/files/errors in `FeaturePlanningRun.result_json`;
- add tests that fail if `files_scanned == 0` for a real repo fixture.

## P0-2 — Architect is still a hardcoded stub

Expected:

- call real Architect LLM path;
- generate waves/packets from business text and context;
- store model/prompt/result/errors;
- fail visibly on invalid JSON or LLM failure.

Actual:

`run_architect()` sets:

```python
arch_run.model = "stub-model"
```

and creates a single fake plan:

```text
Implementation → Initial implementation → scope ["src/"]
```

Impact:

This is not business-feature planning. It will create the same generic packet regardless of user request.

Required fix:

- move real `_call_architect_llm()` logic from `architect.py` into `FeaturePlanningService`;
- store prompt/model/stdout/stderr where available;
- validate generated plan before `PLAN_READY`;
- add tests with fake architect backend producing deterministic multi-wave plan.

## P0-3 — `/api/architect/plan` is still duplicate planning path

Expected:

`/api/architect/plan` should become a thin compatibility wrapper over the new service path.

Actual:

`architect.py` still owns:

- placeholder Feature/Wave/Packet creation;
- background `_background_plan()`;
- `_warm_context()`;
- `_call_architect_llm()`;
- `_persist_plan()`.

Impact:

There are still two separate planning implementations:

1. `/api/features` — new stubbed path;
2. `/api/architect/plan` — old real-ish LLM path with placeholder packets.

This violates the main architecture rule and guarantees behavior drift.

Required fix:

- extract common planning/materialization code into services;
- route `/api/architect/plan` through the same services;
- remove placeholder packet behavior for business-feature intake.

## P0-4 — Wave 4 live logs are still not implemented

Expected:

- stdout/stderr visible while Context Builder / Architect are still running;
- ProcessSupervisor / AgentRunService write logs incrementally;
- final process result remains compatible.

Actual:

The logs endpoint only reads `stdout_path` or `stderr_path` from planning state and tails the file.

But the current stub planner does not set `stdout_path` / `stderr_path`, and this diff does not change `ProcessSupervisor` or `AgentRunService`.

Impact:

Wave 4 remains endpoint-only. It does not provide live logs.

Required fix:

- implement streaming stdout/stderr in process execution layer;
- store planning run log paths;
- test that logs are visible before process completion.

## P0-5 — Tests are too weak and partially accept wrong behavior

Examples:

- `test_create_feature_auto_queue` accepts status `queued` **or** `PLANNING`, which would allow auto_queue to silently fail to queue.
- `test_approve_fails_before_plan_ready` accepts both `200` and `409`, so it does not prove the gate works.
- `test_get_planning_logs` only checks that response has `lines` and `total`; it does not assert real logs exist.
- service tests validate the stub context and stub architect behavior rather than real Context Builder / Architect integration.

Impact:

The green tests can pass while the main feature is still non-functional.

Required fix:

- remove permissive `200 or 409` assertions;
- assert exact lifecycle states;
- assert auto_queue ends with queued feature and READY first packet;
- assert draft mode eventually reaches PLAN_READY with non-stub plan;
- assert logs are produced and visible for a running process;
- assert Admin UI no longer contains `/api/architect/plan` in `submitBiz`.

## P1 findings

## P1-1 — SQLite-only table creation is not a proper migration

`db/__init__.py` creates `feature_planning_runs` only in SQLite startup migrations. Non-SQLite dialects return early and do not receive this migration path.

If the project intends SQLite-only for now, document that. Otherwise add Alembic or the repo's canonical migration equivalent.

## P1-2 — Mode remains free-form string

`FeatureCreateRequest.mode` is still `str`, not a strict enum/literal. Unknown modes will create a `PLANNING` feature and then fall through.

Required fix:

```text
mode: Literal["draft_plan", "auto_queue"]
```

## P1-3 — Regenerate still does not actually regenerate

`regenerate_plan()` sets status back to `PLANNING`, creates another pending context_builder run, removes `plan_json`, and returns state. It does not actually run context/architect again.

Required fix:

- either trigger background planning like create does;
- or make regenerate explicitly only enqueue and document a runner.

## P1-4 — Event coverage remains incomplete

Expected stage lifecycle events should include started/completed/failed for context builder, architect, and materialize.

Current service mostly emits completed/ready/materialized events. Failed stage persistence is not robust.

## P1-5 — Logs endpoint should validate stream and state-root

The endpoint chooses stdout for `stream == "stdout"`, otherwise stderr. Unknown stream values silently map to stderr.

Required fix:

- reject streams except `stdout|stderr`;
- validate resolved path is under known GRACE state/artifact root;
- cap tail with lower and upper bounds.

## File notes

## `src/grace_control/api/routers/features.py`

Good:

- New endpoint path exists.
- Draft mode now starts background planning.
- Logs endpoint validates run belongs to feature via planning state.

Problems:

- Background task uses sync service calls and has minimal failure persistence.
- Unknown `mode` falls through instead of 422.
- Logs endpoint is still file-reading logic inside router.

## `src/grace_control/services/feature_planning_service.py`

Good:

- Approve now uses first wave READY / later waves DRAFT.
- Feature status now lowercase `queued`.
- Service commits stage changes.

Problems:

- Context and architect are still stubs.
- Materialization still does not reuse old `_persist_plan()` enrichment.
- Regenerate does not run planning.
- No stdout/stderr paths are produced.

## `src/grace_control/ui/static/admin.js`

Good:

- `submitBiz()` now posts to `/api/features`.

Problems:

- Dashboard still renders only waves/packets; it does not show a proper feature-level Planning / Plan JSON / Events / Logs detail for pre-materialized features.
- `state.selectedPlanningFeature` is set but not visibly used in the reviewed range.

## `src/grace_control/db/__init__.py`

Good:

- SQLite table creation is added.

Problems:

- This is SQLite-only and not a full migration.

## Required next fix packet

Create one focused fix wave, not another broad “Waves 1–4 complete” claim.

### Fix packet A — Real planning service

- Move real `_warm_context()` from `architect.py` into service layer.
- Move real `_call_architect_llm()` into service layer.
- Make `/api/features` use real context + real architect.
- Make `/api/architect/plan` a wrapper over the same service.
- Add fake backend tests for deterministic architect output.

### Fix packet B — Admin planning detail

- Render planning feature card before waves exist.
- Show Context Builder / Architect / Plan Ready.
- Add View JSON / Approve / Regenerate.
- Add frontend test that `submitBiz()` calls `/api/features` and not `/api/architect/plan`.

### Fix packet C — Live logs

- Implement process streaming in ProcessSupervisor / AgentRunService.
- Store stdout/stderr paths in FeaturePlanningRun.
- Restrict logs endpoint.
- Add live-log tests.

### Fix packet D — Tests/gates

- Replace permissive assertions with exact lifecycle assertions.
- Add queue claim regression test after approve.
- Add no-stub regression: generated plan summary/model must not be `stub-model` in integration mode.

## Final decision

Do not accept `74ce713` as completed Waves 1–4.

Correct status:

```text
FAIL — progress over skeleton, but core blockers remain.
```

Recommended next action:

Return to agent with this review and require a targeted fix focused on:

1. real context builder;
2. real architect service path;
3. `/api/architect/plan` wrapper;
4. live logs;
5. stronger tests.
