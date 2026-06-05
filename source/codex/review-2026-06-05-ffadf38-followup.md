# Review: `ffadf38` follow-up after refactor audit

Date: 2026-06-05
Reviewed ref: `origin/main` at `ffadf383e8ed4161f645bb52a88ff832c7d17ff5`
Previous review: `source/codex/review-2026-06-05-refactor-audit.md`

## Verdict

`ffadf38` does **not** resolve the P0/P1 findings from the previous review. It mainly changes docs-check, generated docs process, backend selection plumbing, and acceptance tests. Those are useful, but the critical runtime bugs remain in `origin/main`.

Do not count `ffadf38` as closure for the previous review. Return to the concrete items below.

---

## Still open P0 / blockers

### 1. `MergeService` still reports success without persisting `MERGED`

Current code in `src/grace_control/services/merge_service.py` still does:

```python
await svc.transition(packet_id, target_state=None, reason=f"merge_complete:{commit_sha[:8]}")
```

But `PacketService.transition()` accepts `to_state`, not `target_state`. This raises, gets swallowed by the broad `except`, logs `merge_state_transition_failed`, then returns `MergeResult(success=True, ...)`.

Impact: `/api/packets/{id}/merge` can return `state: "merged"` while DB still contains `accepted`.

Required fix:

```python
from grace_control.db.schema import PacketState
await svc.transition(packet_id, PacketState.MERGED, reason=f"merge_complete:{commit_sha[:8]}")
```

Also: if the state transition fails, `MergeService` must return `MergeResult(success=False, error=...)`, not hide it.

Required tests:

- successful merge persists `Packet.state == PacketState.MERGED.value`
- merge returns failure if DB transition fails
- router response state is read/confirmed from persisted DB state or service result after transition

---

### 2. Existing SQLite DB migration still missing for `features.degraded_reason`

Current `src/grace_control/db/__init__.py` still only does:

```python
Base.metadata.create_all(engine)
```

`create_all()` does not alter existing tables. Existing `grace.db` created before `Feature.degraded_reason` was added can break once code queries or writes the new column.

Required fix, minimal MVP-safe SQLite guard:

- after `create_all(engine)`, if SQLite, inspect `features` columns
- if `degraded_reason` absent, run:

```sql
ALTER TABLE features ADD COLUMN degraded_reason TEXT
```

Preferred long-term: Alembic.

Required tests:

- create old SQLite schema without `degraded_reason`
- call `init_db(old_db_url)`
- verify `features.degraded_reason` exists and feature query/write works

---

### 3. `PacketService.claim()` still returns detached ORM `Lease`

Current `PacketService.claim()` commits inside the service and returns the ORM `Lease`. The router then reads `lease.id` and `lease.expires_at` after the service session is closed.

With SQLAlchemy `expire_on_commit=True`, this can raise `DetachedInstanceError`.

Required fix:

- introduce a DTO/dataclass, e.g.:

```python
@dataclass(frozen=True)
class ClaimResult:
    packet_id: str
    lease_id: int
    expires_at: datetime
    spec: dict
```

- read all fields before commit/session close
- return `ClaimResult`, not ORM object

Required tests:

- `PacketService.claim()` returns DTO values after DB session closes
- `/api/packets/claim` returns JSON without touching detached ORM attributes

---

## Still open P1 / high priority

### 4. `cancel_packet()` still bypasses `PacketService`

Current `src/grace_control/api/routers/packets.py` still directly:

- queries packet
- deletes lease
- mutates worker
- calls `_state_machine.transition(...)`
- assigns `packet.state = PacketState.CANCELLED.value`
- records events / broadcasts from the router

This violates the newly introduced contract that `PacketService` owns all state transitions.

It also uses stale terminal logic: `MERGED`, `FAILED`, `BLOCKED`, `CANCELLED`, but not `BLOCKED_FINAL`; and it does not normalize legacy `blocked` strings before checking.

Required fix:

- add `PacketService.cancel(packet_id, reason)`
- move lease deletion and worker cleanup there
- use `PacketStateMachine.normalize_state()`
- terminal states should include `MERGED`, `FAILED`, `BLOCKED_FINAL`, `CANCELLED`
- router should only translate service exceptions to HTTP

Required tests:

- cancel from `ready`, `running`, `rejected`, `blocked_recoverable` works
- cancel from `merged`, `failed`, `blocked_final`, legacy `blocked` returns clear 400
- events/broadcast still happen once

---

### 5. `wave_gate` still opens next wave after `BLOCKED_FINAL`

Current `src/grace_control/core/wave_gate.py` still has:

```python
done_states = {PacketState.MERGED, PacketState.CANCELLED, PacketState.BLOCKED_FINAL}
```

and `BLOCKED_FINAL` is not in `degraded_states`. Therefore a wave where all packets are `blocked_final` has `all_done=True`, `has_degraded=False`, becomes `COMPLETED`, and gates the next wave to `READY`.

This is unsafe. `BLOCKED_FINAL` means stop/manual/architect intervention, not continue.

Required fix:

- remove `BLOCKED_FINAL` from `done_states`
- add `BLOCKED_FINAL` to `degraded_states`
- only `MERGED` and policy-approved `CANCELLED` should open the next wave

Required tests:

- all `merged` opens next wave
- all `cancelled` opens next wave only if policy intends it
- any `failed`, `rejected`, `blocked_recoverable`, `blocked_final`, legacy `blocked` does not open next wave and marks degraded

---

### 6. Scope-aware T0 still checks file existence against project root, not worktree

Current `AcceptancePipeline._resolve_t0_scope_paths()` still resolves candidate files against `self._root`. In `run_acceptance_pipeline()`, `self._root` is `project_root`, while commands run in `worktree_path`.

New files created by the agent only in the worktree may be skipped from targeted lint command construction.

Required fix:

- resolve T0 candidate paths against the command cwd / worktree root, not `project_root`
- one simple approach: pass `cwd` into `_build_t0_commands()` and `_resolve_t0_scope_paths()`
- preserve relative paths for commands executed with `cwd=worktree_path`

Required tests:

- new file exists only in worktree, not project root
- `grace_lint.py` and `ruff check` commands include that file
- deleted files do not break command construction
- absolute/outside-worktree paths are rejected or safely skipped

---

### 7. Worktree cleanup still bypasses `git worktree remove`

Current `MergeService.cleanup_worktree()` only does:

```python
shutil.rmtree(wt, ignore_errors=True)
```

This can leave stale worktree metadata in the target repo. Later attempts can fail because Git still believes the worktree exists.

Required fix:

- add `GitService.worktree_remove(repo, worktree_path, force=True)`
- call `git worktree remove --force <path>` first
- call `git worktree prune`
- only then fallback to `shutil.rmtree()`

Required tests:

- fake GitService verifies `worktree_remove` was called
- cleanup logs but does not raise on failure

---

## What `ffadf38` did fix / change

This commit appears to address:

- docs-check drift detection
- generated OpenAPI/state docs process
- acceptance pipeline test suite alignment
- settings-driven backend selection factory
- API contract archival/redirect docs

Those changes are not a substitute for the runtime P0/P1 fixes above.

---

## Required next Codex packet

Create one focused fix packet, no broad refactor:

Title: `Fix post-refactor runtime regressions from review-2026-06-05`

Files likely involved:

- `src/grace_control/services/merge_service.py`
- `src/grace_control/services/packet_service.py`
- `src/grace_control/api/routers/packets.py`
- `src/grace_control/core/wave_gate.py`
- `src/grace_control/db/__init__.py`
- `src/grace_control/core/acceptance_pipeline.py`
- `src/grace_control/services/git_service.py`
- tests under `tests/grace_control/`

Acceptance criteria:

1. Merge success persists `packets.state == "merged"`; merge fails if state transition fails.
2. Claim returns DTO, not ORM; no detached ORM access in router.
3. Cancel goes through `PacketService.cancel()` and handles `blocked_final` correctly.
4. `blocked_final` / `blocked_recoverable` / `failed` / `rejected` do not open next wave.
5. Existing SQLite DB without `features.degraded_reason` upgrades safely.
6. T0 targeted lint sees files that exist only in worktree.
7. Merge cleanup uses `git worktree remove --force` before filesystem fallback.

Do not spend this packet on docs, generated artifacts, UI, or backend selection. This is a runtime correctness packet.
