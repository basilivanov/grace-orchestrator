# Task 004 — Serialized merge coordinator

## Source of truth

Implement:

`docs/work/TZ_GRACE_PARALLEL_04_SERIALIZED_MERGE.md`

Master spec for ambiguous details:

`docs/work/TZ_GRACE_SAFE_PARALLEL_WAVE_EXECUTION.md`

Depends on accepted TZ01 + TZ02 + TZ03 implementation already present on `main`.

## Reviewer constraints

1. Do not implement TZ05 stale-base combined-state/integration recheck in this task.
2. Add `merge_leases` only through a new Alembic revision and matching ORM model; do not add ad-hoc startup DDL.
3. Merge coordination must be DB-backed. A process-local `asyncio.Lock`/thread lock may be supplementary only, never the correctness mechanism.
4. `target_repo_key` must deterministically identify one logical target repository so aliases/path spellings cannot accidentally bypass serialization.
5. Same target repo: only one holder may perform checkout/merge/push mutation at a time. Different target repos may proceed concurrently.
6. Fencing must protect the mutation itself, not merely lease acquisition: after lease/token loss, a stale holder must not be allowed to continue the next target-mutating step.
7. Expired-lease takeover must perform repo sanity checks first (expected repo root, clean/known state, `MERGE_HEAD` or merge-in-progress detection). Do not blind reset/abort another holder's state.
8. Deterministic accepted merge order for one repo must be `Wave.order`, then `Packet.created_at`, then `Packet.id`.
9. Do not require the whole wave to finish before an accepted independent packet may enter the merge queue.
10. Preserve TZ03 lifecycle: parallel resource lease remains held through ACCEPTED and is released only after successful MERGED or the already-defined failure/cancel/recovery policy.
11. Keep `GRACE_MAX_CONCURRENCY=1` behavior compatible.

## Required tests

At minimum prove:

- two ACCEPTED packets for the same target repo cannot concurrently mutate it;
- the second waits without checkout/index/push mutation;
- different target repos may merge concurrently;
- stale fencing token cannot continue mutation;
- expired merge lease takeover succeeds only after repo sanity passes;
- dirty/in-progress merge state is not blindly reset during takeover;
- deterministic merge order is enforced;
- successful MERGED releases the packet's TZ03 parallel lease, not before.

Prefer a test that instruments/records the actual target-mutating git steps so concurrency safety is demonstrated rather than inferred only from lease rows.

## Required result

Run targeted TZ04 tests plus relevant TZ03/merge/migration/schema regressions, Ruff, `python3 -m py_compile`, repository lint applicable to changed files, and `git diff --check`.

Commit and push the implementation.

Then create:

`docs/work/agent_exchange/outbox/004_SUBMISSION.md`

Keep the submission short:

- commit SHA;
- what changed;
- tests/checks run and results;
- any known limitation or deviation from TZ04.

Do not start Task 005 until reviewer returns `ACCEPT 004`.