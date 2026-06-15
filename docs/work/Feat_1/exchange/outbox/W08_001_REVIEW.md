---
feature_id: Feat_1
wave_id: W08
submission_attempt: 1
reviewer: active_reviewer_architect
decision: REWORK_REQUIRED
reviewed_commit: 67eb8c6
created_at: 2026-06-16T00:00:00Z
---

# Review: W08 attempt 1

Decision: REWORK_REQUIRED

Reviewed submission: `docs/work/Feat_1/exchange/inbox/W08_001_SUBMISSION.md`
Reviewed commit: `67eb8c6`

Good progress:

- `StuckScanner`/`run_stuck_scan()` was introduced and is defensive: individual scanner failures are caught and reported through counts/logging rather than crashing the whole sweep.
- Stuck RUNNING packets with expired/missing leases are moved back to READY and the stale lease/worker reference is cleaned.
- Stale workers are marked inactive.
- BLOCKED_RECOVERABLE and PLAN_FAILED repairable cases emit diagnostics rather than auto-applying unsafe repair.
- LLM repair guard defaults to disabled.
- Startup wiring adds `stuck_scan_loop()` to lifespan.
- The plan compiler rejection path in `try_approve_or_repair_plan()` is now reachable after `approve_plan()` raises on compiler rejection.

Blocking issue:

1. Orphan lease cleanup does not cover every non-RUNNING packet state.

   W08 requires detecting and cleaning the inconsistent state: `lease exists but packet not RUNNING`.
   The implementation uses a hard-coded allowlist of non-running states in `_scan_orphan_leases()`: READY, ACCEPTED, MERGED, REJECTED, FAILED, BLOCKED_FINAL, and BLOCKED_RECOVERABLE.

   But the canonical `PacketState` enum also contains non-running states that are not covered by this list:

   - `DRAFT`
   - deprecated alias `BLOCKED`
   - `CANCELLED`

   A lease attached to any of these states is still a lease for a non-RUNNING packet and should be cleaned by W08. Leaving these states uncovered means the scanner only partially implements the required invariant.

   Required fix:

   - Replace the hard-coded non-running allowlist with a simpler invariant check:

     ```python
     if packet and packet.state != PacketState.RUNNING.value:
         ... clean lease ...
     ```

   - Add regression coverage for at least one currently missed state. Prefer:
     - `test_lease_for_draft_packet_is_cleaned`
     - `test_lease_for_legacy_blocked_packet_is_cleaned`

Non-blocking notes:

1. `stuck_scan_loop()` is started in lifespan but not tracked/cancelled on shutdown. Existing background loops have similar behavior, so this does not block W08, but a future cleanup should track and cancel all startup tasks consistently.
2. `_scan_stale_workers()` marks stale workers inactive but does not clear `current_packet_id` directly. The RUNNING+expired-lease path handles the main dangerous case, but stale inactive workers may keep stale UI metadata in some edge cases.
3. `try_approve_or_repair_plan()` catches all `ValueError` from `approve_plan()` as compiler rejection. Future cleanup should distinguish compiler rejection from unrelated validation errors such as missing feature or invalid feature status.

Required next submission:

`docs/work/Feat_1/exchange/inbox/W08_002_SUBMISSION.md`
