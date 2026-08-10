# Report: GRACE safe parallel wave execution

## SHAs

- Base SHA: `2071706929d776295647fa1b3699a75215b28112`
- Feature implementation SHA: `a8c1eb824dfa9857dfcec82da848b4d1e63924a9`
- Review fix SHA: `22766e56d1a9942cc9a024d395963a8d2c6632ee`

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

The review fix makes this cleanup decision fail closed for both database
initialization errors and ownership-query errors. In effective parallel mode,
an ACCEPTED packet also cannot enter merge coordination without its exact
`parallel_lease_id` and `claimed_attempt`; missing, stale, or wrong identity
returns typed `parallel_lease_lost` before target checkout, merge, or push.

## Tests and results

- `tests/test_tz06_multiworker_integration.py`: **12 passed**. The final suite
  uses file-backed SQLite, concurrent real Worker tasks through the FastAPI
  claim/release/merge routes, isolated real git worktrees and commits, and
  timestamp assertions for overlapping execution plus non-overlapping target
  checkout/merge/push mutations. It covers disjoint overlap, same-scope and
  same-key waits with later progress, dependency-to-MERGED/fresh-base order,
  stale-base clean/conflict/verification paths, crash/expiry recovery,
  parallel fencing, diagnostics, and the concurrency=1 contender path.
- TZ03/TZ04/TZ05 plus TZ006, worker, cleanup, diagnostics, supervisor, and
  crash integration set: **80 passed**.
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

Four independent packets run through concurrent real Worker cycles against a
file-backed SQLite database. Each test executor creates a real isolated git
worktree and commit. Monotonic execution intervals overlap, while an
instrumented real `GitService` records target checkout/fetch/merge/push and
worktree mutation intervals and asserts they do not overlap. Later packets
exercise the stale-base integration recheck and still merge cleanly; the
target repository contains all four packet files and every packet ends in
`MERGED`. Parallel lease retention/renewal, typed waits, crash recovery, and
the concurrency=1 legacy queue behavior are covered by the same final suite.

## Known limitations

- The TZ006 proof uses real Worker tasks with an ASGI-backed control plane and
  real git repositories; full OS-level Supervisor spawning remains covered by
  the existing Supervisor integration tests rather than a long-lived
  multi-process performance test.
- Earlier TZ03/TZ04/TZ05 regression suites still use deterministic Git doubles
  where reproducibility is useful; the final TZ006 merge/stale-base proof uses
  the production coordinator and integration-recheck services with real git.
- Existing unrelated admin/UI legacy assertions remain outside this scope.
