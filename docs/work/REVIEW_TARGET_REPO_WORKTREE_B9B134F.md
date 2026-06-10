# Review: target_repo_worktree cleanup follow-up b9b134f

Date: 2026-06-10
Reviewed commit: `b9b134f4709c3a12e5bdf22d460558634be12e93`
Previous review: `docs/work/REVIEW_TARGET_REPO_WORKTREE_B59F0D2.md`
Verdict: **ACCEPTED FOR SOLAR SAGE DRY PILOT**

## 1. Summary

The follow-up resolves the previous blocker and major gaps well enough to proceed to a Solar Sage dry pilot.

Confirmed changes:

- `_effective_cleanup_root()` added.
- Evidence/reviewer rejection cleanup now passes `project_root=target_repo_root` for `target_repo_worktree`.
- `_persist_run()` cleanup path also uses `_effective_cleanup_root()`.
- `_fast_reject()` no longer relies only on global `settings.workspace_mode`; it resolves profile data and then uses `_effective_cleanup_root()`.
- `run_preflight()` now accepts `branch` and `worktree_path` and records `worktree_conflict`.
- `target_repo_worktree` now fails fast if worktree path is inside GRACE root unless `GRACE_ALLOW_WORKTREE_INSIDE_GRACE=1`.
- Smoke report still shows `target_repo_worktree` PASS.

## 2. Previous blocker status

### B1. Rejection cleanup wrong repo root

Status: **fixed**.

The rejection path now uses:

```python
effective_target_root = self._effective_cleanup_root(executor)
self._terminal_cleanup.run(packet_id=packet_id, attempt=rn, project_root=effective_target_root)
```

The shared helper resolves:

```python
workspace_mode = executor.get("workspace_mode") or settings.workspace_mode or "full_git_worktree"
if executor.get("minimal_repo"):
    workspace_mode = "scoped_copy"
if workspace_mode == "target_repo_worktree":
    return Path(settings.target_repo_root or self.project_root)
return self.project_root
```

This satisfies the rule:

```text
target_repo_worktree cleanup -> target repo
full_git_worktree cleanup -> GRACE repo
```

## 3. Major gap status

### M1. `worktree_conflict` evidence was not real

Status: **fixed enough for P0**.

`run_preflight()` now checks:

```text
git branch --list <attempt_branch>
git worktree list --porcelain
```

and sets `worktree_conflict=True` if either branch or worktree metadata conflicts.

Note: current implementation records the conflict flag but does not fail on conflict by itself. That is acceptable for now because the executor immediately performs cleanup before creating the new worktree. If future production mode wants stricter behavior, add `require_no_worktree_conflict=true`.

### M2. Worktree path inside GRACE repo only warned

Status: **fixed**.

In `target_repo_worktree`, if `worktree_root` resolves inside the GRACE project root, execution now fails unless:

```text
GRACE_ALLOW_WORKTREE_INSIDE_GRACE=1
```

This prevents accidentally handing GRACE repo context back to the agent.

### M3. Fast-reject cleanup root could be inconsistent

Status: **fixed enough for P0**.

`_fast_reject()` now resolves the executor profile by `executor_id`, converts it to dict, and passes it through `_effective_cleanup_root()`.

## 4. Smoke status

`REPORT_TARGET_REPO_WORKTREE_SMOKE.md` still reports PASS:

```text
workspace_mode=target_repo_worktree
commit_semantics=target_repo_commit
target repo clean=true
GRACE files leaked=none
API alive
watchdog no restarts
```

## 5. Remaining caution before Solar Sage

Before the Solar Sage dry pilot, manually verify target repo state:

```bash
cd /opt/solarsage-astro

git status --short
git branch --show-current
git rev-parse HEAD
git rev-parse origin/main
git worktree list
```

Required:

```text
git status --short is empty
current branch is main or configured base branch
HEAD == origin/main when require_remote_sync=1
no conflicting GRACE attempt worktree exists
```

## 6. Decision

Decision:

```text
ACCEPTED FOR SOLAR SAGE DRY PILOT
```

Next step:

```text
Create a tiny Solar Sage dry-pilot packet using target_repo_worktree.
```

The first Solar Sage packet should be low-risk: docs/test-only marker or a tiny non-production UI copy fixture. Do not start with a large UI/business change yet.
