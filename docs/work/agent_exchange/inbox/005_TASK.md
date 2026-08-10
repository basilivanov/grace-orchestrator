# Task 005 — Stale-base integration recheck

## Source of truth

Implement:

`docs/work/TZ_GRACE_PARALLEL_05_STALE_BASE_RECHECK.md`

Master spec for ambiguous details:

`docs/work/TZ_GRACE_SAFE_PARALLEL_WAVE_EXECUTION.md`

Depends on accepted TZ01–TZ04 implementation already present on `main`.

## Reviewer constraints

1. Do not implement TZ06 multiworker/diagnostics/performance work in this task.
2. Add `packet_runs.base_sha` and `packet_runs.integration_base_sha` only through a new Alembic revision plus matching ORM fields; no ad-hoc startup DDL.
3. Persist the **actual target repository HEAD visible when the effective packet workspace is created** as `PacketRun.base_sha`. Do not substitute the orchestrator repo SHA or a scoped-copy synthetic commit.
4. Before target merge, compare that persisted `base_sha` with the current target branch HEAD while respecting the accepted TZ04 merge-serialization/fencing protocol.
5. If HEAD is unchanged, keep the normal serialized merge path and record integration recheck as `skipped`.
6. If HEAD advanced, do not mutate the target checkout first. Build a disposable integration workspace from the current target HEAD, apply the packet result there, and verify the combined state.
7. Git conflict during integration apply must leave the target unchanged and move the packet to `BLOCKED_RECOVERABLE` with failure class `stale_base_conflict`, base/current SHA and evidence.
8. Clean apply but failed integration verification must leave the target unchanged and move the packet to `BLOCKED_RECOVERABLE` with failure class `integration_verification_failed` and logs/evidence.
9. Successful stale-base verification must persist `integration_base_sha`, then merge/push only against the same validated target state. Do not allow target HEAD to advance between the state that passed recheck and the final mutation without detecting/rechecking it.
10. Run at least packet T1 and preserve profile-aware verification semantics on the combined state; do not replace this with a superficial git-conflict-only check.
11. Keep TZ03 parallel lease held until MERGED or the defined blocked/failure release point. Preserve TZ04 merge fencing/heartbeat and deterministic merge order.
12. Temporary integration worktrees/branches must be cleaned safely and must not introduce an unguarded shared `.git/worktrees` race.
13. Write/update `result_json.parallel_execution` with `base_sha`, `integration_base_sha`, `stale_base`, `conflict_keys`, and `integration_recheck = skipped|passed|failed`.
14. Add `GRACE_INTEGRATION_RECHECK_ON_STALE_BASE=true` with default true and keep the disabled path explicit/backward-compatible.
15. No automatic LLM conflict resolution and no speculative dependent-packet execution.

## Required tests

At minimum prove:

- A and B start from target SHA X; A merges to Y; B detects stale base;
- B clean-applies to Y, combined-state T1 passes, `integration_base_sha=Y`, then B merges;
- stale-base git conflict produces `BLOCKED_RECOVERABLE/stale_base_conflict` and target HEAD/content remain unchanged;
- clean apply plus combined-state verification failure produces `BLOCKED_RECOVERABLE/integration_verification_failed` and target remains unchanged;
- unchanged target HEAD skips recheck cleanly;
- actual target `base_sha` is persisted at effective workspace creation;
- target HEAD advancing again during/after recheck is detected rather than merging a result validated against an obsolete integration base;
- temporary integration worktree cleanup is safe and serialized with shared target git metadata;
- existing TZ04 WAIT/fencing/heartbeat behavior still passes.

## Required result

Run targeted TZ05 tests plus relevant TZ04/TZ03, migration/schema, packet-executor/workspace, acceptance/merge regressions, Ruff, `python3 -m py_compile`, applicable GRACE lint, and `git diff --check`.

Commit and push the implementation.

Then create:

`docs/work/agent_exchange/outbox/005_SUBMISSION.md`

Keep the submission short:

- commit SHA;
- what changed;
- tests/checks run and results;
- any known limitation or deviation from TZ05.

Do not start Task 006 until reviewer returns `ACCEPT 005`.