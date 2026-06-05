# Review: post-refactor audit after 9 main commits

Date: 2026-06-05
Repo: basilivanov/grace-orchestrator
Scope: audit after the recent P0/P1/P2 refactor commits pushed to `main`.

## Summary

The refactor moved the project in the right direction:

- P0 stability work exists: `BLOCKED` was split into recoverable/final states; dashboard `PacketRun` import was fixed; artifact read endpoint now has a resolve-based traversal guard.
- Settings consolidation started via `src/grace_control/config/settings.py`.
- `PacketService` was introduced as intended single owner of state transitions.
- Merge logic was extracted into `MergeService` + `GitService`.
- Legacy execution is now behind an `ExecutionBackend` protocol and `LegacyPrefectBackend`.
- `packet_executor.py` was partially split with `PacketMaterializer` and `EvidenceService`.

However, the current `main` has several high-risk regressions. Fix these before doing the next broad refactor wave.

---

## P0 / Blockers

### 1. MergeService does not transition packet to MERGED

**Severity:** blocker

`MergeService.merge_packet()` calls:

```python
await svc.transition(packet_id, target_state=None, reason=f"merge_complete:{commit_sha[:8]}")
```

But `PacketService.transition()` signature is:

```python
async def transition(self, packet_id: str, to_state: PacketState, *, reason: str = "", db=None)
```

So the call uses a non-existing keyword argument and passes no `PacketState.MERGED`. The exception is swallowed and only logged as `merge_state_transition_failed`. The router then returns `state: "merged"`, but the DB row can remain `accepted`.

**Required fix:**

- Change to:

```python
await svc.transition(packet_id, PacketState.MERGED, reason=f"merge_complete:{commit_sha[:8]}")
```

- Add regression test: successful merge must persist `packets.state == "merged"`.
- Ensure API response reads state from DB after transition, not from optimistic constant.

---

### 2. Existing SQLite DBs will not get `features.degraded_reason`

**Severity:** blocker for existing deployments

`Feature` now has:

```python
degraded_reason = Column(Text, nullable=True)
```

But DB init still only calls:

```python
Base.metadata.create_all(engine)
```

`create_all()` will not alter existing tables. Any existing `grace.db` without this column can fail once SQLAlchemy selects or writes `Feature.degraded_reason`.

**Required fix:**

- Add a minimal migration path before production use.
- MVP-safe option: on SQLite startup, inspect `features` columns and run:

```sql
ALTER TABLE features ADD COLUMN degraded_reason TEXT;
```

when absent.

- Better option: introduce Alembic and add first migration.
- Add smoke test using an old DB schema fixture without `degraded_reason`.

---

### 3. PacketService.claim returns detached ORM `Lease`

**Severity:** high / possible runtime 500

`PacketService.claim()` commits and returns an ORM `Lease` instance after the DB session context is closed. `packets.py` then reads:

```python
"lease_id": lease.id,
"expires_at": lease.expires_at.isoformat() + "Z",
```

With SQLAlchemy default `expire_on_commit=True`, this can cause `DetachedInstanceError` after commit/session close.

**Required fix:**

- Return a DTO/dataclass instead of ORM object:

```python
@dataclass(frozen=True)
class ClaimResult:
    packet_id: str
    lease_id: int
    expires_at: datetime
    spec: dict
```

- Read values before session close.
- Add regression test: `/api/packets/claim` returns JSON successfully after service commit.

---

## P1 / High priority

### 4. Cancel endpoint still bypasses PacketService and has stale state logic

**Severity:** high

`cancel_packet()` still directly mutates `packet.state` and deletes leases in the router. This violates the new rule that `PacketService` owns all packet transitions.

It also checks old terminal states:

```python
if current in (MERGED, FAILED, BLOCKED, CANCELLED): ...
```

but does not handle `BLOCKED_FINAL` or normalize legacy `blocked` rows. A cancel request against `blocked_final` may become a generic 500 instead of a clear 400.

**Required fix:**

- Add `PacketService.cancel(packet_id, reason)`.
- Use `PacketStateMachine.normalize_state()`.
- Terminal cancellation rules should explicitly include `MERGED`, `FAILED`, `BLOCKED_FINAL`, `CANCELLED`.
- Router should only translate service exceptions to HTTP responses.
- Add tests for cancel from `ready`, `running`, `rejected`, `blocked_recoverable`, `blocked_final`, `merged`.

---

### 5. Wave gate can still open the next wave after `BLOCKED_FINAL`

**Severity:** high

`wave_gate.py` currently treats `BLOCKED_FINAL` as a `done_state`, but does not treat it as degraded. If every packet in a wave is `BLOCKED_FINAL`, `all_done=True`, `has_degraded=False`, and the next wave opens.

That is unsafe for GRACE semantics: final block means architect/user intervention, not permission to continue dependent work.

**Required fix:**

- Remove `BLOCKED_FINAL` from `done_states` for gate-opening logic.
- Treat `BLOCKED_FINAL` as degraded/stop condition.
- Next wave should open only when all packets are `MERGED` or intentionally `CANCELLED` by policy.
- Add regression test: wave with all `blocked_final` packets must not promote next-wave drafts to ready.

---

### 6. Scope-aware T0 checks new files against target repo root, not worktree

**Severity:** high

`run_acceptance_pipeline()` constructs:

```python
AcceptancePipeline(
    repo_root=project_root,
    command_runner=CommandRunner(worktree_path),
    scope_guard=ScopeGuard(worktree_path),
)
```

But `_resolve_t0_scope_paths()` checks path existence under `self._root`, which is `project_root`, not `worktree_path`.

New files created only in the agent worktree may be missing from T0 lint command construction and therefore skipped by the scope-aware lint selection.

**Required fix:**

- Resolve T0 candidate paths against the actual command cwd/worktree root, not `project_root`.
- Pass `cwd` into `_resolve_t0_scope_paths()` or store a separate `self._lint_root`.
- Add regression test: new file existing only in worktree is included in `grace_lint.py` and `ruff check` commands.

---

### 7. Merge cleanup no longer unregisters git worktrees

**Severity:** medium-high

Old code used `git worktree remove --force` before falling back to `shutil.rmtree`. New `MergeService.cleanup_worktree()` only runs `shutil.rmtree()`.

This can leave stale entries in `git worktree list`, causing later attempts to trip over stale metadata.

**Required fix:**

- Add `GitService.worktree_remove(repo, worktree_path, force=True)`.
- Use git removal first, then `shutil.rmtree()` fallback.
- Add smoke test or fake GitService test that cleanup calls worktree removal.

---

## P2 / Medium priority

### 8. Legacy boundary is useful but incomplete

**Severity:** medium

`LegacyPrefectBackend` is the only direct `prefect_grace` import, good. But `packet_executor.py` still owns legacy registry writing, stale branch cleanup, and branch format construction.

That means legacy-specific behavior is still split between `packet_executor.py` and `legacy_backend.py`.

**Required fix:**

- Move packet registry writing and legacy worktree cleanup either into `LegacyPrefectBackend` or a dedicated `LegacyRegistryService`.
- Keep `packet_executor.py` focused on orchestration and acceptance only.
- Use the shared `BRANCH_FORMAT` constant everywhere; remove duplicated string formatting.

---

### 9. Legacy backend ignores requested base ref

**Severity:** medium

`LegacyPrefectBackend.run()` passes:

```python
base_ref="HEAD"
```

The `ExecutionRequest.spec` carries `base_ref`, but the backend discards it. That can break diff/scope checks when the orchestrator is supposed to run against `main` or configured `GRACE_BASE_REF`.

**Required fix:**

- Pass `request.spec.get("base_ref", "HEAD")` to `run_e2e_packet()`.
- Add test that backend forwards base_ref.

---

### 10. Settings are introduced but not consistently used

**Severity:** medium

Examples still using raw env / hardcoded values:

- `api/main.py` reads `GRACE_DB_URL` directly.
- Lifespan loops sleep hardcoded `30` and `60` seconds instead of settings.
- `packet_executor.py` still reads `GRACE_BASE_REF` and `GRACE_AGENT_TIMEOUT` directly.

**Required fix:**

- Use `settings.database_url`, `settings.wave_gate_interval_seconds`, `settings.feature_gate_interval_seconds`, `settings.base_branch`, `settings.agent_timeout_seconds`.
- Keep env reads only inside `settings.py`, except for rare dynamic per-run overrides.

---

## Suggested next packets

### Packet A — merge + claim correctness

Files:

- `src/grace_control/services/merge_service.py`
- `src/grace_control/api/routers/packets.py`
- `src/grace_control/services/packet_service.py`
- tests for merge + claim

Acceptance:

- successful merge persists `Packet.state == merged`
- claim response never touches detached ORM
- tests fail before fix and pass after fix

### Packet B — cancel + wave gate semantics

Files:

- `src/grace_control/services/packet_service.py`
- `src/grace_control/api/routers/packets.py`
- `src/grace_control/core/wave_gate.py`
- tests for cancel + wave gate

Acceptance:

- cancel uses PacketService only
- `blocked_final` never opens next wave
- `blocked_recoverable` does not open next wave
- merged/cancelled-only wave can open next wave

### Packet C — SQLite migration guard

Files:

- `src/grace_control/db/__init__.py` or migration module
- tests with old SQLite schema

Acceptance:

- old DB without `features.degraded_reason` upgrades automatically or via migration
- no startup failure on existing `grace.db`

### Packet D — acceptance T0 worktree root

Files:

- `src/grace_control/core/acceptance_pipeline.py`
- acceptance pipeline tests

Acceptance:

- new file existing only in worktree is linted
- deleted/renamed files do not break command construction
- scope paths outside worktree are rejected or skipped safely

### Packet E — finish legacy boundary cleanup

Files:

- `src/grace_control/adapters/packet_executor.py`
- `src/grace_control/agent/legacy_backend.py`
- optional `src/grace_control/agent/legacy_registry.py`

Acceptance:

- only legacy backend/registry imports or knows legacy registry format
- packet_executor contains no direct subprocess worktree cleanup
- backend forwards configured base_ref

## Recommendation

Do not start the large `packet_executor.py` split continuation yet. First fix Packet A-C. The current code can report successful merges while DB state remains accepted, can fail claims through detached ORM access, and can break existing SQLite databases due to the new column without migration.
