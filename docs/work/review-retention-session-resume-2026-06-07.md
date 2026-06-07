# Review: Retention Policy + Session Resume implementation

Date: 2026-06-07
Reviewer: ChatGPT
Scope: static review of current `main` after Retention and Session Resume implementation commits.

## Verdict

**REQUEST CHANGES.**

The implementation is directionally good and a lot of infrastructure is in place, but there are several functional gaps that mean the two features are not yet reliable in real operation:

- Session Resume is mostly wired, but the selected executor dict drops the resume configuration, so resume mode will usually stay `never`.
- Maintenance UI is present, but stale worktree detection is likely broken because worktree slugs are matched against `packet_id` keys incorrectly.
- Maintenance paths are hardcoded to `/tmp/grace-orchestrator-export`, not runtime settings.
- Some cleanup paths still skip proper git worktree removal and can leave stale git metadata.

## What is implemented well

- `TerminalStateCleanup` exists and follows the correct high-level policy: delete worktree + `agent/<packet>-attempt-*` local branches, keep `.grace/state` artifacts.
- `SizeCalculator` and `fmt_size()` are implemented and integrated into admin packet/tree DTOs.
- Maintenance view exists at `/admin?view=maintenance` with disk, worktrees, branches, and manual cleanup UI.
- `AgentSession` table and `SessionStore` are implemented.
- `ExecutionRequest` / `AgentRunService` support `resume_session_id` and `fork_session` parameters.
- Sessions tab and `TraceService.get_session_chain()` are present.

## Findings

### BLOCKER 1 — `resume_mode/resume_flag/fork_flag/backend/inject_dir` are not propagated from `agent_profiles.yaml`

`src/grace_control/config/agent_profiles.yaml` defines fields like:

- `resume_mode: on_retry`
- `resume_flag: "--session"`
- `fork_flag: "--fork"`
- `inject_dir: true`
- `backend: cli`

But `AgentProfile.to_dict()` in `src/grace_control/config/agent_profiles.py` only returns:

- `executor_id`
- `command`
- `extras`
- `model`
- `effort`
- `cwd`
- `timeout_seconds`
- `env`
- `input_mode`
- `input_template`

It does **not** return `resume_mode`, `resume_flag`, `fork_flag`, `backend`, `inject_dir`, or `role`.

Impact:

- `PacketExecutionAdapter._call_executor()` does `resume_mode = executor.get("resume_mode", "never")`.
- Because the field is missing from selected executors, runtime falls back to `never`.
- `AgentRunService.run()` also checks `executor.get("resume_mode", "never")`, so `--session/--conversation/--fork` will not be injected.
- `inject_dir` may also silently stop working for non-legacy/non-opencode names.

Fix:

- Add these fields to `AgentProfile.__init__` and `to_dict()`:
  - `backend`
  - `resume_mode`
  - `resume_flag`
  - `fork_flag`
  - `inject_dir`
  - `role` or derive role explicitly in selector.
- Add a test: `select_executor("coder", attempt=2)` must contain `resume_mode == "on_retry"` for profiles that define it.
- Add an integration test proving retry command includes `--session <previous_external_id>`.

### BLOCKER 2 — Maintenance stale worktree detection uses wrong key

`admin_ui._packet_states_map()` returns `{packet_id: state}`.

`MaintenanceService._list_worktrees()` currently does:

```python
slug = path.name
state = packet_states.get(slug)
is_stale = state in _TERMINAL_LIKE
```

But worktree slugs are shaped like:

```text
<pkt_id>-attempt-0001
```

while the map key is only:

```text
<pkt_id>
```

Impact:

- Worktrees for terminal packets show as `unknown`, not stale.
- `snapshot.stale_worktree_count` stays zero.
- The bulk “Clean up all stale” button may never appear.
- `cleanup_stale_worktrees()` may remove nothing.

Fix:

- Extract `packet_id` from slug before lookup:

```python
packet_id = slug.rsplit("-attempt-", 1)[0] if "-attempt-" in slug else slug
state = packet_states.get(packet_id)
```

- Add tests where `packet_states = {"pkt_abc": "merged"}` and worktree dir is `pkt_abc-attempt-0001`; it must be marked stale.

### BLOCKER 3 — Maintenance service paths are hardcoded

`admin_ui.py` initializes MaintenanceService with:

```python
state_root=Path("/tmp/grace-orchestrator-export/.grace/state")
worktree_root=Path("/tmp/grace-orchestrator-export/.grace/worktrees")
project_root=Path("/tmp/grace-orchestrator-export")
```

Impact:

- `/admin?view=maintenance` only works for that exact local export path.
- Real deployments using `settings.target_repo_root`, `settings.state_root`, or `.grace/config.yaml` will show wrong disk usage / no branches / no worktrees.
- Cleanup actions may act on the wrong repo if that path exists.

Fix:

- Build paths from `settings`:

```python
project_root = Path(settings.target_repo_root or ".").resolve()
state_root = (project_root / settings.state_root).resolve()
worktree_root = (project_root / settings.worktree_root).resolve()
```

- Add an admin UI test that overrides settings and verifies snapshot uses those paths.

### MAJOR 4 — fast reject path skips terminal cleanup

`PacketExecutionAdapter.execute()` calls `_fast_reject()` when `_inspected_worktree()` fails.

That can happen after the worktree was created, for example when:

- the agent produced no changes;
- worktree inspection fails;
- the worktree is malformed.

`_fast_reject()` only updates evidence/run status and returns. It does not call `TerminalStateCleanup`.

Impact:

- No-changes / worktree-issue failures can leave `.grace/worktrees/<packet>-attempt-NNNN` and `agent/<packet>-attempt-NNNN` branches behind.
- This defeats the Retention Phase 1 guarantee for one important failure path.

Fix:

- Either route `_fast_reject()` through `_persist_run(...)`, or pass `packet_id/run_number` into `_fast_reject()` and call `TerminalStateCleanup.run(packet_id, attempt=run_number)`.
- Add a test: no-changes fast reject removes worktree and branch but preserves `.grace/state` run artifacts.

### MAJOR 5 — manual worktree cleanup uses `shutil.rmtree()` but not `git worktree remove/prune`

`MaintenanceService.cleanup_worktree()` removes the directory via `shutil.rmtree(path)`, then deletes the branch.

It does not call:

- `git worktree remove --force`
- `git worktree prune`

Impact:

- Git administrative metadata under `.git/worktrees/` can remain stale.
- Future `git worktree add` may fail even though the directory was removed.
- This reintroduces the exact stale-worktree problem that `GitService.worktree_remove()` was designed to solve.

Fix:

- Reuse `GitService.worktree_remove(project_root, path, force=True)` before filesystem fallback.
- Call `GitService.worktree_prune(project_root)` after cleanup.
- Add a test verifying `git worktree list` no longer contains the cleaned path.

### MAJOR 6 — `AgentSession.run_id` is saved as `R01`, but schema says it should be `PacketRun.id`

Schema comment:

```python
run_id = Column(String, nullable=True, index=True)  # PacketRun.id
```

But `PacketExecutionAdapter` saves:

```python
run_id=evidence_dir.name if evidence_dir else None
```

That produces `R01`, not `pkt_xxx-R01`.

Impact:

- Session ↔ run cross-reference is weak/broken.
- Admin and trace cannot reliably jump from session to exact `packet_runs` row.

Fix:

- Save the actual `run_id` variable already available in the adapter.
- Add a test asserting `AgentSession.run_id == PacketRun.id`.

### MAJOR 7 — fork parent linkage stores external session id, not internal session row id

`AgentSession.id` is the internal DB id (`ses_<uuid>`). `external_id` is the backend session id.

`parent_session_id` is documented as “for forks — points to original”, but `PacketExecutionAdapter` sets:

```python
parent_session_id=resume_session_id if fork else None
```

`resume_session_id` is `prev.external_id`, not `prev.id`.

Impact:

- Session chain cannot reliably join parent/child rows inside DB.
- If two backends produce overlapping external ids, the chain becomes ambiguous.
- UI arrows still show something, but it is not a robust relational chain.

Fix:

- Keep both values if needed:
  - `parent_session_id = prev.id`
  - `parent_external_id = prev.external_id` as a new nullable column or inside metadata.
- Add a fork test: child row’s `parent_session_id` equals parent row’s internal `id`.

### MAJOR 8 — session-table detection is SQLite-only

`SessionStore._check_table()` and `AdminAggregationService.get_packet_sessions()` query `sqlite_master` directly.

Impact:

- On non-SQLite engines, session UI/trace will report `table_missing` or fail even if `agent_sessions` exists.
- The codebase has a generic `database_url` setting, so the read path should not hardcode SQLite internals.

Fix:

- Use SQLAlchemy inspection:

```python
from sqlalchemy import inspect
inspect(db.bind).has_table("agent_sessions")
```

- Add a test around `SessionStore._check_table()` using SQLAlchemy inspection rather than `sqlite_master`.

### MAJOR 9 — `RecoveryDecision.resume_session_id/fork_session` fields are inert

`RecoveryDecision` has fields:

```python
resume_session_id: str | None = None
fork_session: bool = False
```

But the reviewed recovery path does not populate them. `RecoveryController._persist_decision()` just dumps the decision as-is into `result_json.recovery`.

Impact:

- The commit message says these fields are persisted “for audit trail”, but they will usually remain empty/default.
- Runtime session resolution currently happens later inside `PacketExecutionAdapter`, outside `RecoveryDecision`.

Fix:

Choose one of two designs:

1. Recovery owns the decision:
   - populate `resume_session_id` / `fork_session` inside `RecoveryController` from `SessionStore`;
   - persist them in `result_json.recovery`.

2. Adapter owns runtime session resolution:
   - remove the claim from recovery docs/commit message;
   - optionally write the actual resolved session into `PacketRun.result_json.session_resume` after execution.

### MINOR 10 — Sessions tab template expects fields that one DTO path does not return

`_tab.html` uses:

- `s.duration_seconds`
- `s.fork_of`

`SessionStore.get_sessions_for_packet()` returns these, but `AdminAggregationService.get_packet_sessions()` uses raw SQL and does not include them.

Impact:

- Duration/fork metadata may not render in the admin Sessions tab.
- Not fatal, but the UI is less useful than intended.

Fix:

- Make `AdminAggregationService.get_packet_sessions()` call `SessionStore.get_sessions_for_packet()` instead of duplicating raw SQL.

### MINOR 11 — unknown cleanup action path references a non-existent attribute

`admin_ui.cleanup_action()` does:

```python
result = _maint_svc.CleanupResult()
```

`CleanupResult` is a class in `maintenance_service.py`, not an attribute of the service instance.

Impact:

- Only affects invalid/manual malformed action queries.
- Still should be fixed to avoid a 500.

Fix:

- Import `CleanupResult` or add a helper constructor.

## Tests to add before accepting

1. `test_selected_executor_preserves_resume_fields`
   - Load `coder-deepseek-flash`.
   - Assert selected executor has `resume_mode`, `resume_flag`, `fork_flag`, `backend`, `inject_dir`.

2. `test_retry_injects_session_flag_from_previous_session`
   - Existing completed `AgentSession.external_id = "ses_prev"`.
   - Retry same coder.
   - Assert command contains `--session ses_prev`.

3. `test_maintenance_marks_attempt_slug_stale_by_packet_id`
   - Worktree: `pkt_abc-attempt-0001`.
   - Packet state map: `{ "pkt_abc": "merged" }`.
   - Assert `is_stale == True`.

4. `test_cleanup_stale_worktrees_removes_terminal_packet_worktree`
   - Same setup as above.
   - Assert cleanup removes the dir and matching branch.

5. `test_fast_reject_cleans_worktree_and_branch`
   - Simulate no-changes or invalid worktree after `git worktree add`.
   - Assert worktree/branch are cleaned.

6. `test_manual_cleanup_uses_git_worktree_remove_and_prune`
   - Create a real git worktree.
   - Cleanup via MaintenanceService.
   - Assert `git worktree list` does not contain the path.

7. `test_agent_session_run_id_matches_packet_run_id`
   - Assert saved session `run_id == "<packet_id>-R01"`, not just `R01`.

8. `test_fork_parent_session_uses_internal_id`
   - Create parent session with internal and external ids.
   - Fork child.
   - Assert `parent_session_id == parent.id`.

9. `test_session_table_detection_uses_sqlalchemy_inspect`
   - Ensure session lookup does not rely on `sqlite_master`.

## Suggested fix order

1. Fix `AgentProfile` propagation first — otherwise Session Resume is functionally off.
2. Fix MaintenanceService stale detection and hardcoded paths — otherwise UI cleanup is misleading.
3. Fix fast-reject cleanup and manual `git worktree remove/prune` — otherwise retention still leaks.
4. Fix session run/parent linkage and table detection.
5. Add the targeted regression tests above.

## Acceptance after fixes

Accept when:

- Retry actually passes previous external session id into CLI command.
- Maintenance tab points at the configured target repo.
- Terminal/fast-reject cleanup removes local worktree + local agent branches.
- Manual cleanup does not leave stale git worktree metadata.
- Sessions tab and `grace trace` show a coherent chain with correct run ids and parent links.
