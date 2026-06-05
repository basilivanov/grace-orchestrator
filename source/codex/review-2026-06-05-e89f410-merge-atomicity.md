# Review: `e89f410` merge atomicity fix

Date: 2026-06-05
Reviewed commit: `e89f410d309c4a1b576c73d6a46663d5693e4400`
Previous finding: `source/codex/review-2026-06-05-5198516-followup.md`

## Verdict

Approved. The remaining merge atomicity blocker is fixed.

`MergeService.merge_packet()` now treats `PacketService.transition(..., PacketState.MERGED)` failure as a failed merge result instead of falling through to `success=True`.

This closes the last open runtime correctness finding from the post-refactor audit.

## What was checked

### 1. Service-level behavior

Current behavior:

```python
try:
    await svc.transition(
        packet_id, PacketState.MERGED, reason=f"merge_complete:{commit_sha[:8]}",
    )
except Exception as e:
    _log.warn("merge_state_transition_failed", ...)
    return MergeResult(
        False, packet_id, commit_sha, str(repo), branch_name, target_branch,
        error=f"state transition failed: {str(e)[:200]}",
    )
```

This is correct for the current contract:

- git merge/push may already have landed;
- `commit_sha` is preserved for operator/debug visibility;
- service reports `success=False` if DB state is not updated;
- caller can surface the split-brain risk as a 409 instead of a false 200.

### 2. API behavior

`/api/packets/{packet_id}/merge` now:

- sees `result.success == False`;
- best-effort records `packet_merge_failed` without letting observability failures mask the real response;
- raises HTTP 409 with `detail.merge_failed` and `packet_id`.

This is the correct API-level behavior.

### 3. Tests

Two regression tests were added:

- `test_followup_5198516_merge_fails_when_transition_fails`
- `test_followup_5198516_merge_router_returns_409_on_transition_failure`

They cover the exact failure mode from the previous review:

- transition raises;
- service result is failed;
- SHA is preserved;
- packet remains `ACCEPTED`;
- API returns 409.

## Minor notes / not blockers

1. The merge router still returns hardcoded `"state": "merged"` on success. It is acceptable after service success, but later it would be cleaner to read the persisted packet state or include confirmed state in `MergeResult`.
2. Event recording in the router is best-effort and duplicated with service/event layers. This is acceptable short-term, but should be centralized during the API/service cleanup wave.
3. The code now correctly handles the old critical split-brain case, but future merge design may want an explicit `MERGED_GIT_ONLY` / reconciliation state if git push succeeds and DB transition fails.

## Status

No blocker remains from the previous merge atomicity review.

Proceed to the next roadmap wave:

1. API-first contract + CLI inventory.
2. Trace/observability API.
3. CLI runtime removal.
4. Hardcode/config cleanup.
5. Stronger GraceLint executable canon.
