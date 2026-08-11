# TZ 04_MERGE_PIPELINE — Grace Local Adopt merge pipeline refactor

Status: READY FOR CODER
Source programme: `TZ_GRACE_LOCAL_ADOPT_REFACTOR_MASTER.md`
Source block: `TZ_GRACE_LOCAL_ADOPT_REFACTOR_04_MERGE_PIPELINE.md`
Dependency: previous Local Adopt named TZs through `03_FEATURE_PLANNING` — ACCEPTED by Architect

## Coder protocol

You are the Coder for this named TZ. Read and execute **only this file**. Do not open or start another inbox task/TZ unless the Architect explicitly names it after ACCEPT.

Before editing anything:

1. Work in `/opt/grace-orchestrator`.
2. Fast-forward sync with GitHub. The checkout must be clean and updated from `origin/main`; use fast-forward-only sync and do not create a merge commit.
3. If the checkout cannot fast-forward cleanly, stop and report the blocker; do not overwrite local work.

After implementation:

1. Run the required verification below.
2. Commit the implementation.
3. Push the commit to GitHub.
4. Create **only** `docs/work/agent_exchange/outbox/04_MERGE_PIPELINE_SUBMISSION.md` for the report.
5. Do not create the next task, review file, `state.json`, lock files, orchestration metadata, or any other coordination file.

The submission must contain these exact lines with the real implementation commit SHA:

```text
WEB_ORCH_REPORT: SUBMISSION 04_MERGE_PIPELINE
WEB_ORCH_STATUS: DONE
WEB_ORCH_COMMIT: <commit-sha>
WEB_ORCH_CHECKS: PASS
```

If the Architect later returns REVIEW, read only `docs/work/agent_exchange/inbox/04_MERGE_PIPELINE_REVIEW.md`, fix that review, and report only to `docs/work/agent_exchange/outbox/04_MERGE_PIPELINE_RESUBMISSION.md`.

## Goal

Refactor `src/grace_control/services/merge_service.py` into a bounded stable `MergeService` facade plus coherent merge-focused owners, without changing merge behaviour, packet lifecycle/state semantics, conflict/stale-base handling, acceptance/integration recheck semantics, evidence/artifact contracts, or public return shapes.

Required structural result:

- `merge_service.py` must be `<= 1000` physical lines with practical headroom; target `<= 800`, preferably materially below that when a thin facade is natural;
- the current large `merge_packet()` path must be `< 4000` Grace-estimated tokens (`len(source) // 4`) and target `<= 2500`;
- every touched/new function or async function must remain `< 4000` estimated tokens and large orchestration functions should normally be `<= 2500–3000`;
- every new Python module must stay `<= 1000` physical lines, preferably `<= 800`;
- do not merely move a giant function unchanged into a new near-limit module.

Do not solve this by arbitrary line slicing, compression, string-concatenation lint evasion, or duplicating existing merge/acceptance business rules.

## Owned write scope

Primary source:

- `src/grace_control/services/merge_service.py`

Expected new merge-focused modules under `src/grace_control/services/` (or an equally coherent existing package), plus directly affected merge/integration tests.

Optional only if moved code produces a genuine textual non-size GraceLint false positive that cannot be fixed naturally:

- `.grace/lint_allowlist.yaml`

Any allowlist change must be narrow, truthful, non-size, and explained. Never add `GRC005` or `GRC012` suppression and never obscure normal identifiers to evade GraceLint.

### Explicitly out of scope

Do not start blocks 05 or 06 and do not reopen accepted blocks 01–03 unless an unavoidable compatibility defect is proven.

Frozen by default:

- `src/grace_control/db/schema.py`
- Alembic migrations
- `src/grace_control/core/contracts.py`
- `src/grace_control/config/settings.py`
- `src/grace_control/core/state_machine.py`
- public API schemas

Do not change these unless an unavoidable, test-backed compatibility reason exists; if so, keep it minimal and explain it in the submission.

## Required responsibility decomposition

Refactor by merge responsibility, not by line count alone. Exact module names may differ, but ownership must be clear and non-duplicated.

### 1. Stable facade / coordinator

Keep `MergeService` and current public merge entry points/signatures/results compatible. The facade should coordinate explicit stages rather than own all merge mechanics inline.

### 2. Git inspection and merge mechanics

A coherent owner may contain the low-level git/worktree operations currently embedded in merge orchestration, such as:

- accepted/materialized commit and base/head inspection;
- worktree/branch state inspection;
- rebase / merge execution mechanics;
- commit/no-change proof where that belongs with git facts;
- deterministic command/result parsing.

Do not fork an existing dedicated git/worktree owner if one already exists; reuse it.

### 3. Merge guards / consistency checks

A coherent owner may contain merge eligibility and consistency decisions, including current behaviour for:

- packet/state preconditions;
- stale base / stale worktree detection;
- no-change versus existing-commit handling;
- scope and merge-conflict classification;
- overlap/conflict checks for parallel work;
- fail-closed routing before mutating the target branch.

Keep one authoritative implementation of each rule.

### 4. Post-merge integration recheck

A coherent owner may contain the current integration/recheck lifecycle after merge, including acceptance/recheck invocation, terminal routing and any rollback/recovery behaviour already present.

Do not redesign acceptance. Reuse the existing acceptance/recheck owners and preserve their order and result interpretation.

### 5. Evidence / observability / conflict support

Where current merge code owns merge-specific evidence, diagnostics, patch/artifact capture or overlap metadata, extract only if it forms a coherent owner. Preserve exact observable keys/names and do not introduce a generic framework merely to reduce lines.

## Behaviour that must remain unchanged

This is refactor-only. Preserve current observable behaviour, including where applicable:

- `MergeService` public import path;
- current merge method signatures and return/result shapes;
- packet lifecycle/state transitions and state-machine calls;
- transition into and out of integration/merge states;
- stale-base/stale-worktree handling;
- no-change handling and proof of an already-existing accepted commit;
- accepted/materialized/base commit resolution;
- rebase behaviour and failure classification;
- git merge conflict behaviour and conflict diagnostics;
- parallel scope/overlap conflict semantics;
- post-merge integration recheck / acceptance semantics and ordering;
- rollback, cleanup and recovery behaviour already present;
- event names and event ordering where observable;
- artifact names/paths and evidence/result JSON keys;
- failure/reason/status codes relied upon by callers/tests;
- target repository/branch selection semantics;
- DB schema and public HTTP contracts.

If a behaviour is currently delegated to an existing helper/service, keep that helper authoritative instead of copying the rule into a new module.

## Regression protection

Existing behavioural/integration tests are the contract and must not be weakened. Before coding, inspect all current source/tests that import `MergeService`, call the merge entry point, monkeypatch merge-service module symbols, or assert merge events/states/evidence.

At minimum preserve or add coverage for the current high-risk cases where they exist:

1. successful merge and terminal state/result;
2. stale base / target head movement;
3. no-change versus already-existing accepted commit;
4. rebase failure;
5. git merge conflict and failure classification;
6. parallel scope/overlap conflict handling;
7. post-merge integration recheck success;
8. post-merge integration recheck failure/rollback or current terminal routing;
9. accepted/materialized/base commit resolution;
10. event names, evidence/result keys and artifacts relied upon by callers;
11. public `MergeService` imports/signatures and any demonstrated monkeypatch points.

Allowed test edits:

- add focused unit tests for an extracted merge owner;
- minimally retarget an internal monkeypatch when ownership genuinely moved;
- add compatibility-import coverage.

Forbidden:

- deleting behavioural assertions;
- changing expected state/status/reason/event/evidence merely to match a refactor regression;
- broad `skip`/`xfail` additions;
- replacing integration coverage with mocks only.

## Lint / structural guardrails

Accepted block 01 semantics are authoritative:

- `GRC005`: violation only when a Python file has `> 1000` physical lines;
- `GRC012`: violation only when `len(function_source) // 4 > 4000`;
- `GRC012` applies to public/private sync/async functions;
- selective `rules_enabled` behaviour remains intact;
- no `GRC005`/`GRC012` allowlist suppressions.

The MASTER headroom targets remain architectural acceptance criteria for this programme; do not park the facade or a new owner immediately below the hard limits.

## Required verification

First identify and run the smallest directly affected current merge/integration test modules. The repository may not have a single file named `test_merge_service.py`; use the actual current tests discovered from imports/calls rather than inventing a path.

At minimum also run:

```bash
make test
make lint
git diff --check
```

And run:

- `.venv/bin/python -m py_compile` on `merge_service.py` and every touched/new merge Python module;
- `scripts/grace_lint.py` targeted at `merge_service.py` and every touched/new merge Python module;
- all current tests that directly exercise the merge facade, merge integration/recheck path, conflict/stale-base path, or patch demonstrated merge-service symbols.

The repository has known baseline/environment debt outside this packet, including a `.venv` without Ruff and a stable unrelated broad-suite failure set. Do not assume a failure is baseline from history. If any required broad or directly affected command is non-zero, compare the exact failure-node set against a clean parent baseline using the same environment and exact arguments. Report whether the sets are identical; any new failure attributable to this packet is a blocker.

Do not claim an individual command passed when it failed. `WEB_ORCH_CHECKS: PASS` may only mean the TZ-specific implementation is green with any separately proven baseline/environment blockers reported precisely.

## Acceptance criteria

Architect will inspect the actual implementation commit and diff. ACCEPT requires all of the following:

1. `merge_service.py <= 1000` physical lines with practical headroom, target `<= 800`.
2. Public merge coordinator below 4000 estimated tokens and target `<= 2500`.
3. No touched/new function exceeds 4000 estimated tokens; large orchestration functions have practical headroom.
4. No new Python module exceeds 1000 lines; avoid near-limit parking where coherent further extraction exists.
5. Responsibilities are extracted coherently, not by arbitrary line slicing/compression.
6. `MergeService` and current public merge entry points/signatures/results remain compatible.
7. State transitions, stale-base/no-change/existing-commit, rebase/conflict, overlap, integration-recheck, recovery and evidence/event semantics remain unchanged.
8. Existing dedicated git/worktree/acceptance/business-rule owners remain authoritative; no duplicate implementation is introduced.
9. Existing behavioural tests are not weakened.
10. Directly affected merge/integration tests pass, or any non-zero set is proven identical to a clean parent baseline.
11. Targeted GraceLint and `py_compile` pass for every touched/new merge source file.
12. No `GRC005/GRC012` suppression or lint-evasion construction is introduced.
13. Diff contains no block 05/06 work and no unrelated product/API/DB/config/state-machine change.
14. Any broad-suite non-zero result is proven against the clean parent baseline rather than merely labelled pre-existing.

## Submission content

Keep `04_MERGE_PIPELINE_SUBMISSION.md` concise but include:

- exact implementation commit SHA;
- files created/modified;
- before/after physical line count for `merge_service.py`;
- before/after `len(source) // 4` estimate for the main merge coordinator;
- largest function(s) in every touched/new merge module;
- old responsibility -> new owner mapping;
- existing helpers/services reused rather than copied;
- public facade/re-exports and patch points retained or intentionally retargeted;
- tests changed/added and why;
- confirmation no behavioural assertion was weakened;
- confirmation merge states/events/artifacts/evidence/result and integration-recheck semantics remain stable;
- exact verification commands/results;
- any baseline/environment failures with clean-parent comparison evidence;
- any narrow non-size allowlist change and rationale;
- any known follow-up debt, without starting another named TZ.
