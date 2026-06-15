# W11 — UI/API Diagnostics for Plan and Runtime Failures

Status: READY

Parent TZ: `docs/work/TZ_GRACE_ORCHESTRATOR_RUNTIME_SCOPE_CONTEXT_HARDENING.md`

## Goal

Make fail-closed errors visible in Mission Control, API responses, and diagnostics artifacts.

## Scope

- API routers and response schemas
- UI templates/static JS/CSS
- feature planning diagnostics
- packet runtime diagnostics
- evidence service
- tests

## Required surfaces

Feature planning:

- plan compiler errors;
- canonicalizer warnings;
- raw architect error;
- repair attempts;
- `PLAN_FAILED` reason.

Runtime:

- lease owner/expires/renewed;
- worker current packet;
- stale release attempts;
- failure class/stage;
- scope enforcement result;
- missing evidence;
- merge failure.

Queue/recovery:

- no-packet reason;
- latest stuck scanner decision;
- next safe action.

## Tasks

1. Expose compiler/canonicalizer diagnostics through API.
2. Render plan failure reason in UI without JS errors.
3. Add runtime diagnostics object to packet detail API.
4. Add lease and worker ownership diagnostics.
5. Add recovery scanner latest decision surface.
6. Add stable diagnostics tests.

## Acceptance

- User can see why plan approval/materialization failed.
- User can see why packet is stuck/running/rejected.
- Stale release and merge failure are visible.
- UI renders diagnostics on mobile/desktop without JS crash.

## Required tests

- `test_packet_api_exposes_lease_diagnostics`
- `test_feature_api_exposes_plan_compiler_errors`
- `test_ui_renders_plan_failed_reason_without_js_error`
- `test_ui_renders_stale_running_packet_state`
- `test_runtime_diagnostics_schema_stable`

## Submission

Create `docs/work/Feat_1/exchange/inbox/W11_001_SUBMISSION.md` when done.
