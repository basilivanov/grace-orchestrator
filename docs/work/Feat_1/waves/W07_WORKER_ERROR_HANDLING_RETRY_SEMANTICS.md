# W07 — Worker Error Handling and Retry Semantics

Status: READY

Parent TZ: `docs/work/TZ_GRACE_ORCHESTRATOR_RUNTIME_SCOPE_CONTEXT_HARDENING.md`

## Goal

Make worker execution flow explicit, observable, and retry-safe. Remove dead exception paths and ambiguous runtime state handling.

## Scope

- `src/grace_control/worker/worker.py`
- `src/grace_control/worker/api_client.py`
- `src/grace_control/services/packet_service.py`
- `src/grace_control/api/routers/packets.py`
- `tests/`

## Tasks

1. Refactor worker loop into clear phases: claim, execute, release, merge, post-release retry/recovery.
2. Replace ad-hoc `status` handling with an execution state object.
3. Classify failure types:
   - `agent_timeout`
   - `agent_nonzero`
   - `scope_violation`
   - `worktree_preflight_failed`
   - `stale_lease`
   - `api_error`
4. Runtime exceptions with attempts remaining should release as retryable, not terminal failed.
5. Merge failure should record explicit event/state for manual action.
6. Remove duplicate/dead `except Exception` and broad silent release failures.

## Acceptance

- Worker timeout goes to retryable status when attempts remain.
- Generic agent failure is retryable when safe.
- Stale release is handled once and not retried blindly.
- Merge failure is observable.
- No dead duplicate exception branch remains.

## Required tests

- `test_worker_timeout_releases_retryable_status`
- `test_worker_generic_agent_failure_rejected_not_failed_when_retryable`
- `test_worker_stale_lease_release_does_not_loop_forever`
- `test_worker_dead_except_removed_or_unreachable_tested`
- `test_merge_failure_records_action_required_event`

## Submission

Create `docs/work/Feat_1/exchange/inbox/W07_001_SUBMISSION.md` when done.
