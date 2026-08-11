# TZ — Grace Local Adopt refactor / 04 Merge pipeline

Status: READY FOR CODER
Parent: `TZ_GRACE_LOCAL_ADOPT_REFACTOR_MASTER.md`
Priority: P0
Dependency: block 01
Primary target: `src/grace_control/services/merge_service.py`

## 1. Problem

`merge_service.py` exceeds the 1000-line Local Adopt limit and has accumulated multiple responsibilities around merge preparation, validation, Git mutation, conflict/staleness handling, integration checks and result persistence.

The repository already contains related services such as:

- `merge_coordinator_service.py`;
- `integration_recheck_service.py`;
- `parallel_conflict_service.py`;
- Git/worktree services.

The refactor must reduce the oversized module without creating duplicate merge semantics across these services.

## 2. Goal

After refactor:

- `merge_service.py` <=1000 lines, preferred <=600-800;
- no merge function/method >4000 estimated tokens;
- `MergeService` remains the stable public facade if currently imported by callers;
- one clear owner exists for every merge business rule;
- stale-base, conflict, recheck and result semantics remain unchanged.

## 3. What we refactor

Required source:

- `src/grace_control/services/merge_service.py`

New helper/service modules may be created under `src/grace_control/services/` where ownership is coherent.

Do not mechanically split the file into numbered parts.

## 4. Preferred responsibility boundaries

Before extracting code, map every merge responsibility to an existing owner. Reuse existing services when they already own the rule.

### A. Merge preflight / eligibility

Candidate responsibility:

- validate that packet/run is merge-eligible;
- resolve current integration/base state needed before mutation;
- check required metadata/commit/worktree inputs;
- produce deterministic preflight result/reason.

If these checks are currently pure and cohesive, extract to a small `merge_preflight_service.py` or equivalent.

Do not move state transitions into this helper unless state ownership already belongs there.

### B. Git merge execution

Low-level Git commands should remain delegated to existing Git/worktree abstractions where available.

Do not introduce a second direct-subprocess Git layer just to shorten `merge_service.py`.

If `merge_service.py` contains orchestration around cherry-pick/merge/reset/cleanup, extract orchestration only and keep generic Git operations in their existing service owner.

Suggested shape:

- `merge_execution_service.py`, or equivalent.

### C. Conflict/stale-base decision

Reuse existing conflict and parallel execution services.

Preserve:

- conflict-key meaning;
- stale-base detection;
- merge refusal/retry conditions;
- integration base SHA semantics;
- reason/error codes and result JSON keys.

If merge-specific mapping glue is large, extract it, but do not copy logic from `parallel_conflict_service.py` or `integration_recheck_service.py`.

### D. Integration recheck orchestration

`integration_recheck_service.py` remains the owner of integration recheck behaviour.

The merge facade/coordinator may decide when a recheck is required and consume its result.

Do not reimplement recheck command execution in a new merge helper.

### E. Merge result/persistence mapping

If a large portion of the module serializes merge outcomes, evidence, metadata and status, extract a cohesive result mapper/persistence helper.

Suggested shape:

- `merge_result_service.py`, or equivalent.

Preserve all persisted keys and values used by admin UI, recovery or tests.

## 5. What stays in `merge_service.py`

Prefer keeping:

- current public class/function import surface;
- top-level merge use case/coordinator;
- dependency wiring;
- high-level order of preflight -> conflict/stale-base -> execution -> recheck -> persistence/cleanup.

The final module should be understandable as the merge application-service facade rather than a container for every implementation detail.

## 6. Behaviour that MUST remain unchanged

Preserve at minimum:

- which packet/run states can enter merge;
- base SHA / integration base SHA handling;
- conflict detection semantics;
- conflict-key semantics;
- stale-base semantics;
- integration recheck trigger and outcome mapping;
- branch/worktree cleanup semantics;
- commit SHA/result capture;
- packet/run final status transitions;
- retry/recovery behaviour;
- event/log names if externally consumed;
- result/evidence JSON structure;
- error/reason codes.

No DB schema or migration change is allowed in this block.

## 7. Public/import compatibility

Do not force unrelated callers to migrate imports.

If internals move:

- keep the old `merge_service` public facade;
- re-export public models/functions if necessary;
- new internal modules should not import the facade, preventing cycles.

## 8. Tests — do we change them?

**Yes: internal patch points may move, behavioural expectations do not.**

Inspect all tests referencing:

- `MergeService` / merge service functions;
- merge coordinator;
- parallel conflict handling;
- integration recheck;
- stale-base behaviour;
- merge result JSON/status;
- worktree cleanup after merge/failure.

### Existing tests stay

Keep existing integration/behaviour tests as the primary contract.

### Add focused tests where extraction creates a new boundary

Examples:

- preflight produces same rejection reason for invalid inputs;
- stale-base decision delegates to existing owner and maps result correctly;
- integration recheck result mapping is unchanged;
- result serializer preserves keys;
- public old import still works.

### Do not weaken

Forbidden:

- changing expected conflict outcome;
- accepting a merge that previously rejected;
- removing stale-base assertions;
- mocking away the integration recheck path in tests that previously exercised it;
- changing final state just to make refactor pass.

## 9. Interaction with `merge_coordinator_service.py`

Do not create two coordinators with overlapping responsibilities.

Before adding a new coordinator module, inspect `merge_coordinator_service.py` and choose one of these patterns:

1. `merge_service.py` remains public facade and delegates orchestration to the existing coordinator; or
2. existing coordinator remains a narrower component and newly extracted helpers own only specific implementation stages.

If responsibility overlap already exists, consolidate deliberately and preserve public imports with facades/re-exports.

Do not expand this block into a full redesign of both modules unless required to remove direct duplication.

## 10. Size acceptance

Required:

- `merge_service.py` <=1000 lines;
- preferred <=800 lines;
- all touched/new modules <=1000 lines;
- all touched functions/methods <=4000 estimated tokens;
- high-level merge method preferred <=2500-3000 estimated tokens.

## 11. Verification

Run dedicated merge/parallel/integration-recheck tests first.

Then:

```bash
make lint
make test
```

Before programme completion:

```bash
make ci
```

## 12. Coder submission

Include:

- before/after `merge_service.py` line count;
- largest merge function before/after token estimate;
- responsibility map from old module to new owners;
- explicit note on how `merge_coordinator_service.py`, `parallel_conflict_service.py` and `integration_recheck_service.py` are reused;
- tests changed/added and why;
- confirmation of unchanged status/reason/result semantics;
- verification commands/results.
