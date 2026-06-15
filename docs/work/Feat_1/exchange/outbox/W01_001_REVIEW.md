---
feature_id: Feat_1
wave_id: W01
submission_attempt: 1
reviewer: active_reviewer_architect
decision: REWORK_REQUIRED
reviewed_commit: 6815d9cc3f445d55822ed68c01d813399369f5ec
created_at: 2026-06-15T00:00:00Z
---

# Review: W01 Runtime Safety — Lease Fencing, Renewal, and Retry Semantics

## Decision

REWORK_REQUIRED

## Summary

W01 is moving in the right direction and includes the right primitives: `lease_id`, `claimed_attempt`, a renew endpoint, retryable timeout path, scanner logging, and focused tests.

However, the current implementation does **not** yet satisfy the W01 acceptance criteria. There are several P0/P1 blockers that either bypass fencing entirely or break the real worker/API path.

The most important issue: the implementation is stricter in service-level tests than in the actual API/worker path. Direct `PacketService.claim()` tests pass, but the real `/api/packets/claim` response does not return `claimed_attempt`, and `/api/packets/{id}/release` accepts missing fencing tokens. This means the production path is not yet safely fenced.

## Blocking Issues

### P0-1 — Release fencing is bypassable when tokens are omitted

`release_packet()` says `worker_id`, `lease_id`, and `claimed_attempt` are required, but it reads them with `request.get(...)` and passes missing values through to `PacketService.release()`.

In `PacketService.release()`, checks are conditional:

```python
if worker_id and lease.worker_id != worker_id:
    ...
elif lease_id is not None and lease.id != lease_id:
    ...
elif claimed_attempt is not None and lease.claimed_attempt != claimed_attempt:
    ...
```

If the caller omits all tokens while a lease exists, no fencing check fails and the packet can transition.

This violates W01 directly:

> Release must require matching `worker_id`, `lease_id`, and `claimed_attempt`.

Required fix:

- API must reject missing `worker_id`, `lease_id`, or `claimed_attempt` with 422 before calling service.
- Service must also fail closed if lease exists and any fencing token is missing.
- Remove/limit backward-compatible release without tokens from executable packet path.
- Add tests:
  - release with existing lease and missing `lease_id` -> rejected;
  - release with existing lease and missing `claimed_attempt` -> rejected;
  - release with existing lease and missing `worker_id` -> rejected;
  - no packet state mutation in all cases.

### P0-2 — Real claim API does not return `claimed_attempt`

`PacketService.claim()` returns `claimed_attempt`, but `/api/packets/claim` response does not include it in `data`.

The worker API model has:

```python
claimed_attempt: int = 0
```

So the real worker path will default to `0`, then release with `claimed_attempt=0`. For actual claims, service-level tests show `claimed_attempt` should be `1`, `2`, etc. The release can therefore fail for normal worker execution.

Required fix:

- Add `"claimed_attempt": result.claimed_attempt` to claim response.
- Prefer making `claimed_attempt` required in the worker `PacketClaim` model instead of defaulting to `0`.
- Add API-level test that `/api/packets/claim` returns `claimed_attempt` and worker release succeeds using the returned claim.

### P0-3 — Stale release can still proceed to merge in worker success path

`_release_with_fencing()` catches stale release / 409 and returns:

```python
{"data": {"packet_id": packet_id, "stale_lease": True, "released": False}}
```

But `_main_loop()` ignores that return value. If `status == "accepted"`, it proceeds to merge after `_release_with_fencing(...)` even if release was stale and returned `released: False`.

This violates the W01 rule:

> If release returns stale/409, worker must abandon that packet result.

Required fix:

- `_release_with_fencing()` should either raise a typed `StaleLeaseError` / `StaleReleaseError` to caller, or return a typed result that caller must check.
- `_main_loop()` must not merge, retry, or recovery-handle if release did not actually succeed.
- Add test: accepted execution + stale release -> no merge call.

### P1-1 — Tests cover service path but miss API/worker integration path

The new tests are useful, but most critical regressions are not covered:

- `/api/packets/claim` omits `claimed_attempt`;
- `/api/packets/{id}/release` accepts missing fencing tokens;
- worker ignores stale release result and can proceed to merge;
- API/client roundtrip does not prove real worker release succeeds.

Required tests:

1. API claim returns `claimed_attempt`.
2. API release with missing tokens returns 422/409 and does not mutate packet.
3. Worker claim -> execute accepted -> release with returned tokens works end-to-end.
4. Worker accepted result + stale release does not call merge.

### P1-2 — No CI evidence attached to submission

Commit message says tests were added, but no workflow runs were found for the commit and no command output was provided in a submission file.

Required fix:

- Add `docs/work/Feat_1/exchange/inbox/W01_002_SUBMISSION.md` with test output.
- Include either full suite output or targeted test output with reason full suite was not run.

### P2 — `lease_expiration_grace_seconds` is added but not used

Settings include `lease_expiration_grace_seconds`, but scanner uses direct expiration comparison. This is not a release blocker by itself, but either use the setting or remove it to avoid misleading config.

## Positive Findings

- The design now has a `StaleLeaseError` and event logging for stale release attempts.
- Lease renewal endpoint exists.
- Hardcoded destructive worktree cleanup was removed from the lease scanner.
- Timeout path was changed from terminal `failed` to retryable `rejected` in the worker.
- Direct service-level stale reclaim scenario is covered by tests.

## Required Rework for W01_002

1. Make release fail closed:
   - API requires `worker_id`, `lease_id`, `claimed_attempt`.
   - Service rejects missing tokens when a lease exists.
   - No backward-compatible tokenless release for active leased packets.

2. Fix claim API/client contract:
   - claim response includes `claimed_attempt`.
   - client model requires it instead of defaulting to `0`.

3. Fix worker stale release handling:
   - stale release aborts post-release flow;
   - no merge after stale release;
   - no retry/recovery after stale release unless explicitly safe.

4. Add API/worker integration tests:
   - claim response contains fencing tokens;
   - release missing tokens rejected;
   - real worker happy path can release;
   - stale accepted release does not merge.

5. Provide evidence file:
   - create `docs/work/Feat_1/exchange/inbox/W01_002_SUBMISSION.md`;
   - include changed files, tests run, and remaining limitations.

## Acceptance for Next Review

W01_002 can be approved if:

- stale worker cannot mutate packet state with old or missing tokens;
- release without tokens is impossible for leased RUNNING packet;
- worker gets `claimed_attempt` from actual API claim response;
- stale release does not trigger merge;
- API/worker integration tests prove the real path, not only direct service calls;
- test evidence is included in the submission.

## Final Decision

REWORK_REQUIRED
