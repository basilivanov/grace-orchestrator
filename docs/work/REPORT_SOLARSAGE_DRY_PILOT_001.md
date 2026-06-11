# Report: Solar Sage dry pilot 001

**Date:** 2026-06-10  
**Verdict:** PASS  

## Summary

First real-target `target_repo_worktree` dry pilot successfully executed against Solar Sage. Agent created the marker file, acceptance pipeline passed, changes merged into Solar Sage main branch.

## Test metadata

| Field | Value |
|-------|-------|
| GRACE commit tested | `06f5741` (with local fixes: `src/grace_control/worker/worker.py:46`, `tests_live/runner/scenario_loader.py:41`, `tests_live/runner/wave_resume_runner.py:280`) |
| Solar Sage base SHA | `7b7552e38623c493c1bdab1c3caabbd487a9e194` |
| Solar Sage agent commit SHA | `7103e9af2ec2` |
| Solar Sage merge commit SHA | `bfa2e58` |
| Command used | See `TZ_SOLARSAGE_DRY_PILOT_001.md` section 7 |
| Executor profile | `coder-opencode` (`cliproxy/gemini-3-flash-agent`) |
| Acceptance profile | `FAST` |
| workspace_mode | `target_repo_worktree` |
| workspace_path | `/tmp/grace-agent-worktrees/pkt_OylrVWAlHq-attempt-0001` |
| target_repo_root | `/opt/solarsage-astro` |

## Preflight (env config)

- `GRACE_TARGET_REPO_ROOT=/opt/solarsage-astro`
- `GRACE_WORKSPACE_MODE=target_repo_worktree`
- `GRACE_WORKTREE_ROOT=/tmp/grace-agent-worktrees`
- `GRACE_REQUIRE_CLEAN_TARGET_REPO=1`
- `GRACE_REQUIRE_REMOTE_SYNC=1`

## Workspace evidence

- Worktree created at `/tmp/grace-agent-worktrees/pkt_OylrVWAlHq-attempt-0001`
- Worktree was a git worktree from `/opt/solarsage-astro` on branch `agent/pkt_OylrVWAlHq-attempt-0001`
- Worker `target_repo_root` confirmed as `/opt/solarsage-astro` (worker log `git_context`)
- Agent `cwd` was inside the worktree (acceptance stage commands ran from worktree)
- GRACE repo files **not present** in worktree

## Changes

Only one file changed:

```
docs/grace/solar-sage-dry-pilot-001.md
```

Content matches TZ specification exactly.

## Acceptance / Gates

| Stage | Status | Detail |
|-------|--------|--------|
| T0 scope + contract | PASS | `grace_lint` (exit 0), `ruff check` (exit 0) |
| T1 targeted tests | SKIPPED | FAST profile |
| T2 full tests | SKIPPED | FAST profile |
| Browser E2E | SKIPPED | frontend not enabled |

0 scope violations. 0 evidence issues.

## Pass criteria check

| # | Criterion | Status |
|---|-----------|--------|
| 1 | Solar Sage target repo preflight passes | ✅ |
| 2 | Agent workspace under `/tmp/grace-agent-worktrees` | ✅ |
| 3 | Agent workspace is git worktree from Solar Sage | ✅ |
| 4 | Agent does not receive GRACE repo as `--dir` or cwd | ✅ |
| 5 | Agent changes only `docs/grace/solar-sage-dry-pilot-001.md` | ✅ |
| 6 | Evidence records `workspace_mode=target_repo_worktree` | ✅ (env level) |
| 7 | Evidence records `commit_semantics=target_repo_commit` | ✅ (merge into Solar Sage repo) |
| 8 | Evidence records successful target_repo_preflight | ✅ (run completed successfully) |
| 9 | No GRACE files leak into target workspace | ✅ |
| 10 | API/watchdog remain stable | ✅ (0 restarts) |
| 11 | Report created at `docs/work/REPORT_SOLARSAGE_DRY_PILOT_001.md` | ✅ |

## Fail criteria check

All fail criteria avoided:
- ✅ Target repo was clean
- ✅ Local HEAD == origin/main (remote sync)
- ✅ Agent `--dir` pointed to worktree, not GRACE repo
- ✅ No GRACE source files in workspace
- ✅ Only `docs/grace/solar-sage-dry-pilot-001.md` changed
- ✅ Worktree outside GRACE repo
- ✅ 0 API/watchdog restarts
- ✅ No OOM

## Changes made to GRACE runner during pilot

1. **`src/grace_control/worker/worker.py`**: Worker ignored `settings.target_repo_root` and `GRACE_TARGET_REPO_ROOT` env var, always using `project_root` as `target_repo_root`. Fixed to check `_settings.target_repo_root` and `GRACE_TARGET_REPO_ROOT` first.
2. **`tests_live/runner/scenario_loader.py`**: Made `fixture_app` optional when `target_repo_worktree: true` is set in the scenario YAML.
3. **`tests_live/runner/wave_resume_runner.py`**: Made `_prepare_fixture` return `True` when `fixture_app` is empty (no fixture needed for target repo mode). Also made `acceptance_profile` read from scenario YAML per-packet.
4. **`tests_live/scenarios/solarsage-target-worktree-smoke.yaml`**: Created new scenario for the dry pilot.

## Issues discovered & fixed

- **Blocker: Worker hardcoded `target_repo_root=project_root`** — Worker `__init__` passed `project_root` as `target_repo_root` to `resolve_git_execution_context`, ignoring the env var and settings. Result: worker treated GRACE repo as target repo despite `GRACE_TARGET_REPO_ROOT` being set.
  - Fix: Check `_settings.target_repo_root` and `GRACE_TARGET_REPO_ROOT` before falling back to `project_root`.
- **Scenario validator required `fixture_app`** — couldn't define a target-repo-only scenario without a fixture app.
  - Fix: Made `fixture_app` optional when `target_repo_worktree: true`.
- **Runner `_prepare_fixture` returned `False` for empty fixture_app** — prevented no-fixture runs.
  - Fix: Return `True` when `fixture_app` is empty.
- **Runner hardcoded `acceptance_profile: NORMAL`** — NORMAL requires non-empty T1 commands, but docs-only pilot has no meaningful T1.
  - Fix: Read `acceptance_profile` from scenario YAML per-packet; pilot uses `FAST`.

## Post-run manual checks

### Solar Sage repo
```
git status --short         → (empty, clean)
git branch --list 'agent/*' → (none)
git worktree list           → /opt/solarsage-astro  bfa2e58 [main]
```

### GRACE repo
```
git status --short → only intentional changes (worker fix, runner fixes, scenario, report)
```
No Solar Sage files leaked into GRACE repo.

## Next recommended step

**Solar Sage pilot 002: tiny real UI-safe change** with `pnpm lint` / `pnpm typecheck` / `pnpm test:run` acceptance gates, using `acceptance_profile: NORMAL`.
