# Review 004

Status: CHANGES_REQUIRED
Reviewed commit: `82b138f22ca3d51b07648d01a383b059439c92d8`

The two blockers from the previous review are substantially addressed: merge-slot contention now has a 202 WAIT path with worker retry, and target-repo worktree cleanup has been moved under the current merge lease. Two remaining concurrency blockers must be closed before TZ04 is accepted.

## Blocker 1 — repo sanity runs before merge-slot/order WAIT and can turn normal contention into a hard failure

`MergeService.merge_packet()` currently does target-repository validation and `check_repo_sanity()` before it checks deterministic accepted order and before it tries to acquire the merge lease.

That is unsafe for the second worker while the first worker is actively mutating the same repo.

Concrete timing:

1. Packet A is the current deterministic merge candidate and owns the merge lease.
2. A is inside real `git merge` / another transient target mutation.
3. Packet B calls merge.
4. B first runs `validate_repo()` / `check_repo_sanity()`.
5. The repo may legitimately expose transient dirty state or `MERGE_HEAD` while A is alive and correctly owns the slot.
6. B therefore gets `target_repo is dirty` / `merge_repo_sanity_failed` instead of `waiting_for_merge_slot`.
7. API returns a real error; worker emits `merge_failed_action_required` and stops retrying B.

This recreates the original progress bug under real Git timing even though the new WAIT test passes. The current regression pauses A at `worktree_remove`, after A is already MERGED, where repo sanity stays clean; it does not cover B arriving while A is inside merge/index mutation.

### Required fix

An expected live-slot/order conflict must take precedence over repo-sanity failure.

A safe minimal ordering is:

1. DB-only deterministic order check; if packet is not first -> return `waiting_for_merge_slot` immediately.
2. Attempt merge-lease acquisition; if a live holder owns the repo -> return `waiting_for_merge_slot` immediately, without inspecting transient target state.
3. Once this packet owns the slot, run normal repo sanity before mutation.
4. Expired-lease takeover must still perform the existing non-destructive sanity check before replacing the expired holder.

Equivalent implementations are fine, but a live legitimate holder must never make the waiting worker classify the repo's transient state as a terminal/manual merge failure.

### Required regression test

Use the real MergeService/worker seam:

- A owns the same-repo merge slot and is paused during `merge` (not post-merge cleanup);
- expose `MERGE_HEAD` or transient dirty state while A is paused;
- B attempts merge;
- B must receive WAIT, perform zero target mutation, and must not emit `merge_failed_action_required`;
- after A completes/releases, B retries automatically and reaches MERGED.

## Blocker 2 — merge lease is never heartbeated/refreshed during active merge work

`MergeCoordinatorService` has `renew()` and stores `heartbeat_at`, but the merge orchestration never uses it. `run_mutation()` only calls `assert_current()` before invoking the blocking git callback.

The lease therefore has one fixed expiry from acquisition. A live holder can legitimately spend time in checkout/fetch/merge/push/branch/worktree cleanup, approach `expires_at`, start another mutation while still current, then have the lease expire during that mutation. Another worker can reclaim the expired lease if repo sanity happens to look clean (for example during fetch/ref/worktree metadata operations) and start its own mutation while the old callback is still running.

That violates the core TZ04 invariant: one logical target repo must never have concurrent mutation, and an active holder must remain fenced for the duration of its mutation sequence.

### Required fix

Keep the merge lease alive while the holder is actively working.

Acceptable approaches:

- heartbeat/renew the lease during guarded mutation execution; or
- refresh the lease immediately before every guarded mutation and guarantee that no single guarded callback can outlive the refreshed TTL. Multi-command callbacks such as packet branch cleanup must then be split into individually guarded/renewed target mutations (or heartbeat internally).

Do not hold a long DB transaction around git/subprocess work.

After lease/token loss, the stale holder still must fail closed before any subsequent mutation.

### Required regression test

Add a deterministic lease-expiry concurrency test, not only a stale-token-after-takeover test:

- use a short merge lease TTL or force the lease near expiry;
- A is a live holder and enters a guarded target mutation;
- keep A active long enough that the original expiry would elapse;
- B attempts same-repo takeover/mutation;
- while A is alive, B must not begin target mutation and observed max same-repo mutation concurrency must stay 1;
- after A really releases/stops heartbeating, normal expired takeover remains possible and receives a fresh fencing token.

## Notes

Good in the resubmission:

- API 202 WAIT is no longer a generic HTTP merge failure;
- worker retries expected slot/order WAIT with bounded backoff delay;
- expected WAIT no longer emits manual-action failure;
- `worktree remove`, `worktree prune`, and worktree branch deletion now execute inside the merge-lease boundary;
- the new concurrent cleanup test proves the second merge does not overlap that cleanup path.

Keep TZ05 stale-base integration recheck out of this fix.

Run TZ04 + TZ03 + migration/schema/lease/queue/worker regressions, Ruff, `python3 -m py_compile`, applicable GRACE lint, and `git diff --check`.

Commit and push the fix, then update/create:

`docs/work/agent_exchange/outbox/004_RESUBMISSION.md`

Do not start Task 005 until reviewer returns `ACCEPT 004`.
