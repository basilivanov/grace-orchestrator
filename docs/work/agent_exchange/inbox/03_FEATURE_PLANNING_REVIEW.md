# REVIEW — 03_FEATURE_PLANNING

Status: REVIEW REQUIRED
Reviewed implementation: `aa37f581ea44c9e149ff1b4f78d4777ed7103f79`
Source packet: `docs/work/agent_exchange/inbox/03_FEATURE_PLANNING.md`

## Protocol

Read and execute **only this review file**. Before editing, fast-forward sync `/opt/grace-orchestrator` from `origin/main` with a clean checkout. Do not start any next named TZ.

After fixing this review:

1. run the required verification below;
2. commit and push the implementation;
3. create only `docs/work/agent_exchange/outbox/03_FEATURE_PLANNING_RESUBMISSION.md`;
4. do not create any next task, state/lock/orchestration metadata, or unrelated coordination file.

The resubmission must identify the real implementation commit and include:

```text
WEB_ORCH_REPORT: RESUBMISSION 03_FEATURE_PLANNING
WEB_ORCH_STATUS: DONE
WEB_ORCH_COMMIT: <commit-sha>
WEB_ORCH_CHECKS: PASS
```

## Review result

The stage extraction itself is directionally correct and the review found no reason to revert it. Context Builder, Architect, workspace safety, and planning-run support are coherent owners. The blocker is **remaining structural headroom in the public facade**.

Current reported/fetched state:

- `feature_planning_service.py`: **987 physical lines**;
- `approve_plan()`: ~**3674** Grace-estimated tokens;
- `try_approve_or_repair_plan()`: ~**3403** Grace-estimated tokens.

This does not satisfy the Local Adopt programme goal of practical headroom. The MASTER explicitly says refactor targets must not merely land just below 1000 lines / 4000 tokens, and this packet itself targets `feature_planning_service.py <= 800` with large orchestration functions preferably <=2500–3000.

The remaining functions also still contain coherent extractable responsibilities rather than unavoidable compatibility glue:

### 1. Approval / compiler / materialization ownership

`approve_plan()` currently combines, among other things:

- PLAN_READY precondition and plan loading;
- scope canonicalizer orchestration/artifacts/events;
- public `PlanCompiler` invocation and compiler result persistence;
- materialization-run lifecycle;
- Wave/Packet creation and packet metadata enrichment;
- materializer artifacts/events;
- final feature queue transition/events.

Extract this as one coherent approval/materialization service (or an equivalently clear bounded ownership). Keep `FeaturePlanningService.approve_plan()` as a compatibility wrapper/delegator.

Do **not** change compiler/canonicalizer/materializer/event/state semantics, DTO/result shape, packet READY/DRAFT rules, target repo propagation, IDs, event names, artifact names, or public compiler boundary.

### 2. Repair / autofix ownership

`try_approve_or_repair_plan()` currently combines:

- approval rejection recovery;
- compiler-error loading/classification;
- deterministic plan autofix and recompilation;
- repair artifacts/events;
- previous Architect session recovery;
- LLM repair attempts;
- scope canonicalization after repair;
- recompilation/terminal routing.

Extract this as one coherent repair/autofix service (or equivalently bounded owner). Keep `FeaturePlanningService.try_approve_or_repair_plan()` as a compatibility wrapper/delegator.

Preserve the existing public method signature/return shape and all current repair-loop semantics, attempt limits, event/artifact names, compiler error persistence, previous-session behavior, canonicalization, and PLAN_READY/PLAN_FAILED transitions.

## Required structural result

After the review fix:

- `feature_planning_service.py` should have real headroom, target **<= 800 physical lines** and preferably materially below that once approval/repair are delegated;
- no touched/new Python module may exceed 1000 physical lines;
- no touched function/method may exceed 4000 estimated tokens;
- large orchestration functions should have practical headroom, target <=2500–3000 rather than ~3400–3700;
- do not simply move either large function unchanged into a new near-limit module;
- split by the coherent approval/materialization and repair/autofix responsibilities described above;
- keep the four already extracted stage/workspace/support modules unless a minimal compatibility adjustment is required.

## Compatibility requirements

Preserve all acceptance requirements from the original packet, including:

- `FeaturePlanningService` public facade;
- `normalize_architect_plan` and demonstrated compatibility helper exports/patch points;
- Context Builder / Architect mutation safety;
- planning run statuses, state transitions, stdout/stderr paths, artifacts and events;
- public `grace_control.core.plan_compiler` dependency boundary only — no private `plan_validation.*` imports;
- plan JSON normalization/current-contract behavior;
- compiler/autofix/materialization behavior;
- no DB schema, migration, settings, state-machine or public API schema changes;
- no test weakening or broad skip/xfail;
- no `GRC005`/`GRC012` allowlist entries and no lint-evasion constructions.

Existing narrow non-size allowlist entries from the first submission may remain only if still truthful after ownership moves. Remove/update any entry whose path/ownership is no longer accurate.

## Verification

At minimum rerun:

```bash
.venv/bin/python -m pytest tests/grace_control/services/test_feature_planning_service.py -q
.venv/bin/python -m pytest tests/grace_control/services/test_feature_planning_store.py -q
.venv/bin/python -m pytest tests/grace_control/services/test_context_builder_safety.py -q
.venv/bin/python -m pytest tests/grace_control/services/test_plan_autofix.py -q
make test
make lint
git diff --check
```

Also run targeted `py_compile` and `scripts/grace_lint.py` for `feature_planning_service.py` and every touched/new planning source module.

If any required test/broad command is non-zero, compare the exact failure-node set against a clean parent baseline using the same environment and exact arguments. Do not merely label failures pre-existing. `make lint` may be reported as the known Ruff environment blocker only if the current parent exhibits the same blocker.

## Resubmission report

Report:

- exact implementation commit SHA;
- final physical line count of the facade and every new/touched planning module;
- largest function estimate in each touched module;
- approval/materialization and repair/autofix responsibility mapping;
- public wrappers/patch points retained;
- any allowlist changes and rationale;
- exact focused/broad verification outcomes and baseline comparison where needed;
- confirmation that no behavioural assertions or planning contracts changed.
