# Task 003 — Safe atomic claim + parallel leases

## Source of truth

Implement:

`docs/work/TZ_GRACE_PARALLEL_03_SAFE_ATOMIC_CLAIM.md`

Master spec for ambiguous details:

`docs/work/TZ_GRACE_SAFE_PARALLEL_WAVE_EXECUTION.md`

Depends on accepted TZ01 + TZ02 implementation already present on `main`.

## Reviewer constraints

1. Do not implement TZ04 merge serialization or TZ05 stale-base integration recheck in this task.
2. `ParallelConflictService` must be the canonical runtime scope/key conflict implementation for parallel claims.
3. Scope overlap must cover at minimum:
   - same file;
   - file vs parent directory;
   - parent/child directories;
   - normalized equivalent paths;
   - conservative glob/pattern overlap;
   - uncertain overlap => conflict/serialize;
   - disjoint paths => safe.
4. Do not rely on the old DAG validator's exact-string set intersection as the runtime safety mechanism.
5. Candidate selection + dependency/wave/capacity/conflict checks + normal packet claim/lease + parallel lease acquisition must be one short atomic DB operation for parallel mode.
6. SQLite concurrency test must use a real file-backed SQLite DB and real concurrent claim attempts, not only sequential mocks.
7. `GRACE_MAX_CONCURRENCY=1` regression must remain green.
8. Parallel lease must not be released merely because packet becomes `ACCEPTED`; it remains held until the lifecycle point defined in TZ03/master spec.
9. New DB schema must be added only through a new Alembic revision; do not add new ad-hoc startup DDL.

## Required result

Run targeted tests plus relevant regressions, Ruff and repository checks applicable to changed files.

Commit and push the implementation.

Then create:

`docs/work/agent_exchange/outbox/003_SUBMISSION.md`

Keep the submission short:

- commit SHA;
- what changed;
- tests/checks run and results;
- any known limitation or deviation from TZ03.

Do not start Task 004 until reviewer returns `ACCEPT 003`.