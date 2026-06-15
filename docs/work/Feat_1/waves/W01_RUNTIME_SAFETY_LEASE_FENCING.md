# W01 — Runtime Safety: Lease Fencing, Renewal, and Retry Semantics

Status: APPROVED

Parent TZ: `docs/work/TZ_GRACE_ORCHESTRATOR_RUNTIME_SCOPE_CONTEXT_HARDENING.md`

## Goal

Make packet execution ownership safe. A stale worker must not mutate packet state after lease expiry or reclaim by another worker.

## Scope

- `src/grace_control/services/packet_service.py`
- `src/grace_control/api/routers/packets.py`
- `src/grace_control/api/routers/workers.py`
- `src/grace_control/worker/api_client.py`
- `src/grace_control/worker/worker.py`
- `src/grace_control/core/lease_manager.py`
- `src/grace_control/core/queue_service.py`
- `src/grace_control/config/settings.py`
- `src/grace_control/db/`
- `tests/`

## Tasks

1. Add lease fencing to claim/release.
2. Require `worker_id`, `lease_id`, and `claimed_attempt` for leased packet release.
3. Add active lease renewal.
4. Make timeout/runtime failures retryable when attempts remain.
5. Harden lease expiration scanner and remove destructive hardcoded cleanup.
6. Add stale worker reclaim regression tests.

## Acceptance

- Stale worker cannot release after lease expiry/reclaim.
- Release requires matching worker, lease, and attempt.
- Worker renews lease during long execution.
- Timeout with attempts remaining is retryable, not terminal `FAILED`.
- Scanner behavior is observable.

## Verification

```bash
python3 -m pytest tests/test_w01_lease_fencing.py -q
```

## Review outcome

W01 was approved after rework. See:

- `docs/work/Feat_1/exchange/outbox/W01_001_REVIEW.md`
- `docs/work/Feat_1/exchange/outbox/W01_002_REVIEW.md`
