# TZ: Solar Sage lint baseline strategy for GRACE acceptance gates

Date: 2026-06-11
Status: ready for architect/coder
Priority: P0 unblock Solar Sage pilot 002
Scope: acceptance gates, lint baseline, changed-file lint, reporting

Related:
- `docs/work/TZ_SOLARSAGE_DRY_PILOT_002.md`
- `docs/work/REPORT_SOLARSAGE_DRY_PILOT_002.md` if already created
- `docs/work/REVIEW_SOLARSAGE_DRY_PILOT_001_92BB7C0.md`
- `docs/work/TZ_TARGET_REPO_WORKTREE_INTEGRATION.md`

## 1. Problem

Solar Sage pilot 002 proved that `target_repo_worktree` continues to work and T0 now passes after ruff was limited to Python files.

But T1 is blocked by pre-existing Solar Sage lint debt:

```text
pnpm lint fails with ~298 existing ESLint errors across ~75 files
```

This is not a failure of the agent change and not a failure of `target_repo_worktree`.

Current acceptance behavior is too blunt:

```text
full pnpm lint failure => pilot failure
```

That blocks all small safe pilots until the entire existing frontend lint backlog is fixed.

We need baseline-aware acceptance:

```text
existing lint debt is allowed temporarily
new lint errors introduced by the agent are not allowed
```

## 2. Goal

Implement Solar Sage lint gates so GRACE can continue small pilots safely while still preventing new lint debt.

The new acceptance logic must distinguish:

```text
pre-existing lint errors
vs
new errors introduced by the current agent diff
```

Pilot 002 should then be re-run with:

```text
acceptance_profile=NORMAL
T0 PASS
T1 PASS if no new lint errors are introduced
T1 still reports existing baseline debt
T2 pnpm test:run still enforced if available
```

## 3. Non-goals

Do not fix all 298 existing ESLint errors in this task.
Do not disable lint globally.
Do not weaken Python lint/T0 quality.
Do not change Solar Sage product behavior.
Do not touch auth/payments/subscriptions/schema/config.
Do not add dependencies unless absolutely necessary.
Do not convert pilot 002 into a massive cleanup/refactor.

## 4. Required approach

Implement one of the following, in priority order.

### Option A — changed-file lint gate, preferred P0

Run ESLint only on changed frontend files from the agent diff.

Changed files should be computed from target repo worktree against target base SHA:

```bash
git diff --name-only "$BASE_SHA" HEAD
```

Filter to lintable frontend files:

```text
*.js
*.jsx
*.ts
*.tsx
```

Exclude non-source/generated/vendor files:

```text
node_modules/**
.next/**
dist/**
build/**
coverage/**
```

If no changed lintable frontend files:

```text
changed-file lint gate = skipped / pass
```

If changed lintable files exist, run lint only on those files using the repo's existing tooling.

Preferred command pattern:

```bash
pnpm exec eslint <changed-files>
```

or, if the repo's lint script supports file args:

```bash
pnpm lint -- <changed-files>
```

Do not run full `pnpm lint` as a hard gate while baseline debt exists.

### Option B — baseline compare, P1

If changed-file lint is not enough because repo lint config depends on global project context, implement baseline compare:

```text
before agent: run full pnpm lint, capture structured output
agent changes
after agent: run full pnpm lint, capture structured output
pass if after_errors - before_errors is empty
fail if new errors appeared
```

This option is more expensive and more complex. Use it only if changed-file lint is not reliable.

## 5. Required runner / acceptance behavior

Add a Solar Sage-specific lint gate mode for live scenarios.

Suggested scenario YAML field:

```yaml
lint_policy: changed_files_no_new_errors
```

or under verification:

```yaml
verification:
  lint_policy: changed_files_no_new_errors
```

The runner/acceptance layer should understand this policy and convert T1 lint into:

```text
changed-file ESLint gate
```

rather than full-repo `pnpm lint` hard gate.

Keep full lint visible as an informational diagnostic if desired, but not blocking:

```text
full pnpm lint: FAIL, known baseline debt: 298 errors / 75 files
changed-file lint: PASS
```

## 6. Required commands for pilot 002

For `TZ_SOLARSAGE_DRY_PILOT_002`, replace hard full lint gate:

```bash
pnpm lint
```

with changed-file lint gate:

```bash
python3 scripts/grace_changed_files_lint.py --base-sha "$BASE_SHA"
```

or equivalent built into the acceptance runner.

T1 should become:

```bash
python3 scripts/grace_changed_files_lint.py --base-sha "$BASE_SHA"
pnpm typecheck
```

T2 remains:

```bash
pnpm test:run
```

If `pnpm typecheck` also has pre-existing baseline failures, do not automatically weaken it in this task. Report it separately as `TYPECHECK_BASELINE_DEBT` and write a separate TZ.

## 7. Helper script requirements

If adding a helper script, prefer to place it in GRACE, not Solar Sage, unless there is already an established scripts folder in Solar Sage for CI gates.

Recommended GRACE path:

```text
scripts/grace_changed_files_lint.py
```

Behavior:

```text
input:
  --repo <target worktree path>, default cwd
  --base-sha <sha>, required or env BASE_SHA/GRACE_BASE_SHA
  --package-manager pnpm, default pnpm

steps:
  1. git diff --name-only <base-sha> HEAD
  2. filter to .js/.jsx/.ts/.tsx
  3. exclude generated/vendor dirs
  4. if none, print 'no changed lintable frontend files' and exit 0
  5. run pnpm exec eslint <files>
  6. exit with eslint exit code
```

Output must be human-readable and machine-friendly enough for reports:

```json
{
  "changed_files": [...],
  "linted_files": [...],
  "exit_code": 0,
  "policy": "changed_files_no_new_errors"
}
```

It can print JSON at the end or write an artifact file if the acceptance framework supports artifacts.

## 8. Acceptance report requirements

Acceptance report must distinguish:

```text
full_lint_baseline: failed_known_existing
changed_files_lint: passed
```

For pilot 002 report, include:

```text
full pnpm lint baseline summary: 298 errors / 75 files, pre-existing
changed files list
changed lintable files list
changed-file lint command
changed-file lint result
pnpm typecheck result
pnpm test:run result
```

Do not claim pilot PASS merely because full lint debt is old. The report must show that changed files did not introduce new lint errors.

## 9. Required scenario update

Update `tests_live/scenarios/solarsage-ui-safe-pilot-002.yaml` to use baseline-aware lint.

Target shape:

```yaml
id: solarsage-ui-safe-pilot-002
target_repo_worktree: true
lint_policy: changed_files_no_new_errors
waves:
  - id: W1
    title: Solar Sage UI-safe pilot 002
    packets:
      - id: P1
        role: coder
        acceptance_profile: NORMAL
        verification:
          t0:
            commands:
              - git status --short
          t1:
            commands:
              - python3 /path/to/grace/scripts/grace_changed_files_lint.py --repo . --base-sha "$BASE_SHA"
              - pnpm typecheck
          t2:
            commands:
              - pnpm test:run
```

If the acceptance runner cannot interpolate `$BASE_SHA`, add support for passing base SHA into command environment.

## 10. Required tests

Add unit tests for changed-file lint filtering:

```text
no changed lintable files => pass / skip
changed .tsx file => eslint command includes only that file
changed generated/vendor file => excluded
changed .md file => ignored
multiple changed frontend files => all passed to eslint
eslint non-zero => gate fails
```

Add runner/acceptance tests:

```text
scenario lint_policy parsed
BASE_SHA available to verification commands
t1 changed-file lint failure marks acceptance failed
t1 changed-file lint pass + full baseline lint fail informational does not block
```

Add regression test for T0 ruff behavior:

```text
ruff check must not be run on .ts/.tsx files
```

## 11. Pilot 002 rerun requirements

After implementing this TZ:

1. Re-run Solar Sage pilot 002.
2. Keep `acceptance_profile=NORMAL`.
3. Use target repo mode:

```text
GRACE_TARGET_REPO_ROOT=/opt/solarsage-astro
GRACE_WORKSPACE_MODE=target_repo_worktree
GRACE_WORKTREE_ROOT=/tmp/grace-agent-worktrees
GRACE_REQUIRE_CLEAN_TARGET_REPO=1
GRACE_REQUIRE_REMOTE_SYNC=1
```

4. Create or update:

```text
docs/work/REPORT_SOLARSAGE_DRY_PILOT_002.md
```

## 12. Pass criteria

This TZ passes only if:

1. Existing full-repo `pnpm lint` baseline debt no longer blocks pilot 002 by itself.
2. Changed frontend files are linted.
3. New lint errors in changed files fail acceptance.
4. No changed lintable files produces clear skip/pass.
5. `pnpm typecheck` still runs.
6. `pnpm test:run` still runs.
7. T0 ruff does not run on TS/TSX files.
8. Pilot 002 report clearly states baseline lint debt separately from changed-file lint result.
9. Target repo evidence remains present:
   - `workspace_mode=target_repo_worktree`
   - `commit_semantics=target_repo_commit`
   - `target_repo_preflight.success=true`
10. Full tests pass.

## 13. Fail criteria

Fail if:

```text
full pnpm lint is silently ignored without changed-file lint replacement
new lint errors in changed files are allowed
changed .tsx/.ts files are not linted
BASE_SHA is missing and diff is computed against the wrong base
T1 passes without any meaningful lint check
pnpm typecheck is removed from T1 without separate approval
pnpm test:run is removed from T2 without separate approval
ruff again runs on TS/TSX files
```

## 14. What remains after this

After this passes, continue with Solar Sage pilot 002.

If pilot 002 then fails on `pnpm typecheck` due to pre-existing baseline debt, write a separate TZ:

```text
TZ_SOLARSAGE_TYPECHECK_BASELINE_STRATEGY.md
```

Do not mix typecheck baseline strategy into this lint-specific patch unless absolutely necessary.
