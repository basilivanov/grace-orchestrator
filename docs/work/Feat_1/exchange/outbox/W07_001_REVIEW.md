---
feature_id: Feat_1
wave_id: W07
submission_attempt: 1
reviewer: active_reviewer_architect
decision: REWORK_REQUIRED
reviewed_commit: 2d858a0
created_at: 2026-06-16T00:00:00Z
---

# Review: W07 attempt 1

Decision: REWORK_REQUIRED

Reviewed submission: `docs/work/Feat_1/exchange/inbox/W07_001_SUBMISSION.md`
Reviewed commit: `2d858a0`

Good progress:

- Worker failure types were introduced.
- `ExecutionState` centralizes phase/release metadata.
- The worker loop is split into claim, execute, release, merge, and post-release phases.
- Merge failure now records an observable `packet_merge_failed` event with `action_required: true`.
- W07 tests cover much of the pure state/retry behavior.

Blocking issues:

1. Stale accepted release can still proceed to merge.

   `_run_one_cycle()` calls `_phase_release()` and then merges if `exec_state.release_status == "accepted"`.
   But `_phase_execute()` sets `exec_state.release_status` from the execution result before release.
   If an accepted result is later rejected by the API as stale lease, `_phase_release()` sets `failure_type = STALE_LEASE` but does not clear `release_status`, mark the state as abandoned, or otherwise prevent the merge branch.

   This violates the W01/W07 fencing invariant: stale release must be handled once and must not merge/retry/recover.

   Required fix:

   - On stale release, clear or replace `exec_state.release_status` so it cannot remain `accepted`.
   - Add an explicit `abandoned` / `stale_release` / `skip_merge` state flag, or make `_phase_release()` return a release outcome that `_run_one_cycle()` checks before merge.
   - Add a test that simulates accepted execution + stale release response and asserts `_phase_merge()` is not called.

2. Result-based failures are not classified in the active execution path.

   `classify_worker_failure(result=...)` exists, but `_phase_execute()` does not call it for normal non-accepted `ExecutionResult`s. It only sets `release_status = release_status_from_result(result)` and leaves `failure_type` unset.

   Consequences:

   - rejected agent results do not carry `failure_type=agent_nonzero` in `to_release_result()`;
   - scope violations may release as `blocked`, but `failure_type=scope_violation` and `retryable=false` are not included in the release result;
   - W07 classification exists mostly as helper/test behavior, not as active runtime metadata for result-based failures.

   Required fix:

   - In `_phase_execute()`, when `result.accepted` is false, set `exec_state.failure_type = classify_worker_failure(result=result)`.
   - Ensure scope violations release with `failure_type=scope_violation`, `retryable=false`.
   - Ensure generic non-accepted results release with `failure_type=agent_nonzero`, `retryable=true` when attempts remain.
   - Add tests for `_phase_execute()` or `_run_one_cycle()` proving these classifications are present in the release payload.

Required rework tests:

- `test_worker_stale_accepted_release_does_not_merge`
- `test_phase_execute_classifies_agent_nonzero_result`
- `test_phase_execute_classifies_scope_violation_result`
- `test_release_payload_includes_failure_type_and_retryable_for_result_failures`

Next submission: `docs/work/Feat_1/exchange/inbox/W07_002_SUBMISSION.md`.
