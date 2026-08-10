# Review 004

Status: CHANGES_REQUIRED
Reviewed commit: `51acfe1b13a2d1f30cfe930b45ea056311a4899c`

## Blocker 1 — merge-slot WAIT is treated as terminal/manual failure

The coordinator correctly returns a wait condition when an ACCEPTED packet is not first in deterministic order or when another holder owns the target merge lease.

But the current runtime path does not actually wait/retry:

1. `MergeService.merge_packet()` returns `success=False` with `waiting_for_merge_slot: ...`.
2. The packet merge API converts every unsuccessful result into HTTP 409.
3. `Worker._phase_merge()` catches that request failure as a generic merge error, logs `merge_failed_action_required`, and then leaves the phase.
4. The packet remains `ACCEPTED` and therefore keeps its TZ03 parallel lease, but there is no background merger or later automatic retry path that will call merge for this packet again.

With two parallel workers this can deadlock normal operation: packet A merges, packet B gets a temporary merge-slot wait once, then B remains ACCEPTED indefinitely and blocks conflicting future work.

### Required fix

Treat merge-slot/order contention as a non-failure WAIT state all the way through API/client/worker.

A minimal implementation is acceptable:

- distinguish `waiting_for_merge_slot` from real merge failure in the API response/client;
- worker retries the same ACCEPTED packet with bounded sleep/backoff while the condition is only merge-slot/order contention;
- do not emit `merge_failed_action_required` for an expected wait;
- once the earlier holder releases / earlier ACCEPTED packet becomes MERGED, the waiting packet must automatically retry and merge;
- real checkout/merge/push/sanity/fencing failures remain errors and must not be blindly retried as slot contention.

Do not defer this to TZ06: TZ04's DONE condition says serialized merge must work for multiple workers, and "second waits" must lead to eventual progress.

### Required regression test

Exercise the actual worker/API merge lifecycle (or an equivalent integration path), not only direct coordinator calls:

- two ACCEPTED packets for the same repo;
- both workers attempt merge concurrently;
- deterministic first packet gets the slot;
- second gets a WAIT and performs zero target mutation while waiting;
- after first releases the merge lease / becomes MERGED, second automatically retries;
- both packets end MERGED without a manual-action merge failure.

## Blocker 2 — target-repo git cleanup happens after the merge lease is released

`MergeService.merge_packet()` releases the DB merge lease in its `finally` block. After it returns successfully, the API router calls `cleanup_worktree()`.

That cleanup still performs git mutations against the same logical target repository:

- `git worktree remove --force`;
- `git worktree prune`;
- `git branch -D`.

Therefore packet B can acquire the merge lease and start checkout/merge while packet A is still mutating shared git metadata during cleanup. This breaks the serialized-target-repo invariant even though checkout/merge/push themselves are guarded.

### Required fix

Keep all target-repository git cleanup that belongs to the completed packet inside the same merge-serialization boundary, or reacquire/hold an equivalent merge lease before those target-repo git mutations.

Preferred simple shape:

- pass the worktree path into the merge orchestration;
- perform target-repo `worktree remove/prune` / branch cleanup while the current merge lease is still held;
- only then release the merge lease;
- pure filesystem `shutil.rmtree` that does not touch shared target-repo git state may remain outside if desired.

Do not make cleanup failure incorrectly roll back an already successful git merge; it can remain best-effort, but it must not race another target mutation.

### Required regression test

Instrument target mutation steps including cleanup:

- first same-repo merge pauses during target git cleanup;
- second packet attempts merge;
- second must not begin checkout/merge/push until first cleanup's shared-repo git operations finish and the merge lease is released;
- observed max concurrent shared-target git mutations must remain 1.

## Notes

The core TZ04 pieces are otherwise in good shape: Alembic/ORM lease schema, canonical repo key, `BEGIN IMMEDIATE`/row locking, takeover sanity checks, fencing before guarded steps, deterministic ACCEPTED ordering, and TZ03 parallel-lease release on MERGED are all directionally correct.

Keep TZ05 stale-base integration recheck out of this fix.

Run TZ04 + TZ03 + migration/schema/lease/queue regressions, Ruff, `python3 -m py_compile`, applicable GRACE lint, and `git diff --check`.

Commit and push the fix, then create:

`docs/work/agent_exchange/outbox/004_RESUBMISSION.md`

Do not start Task 005 until reviewer returns `ACCEPT 004`.
