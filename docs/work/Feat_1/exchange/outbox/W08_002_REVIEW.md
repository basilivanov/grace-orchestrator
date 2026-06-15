---
feature_id: Feat_1
wave_id: W08
submission_attempt: 2
reviewer: active_reviewer_architect
decision: APPROVED
reviewed_commit: 315990a
created_at: 2026-06-16T00:00:00Z
---

# Review: W08 attempt 2

Decision: APPROVED

Reviewed submission: `docs/work/Feat_1/exchange/inbox/W08_002_SUBMISSION.md`
Reviewed commit: `315990a`

The W08 rework closes the blocker from `W08_001_REVIEW.md`.

Verified:

- `_scan_orphan_leases()` no longer relies on an incomplete hard-coded allowlist of non-running states.
- The scanner now applies the correct invariant: a lease is valid only while the packet state is `RUNNING`; any packet state other than `RUNNING` is treated as an orphan lease and cleaned.
- Cleanup still records `orphan_lease_cleaned`, clears the worker `current_packet_id`, deletes the lease, and increments the scanner count.
- Regression coverage was added for the previously missed `DRAFT` state.
- Regression coverage was added for the deprecated legacy `BLOCKED` state.
- Attempt 1 W08 behavior remains intact: stuck RUNNING recovery, stale worker deactivation, blocked/PLAN_FAILED diagnostics, guarded LLM repair, and startup scanner wiring.

Non-blocking notes carried forward:

1. `stuck_scan_loop()` is started in lifespan but not tracked/cancelled on shutdown. Existing background loops have similar behavior, so this remains non-blocking.
2. `_scan_stale_workers()` marks stale workers inactive but does not clear `current_packet_id` directly. The dangerous RUNNING+expired-lease path is handled, but some UI metadata may remain stale in edge cases.
3. `try_approve_or_repair_plan()` catches all `ValueError` from `approve_plan()` as compiler rejection. A future cleanup should distinguish compiler rejection from unrelated validation errors.

W08 is approved. Proceed to W09.
