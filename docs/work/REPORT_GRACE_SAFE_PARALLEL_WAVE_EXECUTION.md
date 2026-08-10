# Report: GRACE safe parallel wave execution

## SHAs

- Base SHA: `2071706929d776295647fa1b3699a75215b28112`
- Feature implementation SHA: `a8c1eb824dfa9857dfcec82da848b4d1e63924a9`

## Migration and upgrade path

The canonical Alembic chain remains:

`0001_grace_legacy_baseline` → `0002_safe_parallel_execution` →
`0003_serialized_merge` → `0004_stale_base_recheck`.

Production startup still resolves the database, detects an unversioned legacy
GRACE database, normalizes missing baseline tables/columns and canonical
indexes, stamps the baseline, then runs `alembic upgrade head`. A fresh
database is created through the same Alembic head path. Existing unversioned
and additive-column legacy fixtures were exercised by the migration test
suite.

No new ad-hoc SQLite migration or startup DDL was added in TZ006.

## Schema and contract state

TZ006 uses the existing `parallel_leases`, `merge_leases`,
`packet_runs.base_sha`, and `packet_runs.integration_base_sha` schema from
TZ03–TZ05. Runtime claim responses now carry the parallel lease identity and
expiry; merge requests carry the parallel lease fencing identity when issued
by a real worker. Packet and system diagnostics expose base SHA, integration
base SHA, lease holders, effective concurrency, recheck status, and typed
wait reasons.

The Architect/packet contract remains the TZ02 contract: current Architect
outputs must provide normalized `conflict_keys`, while saved legacy plans are
still normalized compatibly. No contract field was renamed in TZ006.

## Safe claim and conflict rules

When `GRACE_MAX_CONCURRENCY > 1`, the API selects `SafeQueueClaimService`.
The service opens one short SQLite `BEGIN IMMEDIATE` transaction, expires
reclaimable reservations, selects the earliest dependency-ready wave,
checks capacity and active scope/key reservations, claims the packet, creates
the ordinary packet lease and creates the parallel lease before commit.
SQLite lock contention is retried with bounded backoff.

The existing conservative `ParallelConflictService` remains the single
scope/key policy: normalized same paths, parent/child file-directory scopes,
directory overlap, glob overlap, and semantic `conflict_keys` intersections
serialize; uncertain overlap is treated as conflict. Dependency and wave
frontier waits leave the packet `READY` rather than failing it. Typed wait
observations include `waiting_for_dependency`,
`waiting_for_scope_conflict`, `waiting_for_conflict_key`,
`waiting_for_wave_completion`, and capacity waits.

## Worker, merge, and fencing integration

The real Worker claim path consumes the atomic claim DTO. One worker executes
one active packet; parallelism is obtained from multiple worker processes/tasks
and the effective `GRACE_MAX_CONCURRENCY`. Supervisor startup/restart and API
claim paths fail closed with a typed `parallel_safety_disabled` reason when a
required multi-worker guard is disabled.

After an accepted result, the ordinary packet lease is released but the
parallel lease is retained. Worker heartbeats renew the retained parallel
lease and the merge request carries its exact lease ID and `claimed_attempt`.
Merge rechecks that identity immediately before each target-repository
mutation, so a stale worker cannot continue after fencing.

`MergeCoordinatorService` remains the DB-backed serialized mutation boundary:
one active merge lease per normalized target repository, deterministic accepted
order, fencing before each checkout/fetch/merge/push, and repo sanity checks
before expired-lease takeover. Merge-slot contention is a typed
`waiting_for_merge_slot` wait and is persisted for diagnostics. Text merge
conflicts are aborted under the current merge lease, recorded as
`merge_conflict`, and leave the packet recoverably blocked.

Stale-base packets continue through the TZ05 current-head integration recheck.
Clean rechecks persist `integration_base_sha`; stale conflicts and failed
combined-state verification persist their failure class and evidence without
mutating the target branch.

Cleanup now handles ordinary packet lease recovery, associated parallel lease
release, expired merge lease recovery only after repository sanity, and
abandoned accepted packets whose parallel lease expired before merge. Worktree
cleanup keeps a registered/live packet worktree when ownership cannot be
proven orphaned; it does not use a blind target-repository reset.

## Tests and results

- `tests/test_tz06_multiworker_integration.py`: **5 passed**. This uses a
  file-backed SQLite database, the real FastAPI claim/release/renew/diagnostic
  routes, five real Worker-cycle/runtime checks, and stale accepted-packet
  cleanup.
- TZ03/TZ04/TZ05 plus TZ006, worker, cleanup, diagnostics, supervisor, and
  crash integration set: **70 passed**.
- Alembic/database schema, packet executor, and real recovery set: **82
  passed**.
- `python3 -m py_compile` on all changed Python modules and the TZ006 test:
  **PASS**.
- `python3 scripts/grace_lint.py tests/test_tz06_multiworker_integration.py
  --quiet`: **PASS**.
- `ruff check tests/test_tz06_multiworker_integration.py` and targeted changed
  runtime modules: **PASS** where the existing legacy files are lint-clean.
- `git diff --check`: **PASS**.

The repository still contains pre-existing canon/lint debt in older large
modules and unrelated legacy admin/API tests that assert obsolete behavior;
those files were not broadened as part of TZ006.

## Multi-worker smoke proof

Four artificially slow independent packets use a delay of approximately
80 ms. The test records monotonic start/end timestamps for every real Worker
execution and asserts that at least one later packet starts before an earlier
packet finishes. The observed run completed in approximately 1.8 seconds
including database setup, while the packet execution intervals overlap; the
proof is timestamp-based and has no machine-specific absolute performance
threshold. Parallel lease retention/renewal and the concurrency=1 legacy
queue behavior are covered by the TZ03/TZ006 regression tests.

## Known limitations

- The TZ006 smoke fixture uses real Worker tasks with an ASGI-backed control
  plane; full OS-level Supervisor spawning is covered by the existing
  Supervisor integration tests rather than by a long-lived multi-process
  performance test.
- The merge and stale-base suites use deterministic Git doubles and isolated
  repositories to make race/fencing outcomes reproducible; production uses the
  same coordinator and integration-recheck services.
- Existing unrelated admin/UI legacy assertions remain outside this scope.
