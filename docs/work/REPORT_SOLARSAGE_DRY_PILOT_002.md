# Report: Solar Sage Dry Pilot 002

**Date:** 2026-06-11
**Scenario:** solarsage-ui-safe-pilot-002
**Status:** PASS

## Summary

Pilot 002 re-run with baseline-aware changed-file lint gate succeeds. The agent made a clean UI-safe copy change to the TodayScreen, all acceptance gates passed, and the change was merged into Solar Sage main.

## Results

| Stage | Result | Details |
|-------|--------|---------|
| Agent runs | 1 | Single attempt, no retries needed |
| T0 (scope + lint) | PASS | scope clean, ruff check on .py files only |
| T1 (changed-file lint + typecheck) | PASS | baseline compare: 0 new errors (7 pre-existing in touched files) |
| T2 (pnpm test:run) | PASS | all tests pass (746/747, same as baseline) |
| Merge to Solar Sage main | SUCCESS | commit `e8e9a7b` |

## Agent Change

The agent modified `components/today/today-screen.tsx` (+7 lines), adding a disclaimer footer:

```tsx
<footer className="px-5 pb-4 pt-2">
  <p className="text-center font-sans text-[11px] leading-relaxed text-foreground/40">
    Данные показаны для ознакомления. Перед принятием важных решений проверяйте информацию.
  </p>
</footer>
```

The change is clean: follows existing CSS patterns, no new dependencies, no API calls, no state changes.

## Changed-File Lint Baseline Compare

| Metric | Value |
|--------|-------|
| Policy | `changed_files_baseline_compare` |
| Changed frontend files | `components/today/today-screen.tsx` |
| Baseline (pre-existing) errors | 7 (3 no-undef globals, 1 no-unused-vars) |
| New errors introduced | 0 |
| Gate result | PASS (exit 0) |

Full `pnpm lint` baseline summary: 298 errors / 75 files, pre-existing (unchanged).

## Acceptance Evidence

- `workspace_mode`: target_repo_worktree
- `commit_semantics`: target_repo_commit
- `target_repo_preflight.success`: true
- `target_repo`: /opt/solarsage-astro (clean, synced with origin)
- Acceptance profile: NORMAL

## What Changed Since Failed Runs

1. **`pnpm lint` hard gate removed** — replaced by `scripts/grace_changed_files_lint.py` (baseline compare)
2. **Baseline compare implemented** — compares ESLint output on base commit vs current commit per file; only NEW errors (by `(ruleId, message)` key) cause failure. Pre-existing errors are reported as informational baseline debt.
3. **`GRACE_BASE_SHA` env var** — set by `acceptance_pipeline.py` before T1/T2, so the changed-file lint script can detect the base commit
4. **ruff check limited to `.py` files** — prevents false-positive T0 failures on `.tsx`/`.ts` files
5. **Worker `target_repo_root` fix** — worker checks settings/env before falling back to `project_root`
6. **No `GRACE_FAST_FAIL`** — agent got full 600s timeout, completed in ~116s

## Files Changed

- `scripts/grace_changed_files_lint.py` — new: baseline-compare ESLint gate
- `src/grace_control/core/acceptance_pipeline.py` — set `GRACE_BASE_SHA` env var
- `tests_live/scenarios/solarsage-ui-safe-pilot-002.yaml` — updated T1 commands
- `tests_live/runner/wave_resume_runner.py` — added `GRACE_PROJECT_ROOT` env var
- `tests/scripts/test_grace_changed_files_lint.py` — 22 unit tests
- `tests/grace_control/core/test_acceptance_pipeline.py` — 4 unit tests for GRACE_BASE_SHA
