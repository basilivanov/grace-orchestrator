# TZ: Solar Sage direct ESLint debt cleanup

Date: 2026-06-11
Status: ready for direct coder execution
Priority: P0 technical debt cleanup
Scope: Solar Sage repository only, direct coder run, ESLint baseline cleanup

Related:
- `docs/work/TZ_SOLARSAGE_LINT_BASELINE_STRATEGY.md`
- `docs/work/TZ_SOLARSAGE_DRY_PILOT_002.md`
- `docs/work/REPORT_SOLARSAGE_DRY_PILOT_002.md`

## 1. Problem

Solar Sage currently has a large pre-existing ESLint debt:

```text
~298 ESLint errors across ~75 files
```

GRACE now has a baseline-aware changed-file lint gate, so small pilots are unblocked.

But this is still technical debt. It should be cleaned up directly in the Solar Sage repo.

This cleanup must not go through the GRACE orchestrator.

It should be run by a direct coder agent inside Solar Sage:

```text
cd /opt/solarsage-astro
coder agent works directly here
```

## 2. Goal

Reduce Solar Sage ESLint debt to zero, or as close to zero as possible without changing product behavior.

Primary target:

```bash
pnpm lint
```

must pass.

Secondary gates:

```bash
pnpm typecheck
pnpm test:run
```

must pass after cleanup.

## 3. Execution mode

This task is **direct coder mode**.

Do not use:

```text
GRACE target_repo_worktree
GRACE live runner
GRACE scenario YAML
GRACE acceptance packet
```

Use direct shell/agent session in Solar Sage repo:

```bash
cd /opt/solarsage-astro
```

Recommended branch:

```bash
git checkout main
git pull --ff-only origin main
git checkout -b chore/eslint-debt-cleanup
```

The coder should work directly in this branch.

## 4. Preflight

Before starting:

```bash
cd /opt/solarsage-astro

git status --short
git branch --show-current
git rev-parse HEAD
git rev-parse origin/main
pnpm --version
node --version
```

Required:

```text
git status --short is empty
current branch is main or dedicated cleanup branch
base is synced with origin/main
node/pnpm available
```

If repo is dirty:

```text
STOP. Commit or stash existing changes first. Do not auto-stash silently.
```

## 5. Baseline capture

Before changes, capture the baseline:

```bash
pnpm lint 2>&1 | tee /tmp/solarsage-eslint-baseline.txt
```

Also capture structured output if possible:

```bash
pnpm exec eslint . --format json > /tmp/solarsage-eslint-baseline.json || true
```

Record:

```text
total error count
total warning count
number of affected files
top rule IDs
```

This goes into the final report.

## 6. Cleanup strategy

Do the cleanup in safe batches.

Recommended order:

### 6.1 Auto-fixable errors first

Run:

```bash
pnpm exec eslint . --fix
```

Then:

```bash
pnpm lint
pnpm typecheck
pnpm test:run
```

Commit if this batch is clean and behavior-safe:

```bash
git add -A
git commit -m "chore: apply eslint auto-fixes"
```

### 6.2 Manual fixes by rule group

Fix remaining errors by rule family, not randomly file-by-file.

Common safe groups:

```text
unused imports / unused vars
missing React hook deps
prefer-const
no-explicit-any
no-console
jsx escaping
import/order or sort rules
```

For each group:

```text
1. inspect exact errors
2. apply minimal mechanical fixes
3. run pnpm lint
4. run pnpm typecheck
5. run relevant tests or pnpm test:run
6. commit a small batch
```

Preferred commit style:

```text
chore: fix unused imports and variables
chore: fix jsx lint issues
chore: fix hook dependency lint errors
chore: fix remaining eslint violations
```

### 6.3 Avoid risky semantic changes

For lint cleanup, do not rewrite feature logic.

If a lint error requires a non-trivial behavior decision, do not guess.

Instead leave a clear note in the report:

```text
manual decision required: <file>, <rule>, <reason>
```

## 7. Hard constraints

Do not touch unless directly required by lint and reviewed carefully:

```text
auth
payments
subscriptions
billing
API contracts
database/schema/migrations
production deployment config
.env files
package manager lockfile
```

Do not add dependencies.

Do not reformat the whole repository unless ESLint/Prettier explicitly does it through existing config.

Do not disable ESLint rules globally to make the task pass.

Do not add blanket ignores such as:

```text
/* eslint-disable */
// eslint-disable-next-line
```

except for rare cases where the code is intentionally structured that way and the final report explains each exception.

## 8. Allowed changes

Allowed:

```text
remove unused imports
remove unused variables
rename unused function parameters to _param if project convention allows
replace let with const
fix escaping in JSX
fix missing keys if obviously safe
narrow simple any types when obvious
extract stable callbacks/memo values only when mechanically safe
adjust dependency arrays only when semantically correct
```

Allowed with caution:

```text
React hook dependency fixes
no-explicit-any fixes
complex type narrowing
logic-preserving refactors
```

Forbidden unless explicitly approved:

```text
new business logic
new API calls
new package dependencies
large component rewrites
state machine changes
data model changes
```

## 9. Verification gates

After each meaningful batch:

```bash
pnpm lint
pnpm typecheck
pnpm test:run
```

At the end, all must pass:

```bash
pnpm lint
pnpm typecheck
pnpm test:run
```

If `pnpm test:run` has pre-existing unrelated failures, capture them exactly and do not hide them.

If cleanup causes new test failures, fix them or revert the risky change.

## 10. Final checks

Before final commit/push:

```bash
git status --short
git diff --stat
git log --oneline -10
pnpm lint
pnpm typecheck
pnpm test:run
```

Expected:

```text
pnpm lint: PASS
pnpm typecheck: PASS
pnpm test:run: PASS
no unrelated file changes
no package/lockfile changes unless explicitly justified
```

## 11. Final report

Create a report in Solar Sage repo:

```text
docs/grace/eslint-debt-cleanup-report.md
```

The report must include:

```text
base commit SHA
final commit SHA(s)
baseline lint error count
final lint error count
affected file count before/after
top fixed rule groups
commands run
verification results
any exceptions / eslint disables added
any remaining issues
```

Also create a short GRACE-side report later if this cleanup is coordinated from GRACE docs, but the primary report belongs in Solar Sage.

## 12. Pass criteria

This task passes only if:

1. `pnpm lint` passes in Solar Sage.
2. `pnpm typecheck` passes.
3. `pnpm test:run` passes.
4. No new dependencies are added.
5. No auth/payment/subscription/schema/deployment behavior is changed.
6. No broad ESLint-disable workaround is introduced.
7. Changes are split into understandable commits or at least clear logical chunks.
8. Final report exists at:

```text
docs/grace/eslint-debt-cleanup-report.md
```

## 13. Fail criteria

Fail if:

```text
ESLint rules are globally disabled to hide debt
pnpm lint still fails without documented blocker
pnpm typecheck fails due to cleanup
pnpm test:run fails due to cleanup
business logic is changed unnecessarily
large risky refactor is made without need
package.json/pnpm-lock.yaml changed without explicit reason
```

## 14. Suggested direct coder prompt

Use this prompt directly in the Solar Sage repo:

```text
You are working directly in /opt/solarsage-astro, not through GRACE.

Task: clean up the existing ESLint debt until pnpm lint passes, without changing product behavior.

Before changing anything:
- verify git status is clean
- create/use branch chore/eslint-debt-cleanup
- run pnpm lint and capture baseline

Rules:
- do not touch auth, payments, subscriptions, database/schema, production config, env files, or package dependencies unless absolutely necessary and explicitly justified
- do not globally disable ESLint rules
- do not add blanket eslint-disable comments
- prefer mechanical safe fixes: unused imports, unused vars, prefer-const, JSX escaping, obvious type fixes
- for risky hook/type fixes, keep changes minimal and explain them

After each batch run:
- pnpm lint
- pnpm typecheck
- pnpm test:run

Final deliverables:
- pnpm lint passes
- pnpm typecheck passes
- pnpm test:run passes
- create docs/grace/eslint-debt-cleanup-report.md with baseline count, final count, changed files, commands run, and any exceptions
```
