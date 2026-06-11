# TZ: Solar Sage pilot 002 — TabBar UI contract via target_repo_worktree

Date: 2026-06-11
Status: ready after post-merge baseline check
Priority: P0 first small real UI-safe target-worktree pilot
Scope: Solar Sage target repo only

Related:
- `docs/work/TZ_SOLARSAGE_DRY_PILOT_001.md`
- `docs/work/TZ_SOLARSAGE_DIRECT_ESLINT_DEBT_CLEANUP.md`
- `docs/work/REVIEW_SOLARSAGE_DIRECT_ESLINT_DEBT_CLEANUP_E79B55B.md`
- Solar Sage PR #1 merge commit: `967a2f02f16f30d629b88638d23d0ced884a19e9`

## 1. Goal

Run the first small real UI-safe Solar Sage pilot through GRACE `target_repo_worktree` mode after the ESLint debt cleanup has been merged.

This pilot must prove that GRACE can safely make a tiny production-code change in Solar Sage with full target-repo context and standard gates.

Change target:

```text
components/today/tab-bar.tsx
```

Functional scope:

```text
Add stable QA/test selectors to the Today bottom TabBar and cover its active-link contract with a focused unit test.
```

This is intentionally not a product/business feature.

## 2. Execution ownership

This TZ is executed from the GRACE/orchestrator side.

Correct model:

```text
GRACE/orchestrator reads this TZ
GRACE creates a Solar Sage target_repo_worktree
GRACE spawns coder-opencode inside that target worktree
coder edits only Solar Sage files
GRACE collects evidence and writes the final report in GRACE docs/work
```

The coder agent must not receive the GRACE repository as its workspace.

## 3. Prerequisite: post-merge baseline

Before starting this pilot, update Solar Sage `main` and verify the merged ESLint cleanup baseline:

```bash
cd /opt/solarsage-astro

git checkout main
git pull --ff-only

git status --short
pnpm lint
pnpm typecheck
pnpm test:run
```

Required baseline:

```text
git status --short is empty
pnpm lint: PASS, 0 errors, existing warnings only
pnpm typecheck: PASS
pnpm test:run: PASS
```

If this baseline fails, stop. Do not start pilot 002.

## 4. Target repository

Target repo:

```text
/opt/solarsage-astro
```

Expected GitHub repo:

```text
basilivanov/solarsage-astro
```

GRACE repo remains separate:

```text
/opt/grace-orchestrator
# or exported GRACE runtime path, e.g. /tmp/grace-orchestrator-export
```

Agent worktree root:

```text
/tmp/grace-agent-worktrees
```

## 5. Workspace mode

Must use:

```text
workspace_mode=target_repo_worktree
```

Must not use:

```text
scoped_copy
full_git_worktree of GRACE repo
```

Required environment:

```bash
GRACE_TARGET_REPO_ROOT="/opt/solarsage-astro"
GRACE_WORKSPACE_MODE="target_repo_worktree"
GRACE_WORKTREE_ROOT="/tmp/grace-agent-worktrees"
GRACE_REQUIRE_CLEAN_TARGET_REPO=1
GRACE_REQUIRE_REMOTE_SYNC=1
```

Use normal coder profile:

```text
coder-opencode
```

Do not use fixture profile:

```text
coder-opencode-fixture
```

## 6. Required preflight before run

Before starting GRACE runner:

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
current branch is main
HEAD == origin/main
no conflicting GRACE attempt worktree exists
```

If dirty:

```text
STOP. Commit or stash manually. Do not auto-stash.
```

## 7. Branch name

Create the Solar Sage work branch from current `main`:

```text
pilot/002-tabbar-contract
```

If GRACE branch naming is automatic, the generated branch must still be traceable to:

```text
pilot-002-tabbar-contract
```

## 8. Allowed change

### 8.1 Production code

File:

```text
components/today/tab-bar.tsx
```

Required change:

```text
Add stable test selectors to the TabBar without changing layout, visual copy, routing, or active-tab behavior.
```

Minimum acceptable implementation:

```tsx
<nav
  data-testid="today-tab-bar"
  aria-label="Основная навигация"
  ...
>
```

and each tab link gets a stable selector:

```tsx
data-testid={`today-tab-${t.key}`}
```

Existing behavior must stay unchanged:

```text
href values unchanged
labels unchanged
icons unchanged
aria-current behavior unchanged
active/inactive class behavior unchanged
```

### 8.2 Test

Add a focused unit test:

```text
__tests__/components/TabBar.test.tsx
```

Test requirements:

```text
mock next/navigation usePathname
render <TabBar />
assert root nav exists by data-testid="today-tab-bar" or role navigation
assert all five links render: Сегодня, Календарь, Разборы, Спросить, Профиль
assert /calendar pathname marks Календарь as aria-current="page"
assert non-active tabs do not have aria-current="page"
```

The test should not depend on current date except for existing Today href generation.

## 9. Allowed file scope

Allowed changed files:

```text
components/today/tab-bar.tsx
__tests__/components/TabBar.test.tsx
```

Optional only if the repo requires test setup adjustment:

```text
__tests__/setup.ts
vitest.config.*
```

But setup/config changes are discouraged and must be justified in the report.

Forbidden changed files:

```text
package.json
pnpm-lock.yaml
.env*
next.config.*
app/**
pages/**
lib/api/**
lib/auth/**
lib/payments/**
lib/subscriptions/**
lib/billing/**
database/schema/migrations/**
production/deployment config
```

## 10. Hard constraints

Do not change:

```text
business logic
routing semantics
subscription/paywall logic
auth logic
payment/billing code
API contracts
database schema
feature flags
production config
visual layout
copy text
icons
active-tab rules
```

Do not add:

```text
new dependency
new eslint-disable
new broad ignore
large reformatting
snapshot update unrelated to TabBar
```

## 11. Suggested agent packet

Give the coder a tiny packet like this:

```text
Solar Sage pilot 002: TabBar testability contract.

In /opt/solarsage-astro target_repo_worktree only:
1. Add data-testid="today-tab-bar" to the TabBar nav in components/today/tab-bar.tsx.
2. Add data-testid={`today-tab-${t.key}`} to each tab Link.
3. Add __tests__/components/TabBar.test.tsx covering five links and active aria-current for /calendar.
4. Do not change labels, hrefs, styles, active matching, icons, routing, package files, or app logic.
5. Run pnpm lint, pnpm typecheck, pnpm test:run.
```

## 12. Required gates

Run from the Solar Sage worktree:

```bash
pnpm lint
pnpm typecheck
pnpm test:run
```

Also record:

```bash
git diff --stat
git diff --name-only
git status --short
```

Expected:

```text
pnpm lint: PASS, 0 errors
pnpm typecheck: PASS
pnpm test:run: PASS
changed files limited to allowed scope
```

Existing warnings are allowed only if they are the known pre-existing `react-hooks/exhaustive-deps` warnings and not introduced by this pilot.

## 13. Required evidence

Final GRACE evidence must include:

```json
"workspace": {
  "workspace_mode": "target_repo_worktree",
  "workspace_path": "/tmp/grace-agent-worktrees/<packet>-attempt-0001",
  "target_repo_root": "/opt/solarsage-astro",
  "base_sha": "...",
  "commit_semantics": "target_repo_commit"
}
```

and:

```json
"target_repo_preflight": {
  "success": true,
  "is_git_repo": true,
  "working_tree_clean": true,
  "current_branch": "main",
  "local_head": "...",
  "remote_head": "...",
  "remote_sync": true,
  "worktree_conflict": false
}
```

Also record:

```text
agent --dir points to /tmp/grace-agent-worktrees/...
agent cwd points to /tmp/grace-agent-worktrees/...
workspace contains Solar Sage files
workspace does not contain GRACE files
changed files list
commands and exit codes
```

## 14. Output report

Create final report in GRACE repo:

```text
docs/work/REPORT_SOLARSAGE_PILOT_002_TABBAR_CONTRACT.md
```

Report must include:

```text
GRACE commit tested
Solar Sage base SHA
Solar Sage branch name
Solar Sage result commit SHA
workspace_mode
workspace_path
target_repo_root
preflight JSON snippet
workspace JSON snippet
changed files
diff summary
exact gates run
pnpm lint result
pnpm typecheck result
pnpm test:run result
whether GRACE files leaked into workspace
whether target source checkout remained clean
watchdog/API/OOM observation
pass/fail verdict
next recommended step
```

## 15. Pass criteria

Pilot 002 passes only if:

1. Post-merge Solar Sage baseline passes before start.
2. GRACE target preflight passes.
3. Agent workspace is a Solar Sage target repo worktree under `/tmp/grace-agent-worktrees`.
4. Agent does not receive GRACE repo as cwd or `--dir`.
5. Only allowed files are changed.
6. `TabBar` root has stable `data-testid="today-tab-bar"`.
7. Each tab link has stable `data-testid="today-tab-<key>"`.
8. New focused unit test covers links and `/calendar` active aria-current.
9. `pnpm lint` passes with 0 errors.
10. `pnpm typecheck` passes.
11. `pnpm test:run` passes.
12. No new dependencies, lockfile changes, eslint-disable comments, broad ignores, business logic, auth/payment/subscription/schema/deployment changes.
13. Final report exists in GRACE docs/work.

## 16. Fail criteria

Fail immediately if:

```text
target repo dirty before start
local HEAD != origin/main with remote sync required
agent --dir points to GRACE repo
workspace contains GRACE source files
changed files outside allowed scope
package.json or pnpm-lock.yaml changed
routing/hrefs/labels/active matching changed
business/auth/payment/subscription/schema/deployment files touched
new eslint-disable or broad ignore added
pnpm lint/typecheck/test:run fails
API/watchdog restarts unexpectedly
OOM occurs
```

## 17. Next step after pass

If pilot 002 passes:

```text
Solar Sage pilot 003: first tiny user-visible copy or Today-screen micro-polish behind normal gates.
```

Pilot 003 can be slightly more product-facing, but still must avoid auth/payment/subscription/schema/deployment and must remain under a narrow changed-file scope.
