# Report: Solar Sage dry pilot 002 — tiny UI-safe change

**Date:** 2026-06-11  
**Verdict:** FAIL  

## Summary

Pilot 002 failed. The target_repo_worktree wiring worked correctly, but the agent (`cliproxy/gemini-3-flash-agent`) did not produce any changes. The agent explored the codebase (searched for TodayScreen, started reading the Today page) but timed out or stopped without writing any files.

## Test metadata

| Field | Value |
|-------|-------|
| GRACE commit tested | `7a13829` (with local scenario + scenario loader fixes) |
| Solar Sage base SHA | `bfa2e5893b363d2239cc95a7964071b8f34c5c00` |
| Solar Sage agent commit SHA | N/A (no changes produced) |
| Solar Sage merge commit SHA | N/A |
| Command used | See `TZ_SOLARSAGE_DRY_PILOT_002.md` section 9 (without `GRACE_FAST_FAIL`) |
| Executor profile | `coder-opencode` (`cliproxy/gemini-3-flash-agent`) |
| Acceptance profile | `NORMAL` |
| workspace_mode | `target_repo_worktree` |
| Scenario | `solarsage-ui-safe-pilot-002` |

## Attempts overview

| Attempt | Result | Duration | Detail |
|---------|--------|----------|--------|
| 1 | Worktree issue | 65s | Agent ran (exit=0) but committed nothing → `agent_commit_failed` |
| 2 | Worktree issue | 65s | Same — agent completed with no changes |
| 3 | Worktree issue | 65s | Same — max attempts reached, final state: `failed` |

## Workspace evidence

- ✅ Worktree created at `/tmp/grace-agent-worktrees/pkt_3nsJoA9ka4-attempt-0001`
- ✅ Worktree is a git worktree from `/opt/solarsage-astro` (verified via `git worktree list`)
- ✅ Agent `--dir` pointed to worktree, not GRACE repo (from agent_command.log)
- ✅ Worker `target_repo_root` set to `/opt/solarsage-astro` (confirmed in worker git_context log)
- ✅ No GRACE repo files in workspace (worktree only contains Solar Sage files)

## Agent behavior

From `agent_stderr.log` (truncated):
```
build · gemini-3-flash-agent
Todos
[ ] Search for Today/current-day screen in frontend files
[ ] Add non-interactive helper copy
[ ] Run lint, typecheck, and test checks

Glob "**/*.tsx" 100 matches
Grep "TodayScreen" 21 matches
→ Read app/(grace)/today/page.tsx
```

The agent spent its time exploring the repo and was cut off before making any changes. `agent_command.log` shows the agent ran with `opencode run --dir <worktree> --model cliproxy/gemini-3-flash-agent --variant high` and exited with code 0.

## Why the pilot failed

The root cause is **agent-side**: the `gemini-3-flash-agent` model with `--variant high` explored the Solar Sage repo but did not produce any file changes within its execution window. This is likely because:

1. The prompt requires significant codebase exploration (search for TodayScreen, identify the correct UI file, understand existing patterns)
2. The agent's exploration consumed all its available context/tokens before producing output
3. The model lacks the capability to autonomously navigate a large unfamiliar codebase and make targeted changes

## What worked correctly

- ✅ target_repo_worktree wiring
- ✅ Worktree creation from `/opt/solarsage-astro`
- ✅ Worker `target_repo_root` resolution (fixed in pilot 001)
- ✅ Agent `--dir` pointed to Solar Sage worktree, not GRACE repo
- ✅ No GRACE files leaked into workspace
- ✅ Scope guard correctly configured
- ✅ Acceptance pipeline runs after agent commit
- ✅ Pre-existing lint issue documented (298 pre-existing ESLint errors across 75 files)

## Pre-existing condition: ESLint failures

`pnpm lint` has 298 pre-existing errors across 75 files (all in test files and some app files). These are not caused by the agent and would cause T1 to fail regardless of agent output. This would need to be addressed before `pnpm lint` can be used as a reliable acceptance gate.

`pnpm typecheck` passes on the unmodified repo.
`pnpm test:run` passes on the unmodified repo (746 passed, 1 skipped).

## Post-run checks

### Solar Sage repo
```
git status --short         → (empty, clean)
git branch --list 'agent/*' → (none after cleanup)
git worktree list           → /opt/solarsage-astro bfa2e58 [main]
```

### GRACE repo
```
git status --short → only intentional scenario/report files
```
No Solar Sage files leaked into GRACE repo.

## Pass criteria check

| # | Criterion | Status |
|---|-----------|--------|
| 1 | Solar Sage preflight passes | ✅ |
| 2 | Agent workspace under `/tmp/grace-agent-worktrees` | ✅ |
| 3 | Agent workspace from `/opt/solarsage-astro` | ✅ |
| 4 | Agent does not receive GRACE repo as cwd/--dir | ✅ |
| 5 | Changed files limited to 1 UI + 0–1 test | ❌ (no changes made) |
| 6 | No forbidden paths touched | ✅ (nothing touched) |
| 7 | No auth/payment/schema/config changes | ✅ |
| 8 | Workspace evidence JSON present | ✅ (in logs) |
| 9 | target_repo_preflight evidence present | ✅ (in logs) |
| 10 | `pnpm lint` passes | ❌ (pre-existing 298 errors) |
| 11 | `pnpm typecheck` passes | ✅ |
| 12 | `pnpm test:run` passes | ✅ |
| 13 | API/watchdog stable | ✅ (0 restarts) |
| 14 | No OOM | ✅ |
| 15 | Report exists | ✅ |

5/15 pass criteria met.

## Issues discovered

1. **Agent unable to complete complex task** — `cliproxy/gemini-3-flash-agent` with `--variant high` explored the repo but made no changes. For pilot 002's scope (explore + modify), a stronger model may be needed.
2. **`GRACE_FAST_FAIL=1` caps agent timeout at 60s** — the 60s cap via `ProcessSupervisor` is too short for any non-trivial agent task. Removed for second attempt.
3. **Pre-existing ESLint failures** — 298 lint errors in 75 files make `pnpm lint` unusable as a gate without prior cleanup.
4. **`agent_commit_failed` with empty stderr** — when agent exits 0 with no changes, the commit failure error is opaque.

## Next recommended step

Before pilot 003, either:
- **A**: Use a stronger agent model (e.g., `claude-sonnet-4-20250514`) capable of complex codebase navigation and modification
- **B**: Reduce pilot 003 scope to a change that requires zero exploration (e.g., modify a known, hardcoded file path)
- **C**: Clean pre-existing lint errors in Solar Sage so `pnpm lint` can serve as a reliable gate
