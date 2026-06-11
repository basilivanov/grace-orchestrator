# Review: GRACE single-feature FIFO queue discipline rework

**Review status:** PASS_WITH_NOTES
**Date:** 2026-06-12

## Reviewed refs

- Previous reviewed head: `2d33c86`
- Reviewed rework head: `f6897bc`

## Scope reviewed

Primary reviewed files:

- `src/grace_control/services/queue_service.py`
- `tests/grace_control/services/test_queue_service.py`
- `docs/work/REPORT_GRACE_QUEUE_DISCIPLINE_SINGLE_FEATURE_FIFO.md`

The diff also contains small unrelated admin/architect/UI changes. Those are treated as parallel/out-of-scope for this queue review.

## Blocker re-check

### PASS: `ACCEPTED` no longer completes a feature

`TERMINAL_SUCCESS` now contains only:

- `MERGED`
- `CANCELLED`

`ACCEPTED` was removed. This matches the handoff policy: accepted packet is not enough to advance the feature queue before merge.

### PASS: later waves cannot be claimed before earlier waves complete

Wave selection now iterates waves in order and inspects each wave before moving on:

- if degraded packet exists, feature becomes `degraded`;
- if READY exists in the current earliest not-done wave, claim earliest READY packet;
- if current wave is not fully `MERGED`/`CANCELLED`, return `waiting_for_wave_completion`;
- only if current wave is fully done does queue continue to the next wave.

This closes the bug where Wave 2 READY could be claimed while Wave 1 was still DRAFT or ACCEPTED.

### PASS: rework tests added

Added tests cover:

- Wave 1 DRAFT + Wave 2 READY -> no claim.
- Wave 1 ACCEPTED + Wave 2 READY -> no claim.
- Wave 1 MERGED + Wave 2 READY -> claim Wave 2.
- All ACCEPTED feature -> not feature_done.

These directly cover the previous blocker cases.

## Remaining notes

### Report test count is stale

The report still says `Tests (13)`, but it now lists the four new tests too, so the count should be updated to 17.

This is a documentation nit, not a functional blocker.

### Report still under-reports actual diff scope

The final queue report lists only queue files, while the broader diff includes small admin/architect/UI changes. This is acceptable only if those are acknowledged as parallel work or reviewed separately.

This is not blocking the queue discipline PASS, but it should be cleaned up in future reports to avoid confusing reviewers.

### Global wave gate remains a known limitation

`check_wave_gates()` still runs globally, not active-feature-only. The report lists this as a known limitation. It is acceptable for this packet because the corrected queue selection prevents later waves from being claimed early.

## Final decision

**PASS_WITH_NOTES.**

Queue discipline now satisfies the intended MVP policy:

1. single active feature under `GRACE_MAX_CONCURRENCY=1`;
2. feature FIFO by creation order;
3. wave-by-wave progression;
4. deterministic packet order inside wave;
5. degraded feature blocks queue;
6. accepted-but-not-merged work does not advance the queue.

## Suggested follow-up

- Update report heading from `Tests (13)` to `Tests (17)`.
- Keep unrelated admin/architect/UI changes out of queue-discipline reports or explicitly mark them as parallel scope.
- Later hardening: active-feature-only `check_wave_gates()` and stale lease cleanup.
