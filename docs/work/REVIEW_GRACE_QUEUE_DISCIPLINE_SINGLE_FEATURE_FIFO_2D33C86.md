# Review: GRACE single-feature FIFO queue discipline

**Review status:** NEEDS_REWORK
**Date:** 2026-06-12

## Reviewed refs

- Base handoff commit: `19369e2`
- Reviewed head: `2d33c86`

## Scope reviewed

Intended scope from handoff:

- deterministic single-feature FIFO queue discipline
- `/packets/claim` using queue service
- tests for feature order, wave order, packet order, degraded stop, backward compatibility, single concurrency

Actual diff also includes unrelated admin/auth/email/architect background work. That may be parallel work, but the report for this queue packet lists only queue files and does not mention those extra changes.

## Positive findings

- `QueueService.claim_next()` was added and `/packets/claim` now delegates to it.
- Feature activation is FIFO by `Feature.created_at ASC, Feature.id ASC`.
- Packet selection inside a wave is deterministic by `Packet.created_at ASC, Packet.id ASC`.
- `GRACE_MAX_CONCURRENCY=1` blocks claim when any packet is already `RUNNING`.
- Degraded states are detected and set the active feature to `degraded`.
- Tests cover basic feature FIFO, packet ordering, single concurrency, legacy `NOT_STARTED`, and feature done on `MERGED`.

## Blocking findings

### 1. `ACCEPTED` incorrectly counts as feature done

The handoff explicitly required feature completion to use the existing wave-gate meaning:

- successful terminal: `MERGED`
- intentionally skipped: `CANCELLED`

It explicitly said not to treat `FAILED`, `REJECTED`, `BLOCKED_*` as done. It did not allow `ACCEPTED` to complete the feature.

Current code includes `PacketState.ACCEPTED.value` in `TERMINAL_SUCCESS`:

```py
TERMINAL_SUCCESS = {
    PacketState.MERGED.value,
    PacketState.CANCELLED.value,
    PacketState.ACCEPTED.value,
}
```

That means a feature can become `done` before merge, allowing the queue to move to the next feature too early.

Required fix:

- remove `ACCEPTED` from `TERMINAL_SUCCESS`;
- add a test: all packets `ACCEPTED` must not mark feature `done` and must not start the next feature;
- preserve current merge/release pipeline semantics.

### 2. Later wave can be claimed while an earlier wave is not done

The claim loop picks the first wave that has a READY packet:

```py
for wave in waves:
    packet = query READY packet in wave
    if packet:
        return packet.id, "ok"
```

It does not verify that every earlier wave is `MERGED`/`CANCELLED` before considering later waves.

This violates the required rule: a later wave must not be claimable while an earlier wave has non-terminal packets.

Example failure case:

- Wave 1 has only `DRAFT` packet(s)
- Wave 2 has a `READY` packet due to data bug/manual edit/old data
- current code skips Wave 1 because it has no READY packet and claims Wave 2

Required fix:

- process waves sequentially;
- for each wave, first inspect all packets in that wave;
- if the wave has degraded packets, mark feature degraded;
- if the wave has READY packets, claim the earliest READY packet;
- if the wave is fully `MERGED`/`CANCELLED`, continue to next wave;
- otherwise stop with `waiting_for_wave_completion`.

Add tests:

- Wave 1 `DRAFT`, Wave 2 `READY` -> no claim, reason `waiting_for_wave_completion`.
- Wave 1 `ACCEPTED`, Wave 2 `READY` -> no claim unless policy explicitly treats accepted as merged, which it should not.
- Wave 1 `MERGED`, Wave 2 `READY` -> claim Wave 2.

### 3. Report is incomplete for actual diff

The report says files changed are only:

- `src/grace_control/services/queue_service.py`
- `src/grace_control/api/routers/packets.py`
- `tests/grace_control/services/test_queue_service.py`

Actual `19369e2..2d33c86` includes unrelated files such as admin, auth, email service, architect background tests, and UI JS.

Required fix:

- either split unrelated commits out of this queue packet, or
- update the report to clearly mark those changes as parallel/out-of-scope and confirm they were separately reviewed.

## Non-blocking findings

### `check_wave_gates()` still runs globally

The report correctly lists this as a known limitation. It is not a blocker for this packet if ordering is fixed, but future hardening should make wave gating active-feature aware.

### `_run_wave_gate()` swallows exceptions

Queue service catches any exception from `check_wave_gates()` and returns `0`. This avoids claim failure, but it can hide a broken wave gate and make claim decisions against stale states. Not a blocker if tests cover the corrected sequential wave logic, but it should eventually log the exception explicitly or return a reason.

## Final decision

**NEEDS_REWORK.**

The implementation is close, but the queue can currently advance too early because:

1. `ACCEPTED` is treated as feature completion.
2. later READY waves can be claimed while earlier waves are not done.

These are core ordering bugs, not polish issues.

## Minimal rework

1. Remove `ACCEPTED` from `TERMINAL_SUCCESS`.
2. Rewrite wave selection to stop at the first not-done wave.
3. Add tests for:
   - Wave 1 DRAFT + Wave 2 READY -> no claim.
   - Wave 1 ACCEPTED + Wave 2 READY -> no claim.
   - Wave 1 MERGED + Wave 2 READY -> claim Wave 2.
   - all ACCEPTED feature does not become done.
4. Update report with actual changed files or split unrelated changes.
5. Re-run queue tests and full relevant test suite.

## Expected re-review status after fixes

Likely PASS if the above is corrected and unrelated scope is either explained or split.
