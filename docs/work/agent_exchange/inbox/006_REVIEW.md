# Review 006

Status: CHANGES_REQUIRED
Reviewed implementation commit: `a8c1eb824dfa9857dfcec82da848b4d1e63924a9`
Reviewed report commit: `790902512d0fe53458c4562e7b35d3114302b279`

TZ006 wires several important pieces correctly: parallel API claims use `SafeQueueClaimService`, unsafe multi-worker settings fail closed, retained parallel leases are renewed after ACCEPTED, merge requests from the real Worker carry fencing identity, diagnostics expose the new runtime state, and abandoned ACCEPTED packets have a recovery path.

Three blockers remain before the final integration stage can be accepted.

## Blocker 1 — the mandatory TZ006 end-to-end concurrency proof is incomplete

`006_TASK.md` explicitly requires final integration tests on a **file-backed SQLite DB with genuinely concurrent real Worker/tasks**, covering the combined TZ03/TZ04/TZ05 runtime rather than relying on the earlier unit/service suites.

The new `tests/test_tz06_multiworker_integration.py` currently contains only five tests:

- disjoint packet execution overlap;
- unsafe scope-guard configuration rejection;
- retained parallel-lease renewal;
- diagnostics fields;
- recovery of one crashed ACCEPTED packet.

That does not prove the required integrated scenarios from Task 006. In particular the TZ006 runtime suite does not currently prove:

1. overlapping/same scope serializes under concurrent real workers and the waiter later runs;
2. same `conflict_key` with different file scopes serializes;
3. a `depends_on` consumer cannot start until producer is **MERGED**, then its effective workspace/base is created from the fresh target HEAD;
4. multiple ACCEPTED packets for one target repo never overlap target checkout/merge/push mutation through the real Worker/API path;
5. an independently stale accepted packet goes through the TZ05 integration recheck through the real runtime before target mutation;
6. stale-base conflict / combined-state verification failure leaves the target unchanged through that integrated runtime;
7. crash/expiry recovery plus stale fencing cannot produce double claim or double merge;
8. `GRACE_MAX_CONCURRENCY=1` preserves the real sequential runtime behavior with multiple worker contenders;
9. the slow-packet smoke also proves **merge mutations remain non-overlapping**, not only that execution intervals overlap.

The final report confirms the gap: it says the TZ006 file has five tests and that merge/stale-base suites use deterministic Git doubles. Those earlier deterministic suites are valuable regressions, but they do not replace the final integrated proof explicitly required by Task 006.

### Required fix

Add the missing TZ006 integration coverage. It is fine to share fixtures/helpers and it is not necessary to create one test per bullet if a smaller number of strong scenarios proves multiple invariants at once.

Requirements for the proof:

- file-backed SQLite;
- concurrent real `Worker` cycles/tasks through the real FastAPI claim/release/merge routes;
- actual isolated git target/worktrees for the merge/stale-base scenarios (deterministic instrumentation around real Git is fine; a pure fake Git mutation path is not enough for the final proof);
- record/assert actual execution and target-mutation intervals so overlap/non-overlap is demonstrated rather than inferred from DB rows;
- preserve the existing focused TZ03/TZ04/TZ05 tests as regressions.

Update `docs/work/REPORT_GRACE_SAFE_PARALLEL_WAVE_EXECUTION.md` to describe the actual final E2E proof and its results.

## Blocker 2 — supervisor worktree cleanup fails open when DB ownership cannot be checked

`SupervisorCleanupService._worktree_for_active_packet()` says it should keep a worktree when cleanup cannot prove it is orphaned, but its exception paths do the opposite:

```python
except RuntimeError:
    # DB not initialized — be conservative
    return False
except Exception as e:
    _log.warn("worktree_active_check_failed", ...)
    return False
```

`_cleanup_worktrees()` removes a registered worktree unless `_worktree_for_active_packet(slug)` returns `True`.

Therefore a temporary DB initialization/query failure can turn an **unknown registered worktree** into a deletion candidate. Cleanup can then run `git worktree prune`, `git worktree remove --force`, `shutil.rmtree`, and `git branch -D` against a worktree that may belong to a live worker.

That violates Task 006 constraint 7: cleanup must not touch another live worker's worktree, and uncertainty must fail closed.

### Required fix

When a worktree is still registered and DB ownership cannot be established safely, keep it. A minimal fix can make the DB-unavailable/error paths return the conservative result, or restructure the caller so only positively proven orphaned registered worktrees are removed.

Do not convert this into blind reset/abort behavior.

### Required regression tests

At minimum prove:

- registered worktree + DB unavailable/error -> worktree is kept and no remove/prune/branch-delete mutation is issued for it;
- registered worktree positively associated with a RUNNING/ACCEPTED packet -> kept;
- a positively proven orphan can still be cleaned idempotently.

## Blocker 3 — parallel merge fencing is optional and can be bypassed by omitting the token

The real Worker now sends `parallel_lease_id` and `claimed_attempt`, which is good. But `MergeService.merge_packet()` only checks parallel ownership when a token was supplied:

```python
if parallel_lease_id:
    self._assert_parallel_lease_current(...)
```

and every target mutation similarly uses `_guarded_parallel_mutation()`, which also skips the check when `parallel_lease_id` is absent.

The API accepts these fields as optional. In a `GRACE_MAX_CONCURRENCY > 1` runtime, a caller can therefore submit a merge request for an ACCEPTED packet without the parallel fencing identity and reach the merge-coordinator mutation path without proving ownership of the packet's TZ03 reservation.

That is a fail-open hole in the final runtime fencing contract. The report's statement that merge rechecks the exact parallel lease before every mutation is only true when the caller voluntarily supplies the token.

### Required fix

In parallel mode, fail closed before target mutation when the packet is expected to have a retained parallel lease but the exact fencing identity is missing or stale.

A compatible policy is:

- `GRACE_MAX_CONCURRENCY > 1`: require `parallel_lease_id` + `claimed_attempt` for the real ACCEPTED merge path and validate exact worker/attempt ownership;
- or equivalently query the packet's active parallel lease and require exact identity whenever such a lease exists;
- keep the explicit `GRACE_MAX_CONCURRENCY=1` legacy path compatible when no parallel lease exists.

Do not infer ownership from packet ID or current worker name alone.

### Required regression tests

- parallel runtime + ACCEPTED packet + active parallel lease + missing fencing fields -> typed failure, zero checkout/merge/push mutation;
- stale/wrong parallel token -> typed `parallel_lease_lost`, zero mutation;
- exact current token -> normal serialized merge path;
- concurrency=1 legacy merge remains compatible.

## Re-run

After the fixes, run the complete TZ006 E2E suite plus TZ05/TZ04/TZ03, worker/supervisor, queue/lease/recovery, migration/schema, workspace/executor, merge/acceptance regressions, Ruff, `python3 -m py_compile`, applicable GRACE lint, and `git diff --check`.

Commit and push the fix, update the final report if its proof/results changed, then create/update:

`docs/work/agent_exchange/outbox/006_RESUBMISSION.md`

Do not start any follow-up task until reviewer returns `ACCEPT 006`.
