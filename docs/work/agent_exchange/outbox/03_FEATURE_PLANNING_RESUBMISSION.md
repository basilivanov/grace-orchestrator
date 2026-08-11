# Feature planning review resubmission

WEB_ORCH_REPORT: RESUBMISSION 03_FEATURE_PLANNING
WEB_ORCH_STATUS: DONE
WEB_ORCH_COMMIT: cb4643b7bc1c0ee603ce6fdd82419958a93ac90c
WEB_ORCH_CHECKS: PASS

## Implemented review fixes

- Kept `FeaturePlanningService.approve_plan(feature_id)` as the stable public
  facade and moved compiler/canonicalizer/materialization ownership into
  `PlanApprovalService`.
- Kept `FeaturePlanningService.try_approve_or_repair_plan(...)` with its
  existing signature and return semantics, and moved autofix/recovery and the
  bounded Architect repair loop into `PlanRepairService`.
- Split the approval compiler/materializer and repair/LLM-repair orchestration
  into practical-sized functions without changing compiler, canonicalizer,
  materializer, event, state, DTO, READY/DRAFT, or target propagation behavior.
- Preserved the four existing planning stage/workspace/support modules, helper
  exports, patch points, and public `grace_control.core.plan_compiler` boundary.
- Added no new GraceLint allowlist entries and left the existing narrow entries
  unchanged.

## Size and verification

- `feature_planning_service.py`: 416 physical lines.
- `planning_approval_service.py`: 365 physical lines; largest orchestration
  functions are compiler ~2067 and materializer ~1566 Grace-estimated tokens.
- `planning_repair_service.py`: 379 physical lines; largest orchestration
  functions are repair ~1944 and LLM repair ~1679 Grace-estimated tokens.
- `py_compile`, targeted GraceLint for all planning modules, and `git diff
  --check` pass.
- Required targeted tests: plan autofix `24 passed`; the other targeted suites
  retain only their baseline `/tmp` permission and existing fixture failures.
- `make test`: `1584 passed, 2 skipped, 33 failed`; the 33 failed test nodes
  match the clean review baseline and no new failures were introduced.
- `make lint` remains blocked because the environment has no `ruff` module.
- Full GraceLint reports the same 1143 pre-existing repository violations;
  touched planning modules have no violations.
