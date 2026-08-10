# Task 006 — Full multi-worker integration + observability

## Source of truth

Implement:

`docs/work/TZ_GRACE_PARALLEL_06_MULTIWORKER_INTEGRATION.md`

Master spec for ambiguous details:

`docs/work/TZ_GRACE_SAFE_PARALLEL_WAVE_EXECUTION.md`

Depends on accepted TZ01–TZ05 implementation already present on `main`.

## Reviewer constraints

1. This is the final integration stage: wire and prove the accepted TZ03/TZ04/TZ05 mechanisms in the real worker/supervisor runtime; do not replace them with parallel mock-only paths.
2. One worker remains one active packet. Parallelism comes from multiple worker processes/tasks plus `GRACE_MAX_CONCURRENCY`; do not make one worker concurrently execute multiple coder packets.
3. Preserve `GRACE_MAX_CONCURRENCY=1` as the backward-compatible default and regression baseline.
4. Unsafe multi-worker execution must fail closed or be explicitly prevented when merge serialization / required safety guards are disabled. Do not allow `max_concurrency > 1` to silently bypass TZ03/TZ04/TZ05 protections.
5. Real runtime claim path must use `SafeQueueClaimService` for parallel mode and preserve the accepted atomic SQLite claim semantics, scope/key guards, dependency/wave rules, fencing and capacity checks.
6. Real merge path must use `MergeCoordinatorService`, deterministic merge order, heartbeat/fencing and TZ05 stale-base integration recheck exactly as accepted in prior stages.
7. Keep stale/crash recovery state-aware and fenced: packet lease recovery, parallel lease reclaim, merge lease takeover only after repo sanity, and no cleanup of another live worker's worktree.
8. Surface typed wait/failure reasons at least for dependency, scope conflict, conflict key, merge slot, wave completion, parallel lease lost, merge lease lost, stale-base conflict, integration verification failure and merge conflict. Expected WAIT conditions must not become manual-failure states.
9. Add minimal diagnostics/API observability for effective concurrency, active workers, active parallel leases, active merge holder, packet base/integration SHA, current wait reason and integration recheck result. No large admin UI redesign.
10. End-to-end concurrency tests must use a real file-backed SQLite database and genuinely concurrent workers/tasks. Do not prove this only with sequential mocks.
11. Prove 4–8 disjoint same-wave packets can overlap in RUNNING/execution while same/overlapping scope and same conflict key serialize.
12. Prove a dependent consumer cannot start before producer MERGED and then starts from the fresh target base.
13. Prove multiple ACCEPTED packets never overlap target-repo merge mutations, while different execution worktrees may run concurrently.
14. Prove an independently stale packet performs TZ05 recheck before merge; conflict or combined-state verification failure leaves target unchanged.
15. Prove crash/expired lease recovery cannot produce double claim or double merge and stale fencing tokens cannot mutate state.
16. Add a reproducible slow-packet smoke/performance proof using overlap/timestamps rather than a brittle CI wall-clock threshold; merge mutations must remain non-overlapping.
17. Create the final report required by TZ06: `docs/work/REPORT_GRACE_SAFE_PARALLEL_WAVE_EXECUTION.md`, including base/final SHA, migrations/schema, Architect contract changes, claim algorithm, conflict rules, merge serialization, stale-base behavior, test results, concurrency proof, known limitations and confirmation that no new ad-hoc SQLite schema mutations were added.
18. Do not add unrelated redesigns, speculative dependency execution, shared wave worktrees or LLM merge-conflict resolution.

## Required regressions

Run TZ06 end-to-end tests plus relevant TZ05/TZ04/TZ03, worker/supervisor, queue/lease/recovery, migrations/schema, workspace/packet-executor, merge/acceptance and `GRACE_MAX_CONCURRENCY=1` regressions.

Also run Ruff, `python3 -m py_compile`, applicable `grace_lint.py`, and `git diff --check`.

## Required result

Commit and push the implementation and final report.

Then create:

`docs/work/agent_exchange/outbox/006_SUBMISSION.md`

Keep the submission short:

- implementation commit SHA;
- what was wired/proven;
- tests/checks run and results;
- smoke/concurrency proof summary;
- any known limitation or deviation from TZ06.

Do not start any follow-up task until reviewer returns `ACCEPT 006`.
