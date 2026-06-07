# Follow-up Review: `c23970b` Retention + Session Resume fixes

Date: 2026-06-07
Reviewer: ChatGPT
Commit reviewed: `c23970be60311c1d203cb02d7cba53d7d9c720ce`
Previous review: `docs/work/review-retention-session-resume-2026-06-07.md`

## Verdict

**Mostly fixed, but not fully ACCEPT yet.**

The main production blockers from the previous review are substantially addressed. I would downgrade the status from `REQUEST CHANGES` to **`CONDITIONALLY ACCEPT after two small follow-up fixes + targeted tests`**.

## Confirmed fixed

### Fixed: AgentProfile now propagates resume fields

`AgentProfile.__init__` now reads and `to_dict()` now returns:

- `backend`
- `resume_mode`
- `resume_flag`
- `fork_flag`
- `inject_dir`

This fixes the previous “Session Resume is dead because executor dict drops config” blocker.

### Fixed: Maintenance stale worktree lookup now extracts packet_id

`MaintenanceService._list_worktrees()` now maps:

```text
pkt_xxx-attempt-0001 -> pkt_xxx
```

before looking up packet state. This fixes stale worktree detection for terminal packets.

### Fixed: Maintenance paths are no longer hardcoded to `/tmp/grace-orchestrator-export`

`admin_ui.py` now builds `MaintenanceService` from runtime settings:

- `settings.target_repo_root`
- `settings.state_root`
- `settings.worktree_root`

### Fixed: fast reject now runs terminal cleanup

`_fast_reject()` now extracts `packet_id` and run number from `run_id` and calls `TerminalStateCleanup.run()`.

### Fixed: manual worktree cleanup now uses git worktree cleanup

`MaintenanceService.cleanup_worktree()` now calls:

- `GitService.worktree_remove(...)`
- `GitService.worktree_prune(...)`

with filesystem fallback.

### Fixed: AgentSession.run_id now stores full PacketRun id

`PacketExecutionAdapter` now saves:

```python
run_id=f"{pid}-R{attempt:02d}"
```

instead of just `R01`.

### Fixed: fork parent link now uses internal session id

For fork mode, `parent_session_id` is now `prev.id`, while the CLI still receives `prev.external_id`.

### Fixed: session table detection is no longer sqlite_master-only

`SessionStore._check_table()` now uses SQLAlchemy `inspect(...).has_table()` first, with fallback query.

### Fixed: AdminAggregationService delegates to SessionStore

`get_packet_sessions()` now calls `SessionStore().get_sessions_for_packet(...)`, removing the duplicated raw SQL path.

### Fixed: unknown maintenance action no longer references a missing service attribute

`admin_ui.py` imports `CleanupResult` and uses it directly.

## Remaining issues

### MAJOR: RecoveryDecision session fields are still inert

Previous finding `MAJOR 9` is still open.

`RecoveryDecision` still defines:

```python
resume_session_id: str | None = None
fork_session: bool = False
```

but `RecoveryController` still just serializes whatever is already in the decision:

```python
decision_dict = decision.model_dump()
rj["recovery"] = decision_dict
```

I did not find logic that populates these two fields before persistence.

Impact:

- Runtime resume works in `PacketExecutionAdapter`, but recovery audit fields are misleading/empty.
- The implementation claim “RecoveryDecision fields persisted for audit trail” is still not true unless another path populates them.

Recommended fix:

Either:

1. Populate `decision.resume_session_id` and `decision.fork_session` inside `RecoveryController` from `SessionStore`, or
2. Remove/stop claiming these fields from RecoveryDecision and persist the actual resolved session under a separate `session_resume` payload after execution.

### MAJOR: backend-specific session extraction will not work for `agy` as configured

`AgentRunService._extract_session_id(stdout, backend)` has backend-specific patterns:

- `opencode`: JSON + `Session: ...`
- `agy`: `Conversation ID: ...`
- `cli`: only JSON + `Session: ses_...`

But the YAML profile for `coder_agy` says:

```yaml
coder_agy:
  backend: cli
  resume_mode: on_retry
  resume_flag: "--conversation"
  command:
    - agy
```

So `AgentRunService` will use the generic `cli` extractor, not the `agy` extractor. That means `Conversation ID: ...` will not be captured for AGY.

Recommended fix:

Choose one:

1. Set `backend: agy` for `coder_agy` and `backend: opencode` for opencode profiles if `backend` means CLI kind.
2. Keep `backend: cli`, but add a separate `session_backend` / `session_kind` field used only for extraction.
3. Derive extraction backend from `command[0]` when `backend == "cli"`.

I prefer option 3 because it preserves the current meaning of `backend: cli` as “local CLI execution backend”.

### TEST GAP: follow-up commit did not add the targeted regression tests

The follow-up commit modified production files and added `docs/REVIEW_RETENTION_SESSION_RESUME.md`, but I did not see test files changed in this delta.

At minimum, add tests for:

1. `select_executor("coder", attempt=2)` returns resume fields.
2. AGY profile extracts `Conversation ID: ...` correctly through the real selected executor dict.
3. RecoveryDecision audit fields are either populated or intentionally absent.
4. Maintenance stale detection from `pkt_xxx-attempt-0001` against `{"pkt_xxx": "merged"}`.
5. Fast reject cleanup calls terminal cleanup.

## Recommended next action

Make one small follow-up commit:

1. Fix AGY/opencode session extraction kind.
2. Resolve or remove inert RecoveryDecision session fields.
3. Add the targeted tests above.

After that, this can be accepted.
