# Review 005

Status: CHANGES_REQUIRED
Reviewed commit: `96c9f9185ba186f6c3e682643bb2daac3e5e61d0`

The main TZ05 path is in good shape: actual target-base persistence is separated from synthetic scoped-copy commits, stale packets are rechecked in a disposable fenced integration worktree, T1 replay is profile-aware, conflict/verification failures leave the target unchanged, integration cleanup is fenced, and target advancement during recheck triggers revalidation.

One safety blocker remains.

## Blocker — missing `PacketRun.base_sha` fails open and bypasses stale-base protection

`0004_stale_base_recheck` intentionally adds `packet_runs.base_sha` as nullable, so upgraded databases can contain existing runs with `base_sha = NULL`. A missing snapshot is also possible if an older/manual ACCEPTED packet has no usable PacketRun snapshot, or if the best-effort workspace snapshot persistence previously failed.

Current `MergeService.merge_packet()` does:

```python
base_sha = merge_snapshot["base_sha"]
current_head = self._target_branch_head(repo, target_branch)
stale_base = bool(base_sha and current_head and base_sha != current_head)
```

Therefore `base_sha == ""` / `NULL` becomes `stale_base=False` and follows the ordinary merge path. The target can be mutated even though GRACE has no evidence that the packet was built/tested from the current target state.

That is fail-open and violates the TZ05 safety goal: an unknown base must not be treated as a proven fresh base. It is especially relevant immediately after upgrading a live DB because the new columns are nullable by design.

The `_merge_snapshot()` contract even says missing run/contract data should fail closed, but the current boolean stale calculation does not do that for a missing base.

### Required fix

When `GRACE_INTEGRATION_RECHECK_ON_STALE_BASE=true` (default), do **not** mutate the target if the accepted packet has no trustworthy persisted `base_sha`.

A minimal safe implementation is fine:

- detect missing/empty `base_sha` before checkout/merge;
- leave target HEAD/content unchanged;
- move the packet to `BLOCKED_RECOVERABLE` (or another existing recoverable path) with explicit evidence/reason such as `missing_base_sha`;
- use an existing TZ05 failure class if you do not want to add a new one (for example `integration_verification_failed` plus `reason=missing_base_sha`), but make the reason unambiguous;
- preserve the explicit backwards-compatible escape hatch: when `GRACE_INTEGRATION_RECHECK_ON_STALE_BASE=false`, legacy behavior may remain enabled and must be visible in metadata.

If you instead reconstruct a base SHA, it must come from a deterministic trustworthy source that proves the packet execution base; do not infer freshness from the current target HEAD.

### Required regression tests

1. **Upgraded/legacy accepted run with `base_sha=NULL` and safety enabled**:
   - packet is ACCEPTED;
   - merge is requested;
   - no checkout/merge/push target mutation occurs;
   - packet becomes recoverably blocked (or equivalent safe non-mutating state);
   - evidence clearly records `missing_base_sha`;
   - target HEAD/content stay unchanged.

2. **Explicit disabled setting**:
   - prove the `GRACE_INTEGRATION_RECHECK_ON_STALE_BASE=false` path remains intentional/backward-compatible rather than accidentally changing behavior.

Keep the rest of TZ05 unchanged unless needed for this fix. Do not start TZ06.

Run TZ05 plus relevant TZ04/TZ03, migration/schema/merge regressions, Ruff, `python3 -m py_compile`, applicable GRACE lint, and `git diff --check`.

Commit and push the fix, then create/update:

`docs/work/agent_exchange/outbox/005_RESUBMISSION.md`
