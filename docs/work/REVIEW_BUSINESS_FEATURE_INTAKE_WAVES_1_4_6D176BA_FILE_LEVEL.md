# File-level review: Business Feature Intake + Planning Pipeline Waves 1–4

Status: REVIEWED / FAIL — BLOCKING ISSUES
Date: 2026-06-12
Reviewed commit: `6d176ba4def0b1844e999a86e36dc12a017b9bde`
Base: `0a2faf05170aaeefad8f509a73d33f4d10777ebb`
Scope: file-level review of `0a2faf0..6d176ba`

## Diff scope

The actual GitHub compare for `0a2faf0..6d176ba` shows one commit and only these changed files:

```text
src/grace_control/api/routers/features.py
src/grace_control/db/schema.py
src/grace_control/services/feature_intake_service.py
src/grace_control/services/feature_planning_service.py
```

This is important because the claimed Waves 1–4 scope also required:

- admin UI changes;
- `/api/architect/plan` compatibility-wrapper refactor;
- migration `0017`;
- tests;
- live log streaming changes in ProcessSupervisor / AgentRunService.

Those are not present in this diff.

## Executive verdict

Fail / not accepted.

This commit is a useful skeleton for part of Wave 1, but it does **not** implement Waves 1–4 as specified.

The current implementation would not deliver the target user flow:

```text
Admin New Feature → /api/features → background planning → PLAN_READY → approve → existing queue runs packets
```

Instead, the current code has multiple blocking gaps:

1. Admin UI still posts to `/api/architect/plan`.
2. Default `draft_plan` creates pending rows but never starts context/architect planning.
3. `FeaturePlanningService` uses stub context and stub architect plan, not real ContextCollector / LLM.
4. Approve creates packets in `DRAFT` and sets feature status to uppercase `QUEUED`, which does not match queue selection logic.
5. `/api/architect/plan` remains the old full planning implementation, not a compatibility wrapper.
6. No migration is included for the new `feature_planning_runs` table.
7. No tests are included in this diff.
8. Wave 4 live streaming is not implemented; only a logs read endpoint exists.

## Blocking findings

## P0-1 — Admin UI still uses `/api/architect/plan`

Expected:

```text
Admin New Feature → POST /api/features
```

Actual:

`src/grace_control/ui/static/admin.js` still submits business text to:

```javascript
fetch(apiUrl('/api/architect/plan'), ...)
```

This means Wave 3 is not implemented for the real Admin UI. The new `/api/features` endpoint is not actually used by the user's New Feature flow.

Required fix:

- change `submitBiz()` to call `POST /api/features`;
- default mode should be `draft_plan`;
- UI must render feature-level planning state before packets exist;
- add tests asserting Admin no longer calls `/api/architect/plan`.

## P0-2 — `draft_plan` never starts planning

Expected:

```text
POST /api/features mode=draft_plan
→ create Feature PLANNING
→ background Context Builder
→ background Architect
→ PLAN_READY
```

Actual:

`features.py:create_feature()` calls `FeatureIntakeService.create_feature()` and returns immediately for non-`auto_queue` mode. No `BackgroundTasks`, no async task, no scheduler enqueue, no call to `run_context_builder()` or `run_architect()`.

`FeatureIntakeService.create_feature()` creates:

- Feature with status `PLANNING`;
- submit run `done`;
- context_builder run `pending`.

Then it returns. Nothing advances the feature.

Impact:

A real `draft_plan` feature will remain stuck in `PLANNING` with `context_builder=pending` forever.

Required fix:

- add background planning execution for draft mode;
- or add explicit planning queue/runner and document it;
- persist failures visibly.

## P0-3 — Context Builder and Architect are stubs

Expected:

- Context Builder uses the existing context collection path.
- Architect uses the existing LLM planning path.
- Real plan JSON is produced from business task + codebase context.

Actual:

`FeaturePlanningService.run_context_builder()` returns a hardcoded stub:

```python
{
  "repo_root": ".",
  "feature_id": feature_id,
  "files_scanned": 0,
  "summary": "Context collection stub — Wave 1",
}
```

`FeaturePlanningService.run_architect()` returns a hardcoded one-wave/one-packet stub plan and sets `model = "stub-model"`.

Impact:

This is not the intended Context Builder / Architect implementation. It cannot produce real GRACE plans from business requirements.

Required fix:

- reuse/extract the real `_warm_context()` and `_call_architect_llm()` logic from the current architect router into `FeaturePlanningService`;
- do not keep those as router-owned internals;
- store prompt/model/stdout/stderr where available.

## P0-4 — Approved feature will not enter the existing queue correctly

Expected from TZ:

- after approve, first wave packets become `ready`;
- later wave packets remain `draft`;
- feature status must match existing queue semantics.

Actual in `FeaturePlanningService.approve_plan()`:

```python
packet.state = PacketState.DRAFT.value
feature.status = "QUEUED"
```

This conflicts with the existing queue service.

`queue_service` only finds queued features with statuses:

```python
Feature.status.in_(["queued", "NOT_STARTED"])
```

It then looks for packets with:

```python
p.state == PacketState.READY.value
```

Impact:

An approved feature with status `QUEUED` and all packets `DRAFT` is likely invisible/stuck:

- uppercase `QUEUED` is not selected by `_oldest_queued_feature()`;
- even if selected later, the queue claims only `READY` packets;
- no first-wave packet is made `READY` by approve.

Required fix:

- set feature status to existing accepted queued state, safest: `NOT_STARTED`;
- set first-wave packets to `ready`;
- set later-wave packets to `draft`;
- or update `queue_service` and tests to support uppercase `QUEUED` explicitly.

## P0-5 — `/api/architect/plan` is still a duplicate full planning path

Expected:

`/api/architect/plan` remains only as a thin compatibility wrapper around the new services.

Actual:

`src/grace_control/api/routers/architect.py` still contains the old implementation:

- immediate placeholder feature/wave/packet creation;
- background `_background_plan()`;
- `_warm_context()`;
- `_call_architect_llm()`;
- `_persist_plan()`.

Impact:

There are now two planning implementations:

1. old `/api/architect/plan` path, still used by Admin;
2. new `/api/features` skeleton path.

This violates the main architecture rule: no duplicate planning path / no second control flow.

Required fix:

- move real planning logic into `FeaturePlanningService`;
- make `/api/architect/plan` call the same service path;
- remove or deprecate placeholder wave/packet behavior for business-feature intake.

## P0-6 — No migration for `feature_planning_runs`

Expected:

A DB migration creates `feature_planning_runs`.

Actual:

The diff adds the SQLAlchemy model in `schema.py`, but no migration file is present in this commit.

Impact:

Production / persistent DB will not have the table, so the new endpoints can fail with `no such table: feature_planning_runs` unless the runtime uses `create_all()` in a way that masks this locally.

Required fix:

- add migration `0017` or equivalent;
- include upgrade/downgrade;
- add migration smoke test.

## P0-7 — No tests in the actual diff

The runner summary claimed 14 new tests and 600 backend / 756 frontend green, but this commit changes only four source files and no tests.

Impact:

The reported tests are not represented in the reviewed diff.

Required fix:

Add tests for at least:

```text
tests/api/test_features_create_business.py
tests/api/test_feature_planning_api.py
tests/api/test_feature_planning_failures.py
tests/api/test_feature_planning_logs.py
tests/grace_control/services/test_feature_planning_service.py
tests/ui/test_admin_new_feature_intake.py
tests/ui/test_admin_planning_observability.py
tests/ui/test_admin_plan_approval.py
```

## P0-8 — Wave 4 live logs are not implemented

Expected:

- logs visible while Context Builder / Architect / Coder are still running;
- ProcessSupervisor / AgentRunService writes stdout/stderr incrementally;
- final ProcessResult remains compatible.

Actual:

The diff only adds:

```text
GET /api/features/{feature_id}/planning/{run_id}/logs
```

No ProcessSupervisor / AgentRunService changes are present.

Impact:

Wave 4 is endpoint-only and does not satisfy the live streaming requirement.

Required fix:

- implement write-during-run stdout/stderr files;
- add process timeout/orphan tests;
- make planning runs store stdout/stderr paths produced by actual execution.

## Major non-blocking findings

## P1-1 — Event coverage is incomplete

Expected events included:

```text
context_builder_started
context_builder_completed
context_builder_failed
architect_started
architect_completed
architect_failed
plan_ready
plan_materialized
feature_queued
```

Actual implementation emits only some completed/ready events and does not consistently emit started/failed events.

Required fix:

- emit started/completed/failed for each stage;
- include stage/status/duration/executor/model/error in payload_json.

## P1-2 — Logs endpoint reads DB paths without root restriction

The logs endpoint only reads a path from planning state, which is better than accepting a path query param. But it does not enforce that paths are under a known state/artifact root.

Required fix:

- validate resolved path is under GRACE state root;
- validate `stream` is only `stdout` or `stderr`;
- normalize `tail` with min and max bounds.

## P1-3 — Mode is free-form string

`FeatureCreateRequest.mode` is currently `str` with default `draft_plan`.

Required fix:

- make it an enum/literal: `draft_plan | auto_queue`;
- reject unknown modes with 422.

## P1-4 — IDs are generated manually instead of existing UID utilities

The new services generate `feat_...`, `wave_...`, `pkt_...`, `fpr_...` via `uuid4().hex` directly.

Existing code has canonical UID helpers for Feature/Wave/Packet. Mixing ID styles can be acceptable only if documented and tested.

Required fix:

- use existing UID helpers for Feature/Wave/Packet;
- define canonical helper for FeaturePlanningRun if needed.

## P1-5 — Plan materialization loses existing enrichment behavior

The old `_persist_plan()` enriches packets with gate resolver, verification, frozen_scope, self-improvement metadata, and first-wave readiness.

The new `approve_plan()` simply stores the packet dict directly and omits those behaviors.

Required fix:

- reuse extracted materialization logic from old `_persist_plan()`;
- keep gate enrichment and constraints behavior.

## File-level notes

## `src/grace_control/api/routers/features.py`

Good:

- Adds the intended endpoint surface.
- Keeps router mostly thin for basic calls.
- Adds logs endpoint with run-id validation by feature planning state.

Problems:

- default `draft_plan` does not start planning;
- `auto_queue` runs synchronously in request and uses stub services;
- logs endpoint has weak stream/tail/path validation;
- router now owns log file reading; this could move to service layer.

## `src/grace_control/db/schema.py`

Good:

- Adds `FeaturePlanningRun` with useful observability fields.

Problems:

- no migration in diff;
- no FK/index constraints beyond basic indexes;
- no explicit status/stage enums.

## `src/grace_control/services/feature_intake_service.py`

Good:

- Creates Feature + initial planning runs;
- emits basic feature-level events.

Problems:

- no background planning trigger;
- unused `self_improvement` in stored spec;
- no mode validation;
- slug generation is simplistic;
- no trace propagation unless caller passes trace_id, and router currently does not.

## `src/grace_control/services/feature_planning_service.py`

Good:

- Has the right service boundary shape;
- supports planning state, context, architect, approve, regenerate.

Problems:

- context and architect are hardcoded stubs;
- no failure persistence around stage exceptions;
- materialization breaks queue semantics;
- materialization omits old packet enrichment;
- regenerate only resets to pending and does not actually regenerate;
- no live logs / stdout/stderr path production.

## Required fix plan

## Fix Wave A — Make new API actually usable

1. Add migration for `feature_planning_runs`.
2. Change approve behavior:
   - feature status → `NOT_STARTED` or queue-supported lowercase `queued`;
   - first wave packets → `ready`;
   - later waves → `draft`.
3. Add idempotency/duplicate-materialization guard.
4. Add tests for approve → queue claim.

## Fix Wave B — Move real planning into services

1. Extract real `_warm_context()` from architect router into `FeaturePlanningService`.
2. Extract real `_call_architect_llm()` into `FeaturePlanningService`.
3. Extract real `_persist_plan()` into shared materializer service.
4. Make `/api/architect/plan` a compatibility wrapper over those services.
5. Remove duplicate background implementation from router.

## Fix Wave C — Admin UI integration

1. Change `submitBiz()` to `POST /api/features`.
2. Add feature-level planning cards for `PLANNING`, `PLAN_READY`, `PLAN_FAILED`.
3. Add Approve/Regenerate/View JSON UI.
4. Add frontend tests asserting no `/api/architect/plan` usage for New Feature.

## Fix Wave D — Real live logs

1. Implement streaming stdout/stderr in ProcessSupervisor / AgentRunService.
2. Store stdout/stderr paths on FeaturePlanningRun.
3. Restrict logs endpoint to DB-backed paths under state root.
4. Add live-log tests.

## Final decision

Do not accept `6d176ba` as Waves 1–4 complete.

Correct status:

```text
FAIL — skeleton only, multiple P0 blockers.
```

Recommended next action:

Create a new implementation packet that fixes P0-1 through P0-8 before running another acceptance review.
