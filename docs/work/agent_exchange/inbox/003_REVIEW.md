# Review 003

Status: CHANGES_REQUIRED
Reviewed commit: `41ed11b`

## Blocker — expired TTL silently stops protecting RUNNING/ACCEPTED packets

`ParallelLeaseService.expire()` intentionally keeps an expired `parallel_leases` row while the packet is `RUNNING` or `ACCEPTED`, which matches the lifecycle rule that the resource must not be released yet.

But `ParallelLeaseService.active_leases()` currently returns only rows with `expires_at > now`.

Therefore, once the parallel TTL expires:

- a `RUNNING` packet can stop protecting its scope/conflict keys during the ordinary-lease expiry/grace/recovery window;
- an `ACCEPTED` packet stops protecting its scope/conflict keys while waiting for merge, because its ordinary lease has already been deleted and nothing heartbeats the parallel lease anymore.

This violates TZ03: the parallel resource reservation must remain effective through execution and must **not** be released at `ACCEPTED`; it stays protected until merge or the defined failure/cancel/recovery lifecycle point.

## Required fix

Make the effective-active decision state-aware and fail-safe.

At minimum:

1. A parallel lease whose packet is `RUNNING` must remain conflict-active until ordinary lease recovery changes the packet out of `RUNNING` (the lease scanner can then expire/reclaim it).
2. A parallel lease whose packet is `ACCEPTED` must remain conflict-active regardless of TTL until `MERGED` or another explicit releasable lifecycle transition removes it.
3. Do not solve this only by leaving the expired DB row in place; `SafeQueueClaimService` / `active_leases()` must actually continue seeing it as a conflict reservation.
4. Preserve fencing for stale worker renew/release operations.
5. Do not implement TZ04 merge serialization or TZ05 stale-base work here.

A clean implementation is to make `active_leases()` (or an equivalent canonical method used by `SafeQueueClaimService`) treat `RUNNING`/`ACCEPTED` packet-backed reservations as active even after their TTL, while allowing the existing recovery path to remove a stale `RUNNING` reservation after packet state is reset.

## Required regression tests

Add tests proving the effective safety property, not only row existence:

1. Claim packet A with scope/key conflicting with packet B.
2. Move A to `ACCEPTED` using the normal fenced release path.
3. Force A's parallel `expires_at` into the past.
4. With `GRACE_MAX_CONCURRENCY > 1`, attempt to claim B.
5. B must remain `READY` / return conflict wait while A is `ACCEPTED`.
6. Move A to `MERGED` through the normal lifecycle/release path.
7. B must then become claimable.

Also cover the stale `RUNNING` window: an expired parallel TTL must still block a conflicting claim while the packet is still `RUNNING`; after ordinary lease recovery changes the packet state and parallel expiry cleanup runs, the conflicting packet may proceed.

Run the TZ03 targeted suite plus migration/schema/lease-manager/queue regressions, Ruff and `git diff --check`.

Commit and push the fix, then create:

`docs/work/agent_exchange/outbox/003_RESUBMISSION.md`

Do not start Task 004 until reviewer returns `ACCEPT 003`.
