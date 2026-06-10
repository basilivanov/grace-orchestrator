# Review: target_repo_worktree implementation b59f0d2

Date: 2026-06-10
Reviewed commit: `b59f0d2e0a8319ca6ebe0131c299856a0e7ffe9f`
TZ: `docs/work/TZ_TARGET_REPO_WORKTREE_INTEGRATION.md`
Verdict: **PARTIAL ACCEPT — BLOCKED FOR SOLAR SAGE DRY PILOT UNTIL CLEANUP GAP IS FIXED**

## 1. Summary

The main positive path is implemented and the fixture smoke passed:

- `workspace_mode` config exists with default `full_git_worktree`.
- `require_clean_target_repo` and `require_remote_sync` settings exist.
- `GitService.run_preflight()` validates target repo, clean working tree, and optional remote sync.
- `AgentWorkspaceBuilder.build_target_repo_worktree()` creates a real target-repo worktree.
- `PacketExecutionAdapter._call_executor()` can create the agent workspace from target repo instead of GRACE repo.
- Evidence includes `workspace` and `target_repo_preflight` for target mode.
- `REPORT_TARGET_REPO_WORKTREE_SMOKE.md` reports `PASS`.
- Claimed test result: `916 passed`.

This is enough to say the implementation is **directionally correct** and the happy path works.

But there is one cleanup-path blocker before running Solar Sage for real: target repo cleanup is not consistently routed through `target_repo_root` on rejection paths.

## 2. Accepted parts

### 2.1 Config model

Accepted.

The implementation added:

```text
workspace_mode = full_git_worktree by default
require_clean_target_repo = true
require_remote_sync = false
```

This matches the TZ requirement to preserve legacy behavior unless target mode is explicitly configured.

### 2.2 Target repo preflight

Accepted for P0.

`GitService.run_preflight()` checks:

- target path exists and is a directory;
- target path is inside a git work tree;
- dirty working tree fails when `require_clean=true`;
- optional remote sync fails when local HEAD differs from remote ref.

The error for dirty repo is good and operator-friendly:

```text
target repo has uncommitted changes; commit or stash before running target_repo_worktree
```

### 2.3 Target worktree builder

Accepted.

`build_target_repo_worktree()`:

- resolves `base_sha` from target repo;
- calls `git worktree add` on target repo root;
- returns `workspace_mode=target_repo_worktree`;
- returns `commit_semantics=target_repo_commit`.

This is the right bridge mode before implementing scoped-copy apply-back.

### 2.4 Executor integration happy path

Accepted for fixture smoke.

In `_call_executor()`, target mode:

- runs preflight;
- cleans stale target worktree/branch before run;
- builds target repo worktree;
- passes target worktree as `ExecutionRequest.worktree_path`;
- persists `workspace` and `target_repo_preflight` evidence.

### 2.5 Smoke report

Accepted.

The smoke report shows:

```text
workspace_mode=target_repo_worktree
commit_semantics=target_repo_commit
target_repo_root=/tmp/grace-live-test/backend_fastapi_todo
GRACE files leaked: none
API stayed alive
watchdog did not restart
```

## 3. Blocker

### B1. Rejection cleanup still uses default GRACE cleanup in `_route_after._rej()`

In `PacketExecutionAdapter._route_after()`, the rejection path still calls:

```python
self._terminal_cleanup.run(packet_id=packet_id, attempt=rn)
```

without passing the effective target repo root.

This path is used for evidence verifier / reviewer rejections and blocks. That means a target repo worktree run can still clean up using the default cleanup root instead of target repo root.

Impact:

```text
target repo attempt branch/worktree may be left stale after rejection
or cleanup may operate against GRACE repo instead of target repo
future attempts may hit stale branch/worktree conflicts
Solar Sage pilot failure path is unsafe / misleading
```

This violates the TZ rule:

```text
full_git_worktree cleanup -> GRACE repo
target_repo_worktree cleanup -> target repo
```

Required fix:

- Compute/persist effective workspace metadata before routing.
- Pass effective target repo root into every cleanup path, including `_route_after._rej()`.
- Prefer adding an explicit helper:

```python
def _effective_cleanup_root(self, executor: dict) -> Path:
    workspace_mode = executor.get("workspace_mode") or settings.workspace_mode or "full_git_worktree"
    if executor.get("minimal_repo"):
        workspace_mode = "scoped_copy"
    if workspace_mode == "target_repo_worktree":
        return Path(settings.target_repo_root or self.project_root)
    return self.project_root
```

But the helper must be careful: if workspace mode was resolved earlier, use the already-resolved mode, not a second inconsistent lookup.

Required test:

```text
target_repo_worktree + evidence verifier rejection -> TerminalStateCleanup.run called with project_root=target_repo_root
```

Do not accept Solar Sage dry pilot until this is fixed.

## 4. Major follow-up gaps

### M1. `worktree_conflict` is recorded but not actually checked

`PreflightResult` has:

```text
worktree_conflict: bool = False
```

but `run_preflight()` does not appear to inspect `git worktree list` or branch/path conflicts. The field is therefore always false unless future code mutates it elsewhere.

Impact:

```text
evidence can claim worktree_conflict=false without actually checking conflicts
operator may trust a false preflight signal
```

Required follow-up:

- Either implement the actual conflict check in preflight, or remove/rename the field until it is real.
- If implemented, check at least:

```bash
git -C "$target_repo_root" worktree list --porcelain
git -C "$target_repo_root" branch --list "$attempt_branch"
```

Required test:

```text
existing conflicting attempt branch/worktree -> preflight or cleanup reports conflict deterministically
```

### M2. `worktree_root` inside GRACE repo only warns

For real project mode, the implementation only warns if target worktree path is inside GRACE repo.

The TZ allowed reject-or-warn, so this is not a blocker. But for production-like Solar Sage pilot, prefer fail-fast unless explicitly overridden.

Suggested follow-up:

```text
if workspace_mode=target_repo_worktree and worktree_root is inside GRACE project root:
  fail unless GRACE_ALLOW_WORKTREE_INSIDE_GRACE=1
```

### M3. Fast-reject cleanup can resolve from global settings only

`_fast_reject()` uses `settings.workspace_mode` rather than executor-resolved workspace mode.

If workspace mode is supplied only through executor profile/runner and not settings, cleanup can again choose the wrong root.

This is less urgent than B1, but should be unified by the same cleanup-root helper.

## 5. Tests to add/update before acceptance

Required:

1. `target_repo_worktree` + EV rejection cleanup uses target repo root.
2. `target_repo_worktree` + reviewer rejection cleanup uses target repo root.
3. `target_repo_worktree` + fast rejection cleanup uses target repo root if mode was resolved from executor.
4. Worktree conflict evidence is real, or the field is removed.
5. Existing `scoped_copy` fixture smoke still passes.
6. Existing target-worktree smoke still passes.
7. Full suite passes.

## 6. Decision

Current decision:

```text
PARTIAL ACCEPT for fixture target_repo_worktree happy path.
BLOCKED for Solar Sage dry pilot until B1 is fixed.
```

After fixing B1, this can move to:

```text
ACCEPTED FOR SOLAR SAGE DRY PILOT
```

provided the target repo is clean and local HEAD equals `origin/main` as required by preflight.
