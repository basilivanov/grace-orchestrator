# TZ: Solar Sage pilot 004 — frontend multi-wave tooltip smoke

Date: 2026-06-11
Status: ready
Priority: P0 live Solar Sage multi-wave frontend pipeline validation
Scope: Solar Sage target repo via GRACE `target_repo_worktree`

Related:
- `docs/work/TZ_SOLARSAGE_PILOT_003_CONTEXT_BUILDER_FULL_SMOKE.md`
- `docs/work/REVIEW_SOLARSAGE_PILOT_003_FULL_PASS_632EAC2.md`
- `docs/work/REVIEW_AUTO_GATES_BLOCKERS_53F7680.md`

## 1. Goal

Run the next small live Solar Sage pilot after pilot 003.

This pilot must validate the fuller GRACE path with a tiny real frontend change split across multiple waves:

```text
Stage 0 read-only context-builder
→ architect-premium with context bundle
→ W1 production frontend micro-polish
→ W1 acceptance/reviewer/merge gate
→ W2 focused unit-test coverage
→ W2 acceptance/reviewer/merge gate
→ final target repo merge/report
```

The product change is intentionally tiny and low-risk. The main point is to exercise the orchestration path, wave ordering, frontend T0/T1/T2 gates, evidence, reviewer, and final report.

## 2. Why this follows pilot 003

Pilot 003 proved:

```text
context-builder runs before architect/coder
context bundle is real and bounded
coder runs inside Solar Sage target_repo_worktree
small frontend test-only change can pass lint/typecheck/test
```

Pilot 004 should now prove a slightly more complete frontend pipeline:

```text
one production TSX change in W1
one test TSX change in W2
separate acceptance/reviewer gate per wave
full final acceptance after both waves
```

## 3. Target repository

Target repo:

```text
/opt/solarsage-astro
```

Expected GitHub repo:

```text
basilivanov/solarsage-astro
```

Workspace mode:

```text
target_repo_worktree
```

Agent worktree root:

```text
/tmp/grace-agent-worktrees
```

Required environment:

```bash
GRACE_TARGET_REPO_ROOT="/opt/solarsage-astro"
GRACE_WORKSPACE_MODE="target_repo_worktree"
GRACE_WORKTREE_ROOT="/tmp/grace-agent-worktrees"
GRACE_REQUIRE_CLEAN_TARGET_REPO=1
GRACE_REQUIRE_REMOTE_SYNC=1
GRACE_LIVE_AGENT_TESTS=1
```

## 4. Required preflight

Before starting:

```bash
cd /opt/solarsage-astro

git checkout main
git pull --ff-only

git status --short
git rev-parse HEAD
git rev-parse origin/main
pnpm lint
pnpm typecheck
pnpm test:run
```

Required:

```text
git status --short is empty
HEAD == origin/main
pnpm lint: PASS, 0 errors
pnpm typecheck: PASS
pnpm test:run: PASS
```

Stop if baseline is not clean.

## 5. Context-builder requirements

Context-builder must run as Stage 0 and remain read-only.

Required evidence:

```text
context_builder.enabled=true
context_runs >= 1
context_bundle_path present
context_bundle_summary present
mutation_detected=false
selected_files include components/today/tab-bar.tsx
selected_files include __tests__/components/TabBar.test.tsx
bundle excludes node_modules/.next/dist/build/coverage/.git/venv/site-packages
```

Context bundle should include bounded excerpts for:

```text
components/today/tab-bar.tsx
__tests__/components/TabBar.test.tsx
scripts/grace_front_lint.py or note that frontend GRACE lint exists
package.json scripts relevant to lint/typecheck/test
```

## 6. Architect requirements

Architect must consume the context bundle pointer and emit explicit waves.

Required architect output:

```text
context_strategy.mode = contract_first
context_strategy.context_bundle_path != null
risk_level = low
wave_count >= 2 coder waves after Stage 0
W1 allowed_files = ["components/today/tab-bar.tsx"]
W2 allowed_files = ["__tests__/components/TabBar.test.tsx"]
forbidden_files include package/lock/env/auth/payment/subscription/schema/deployment zones
verification includes frontend T0/T1/T2 gates
```

Architect must not collapse W1 and W2 into one coder packet. The point of this pilot is multi-wave execution.

## 7. Product change

### W1 production frontend micro-polish

Allowed changed file:

```text
components/today/tab-bar.tsx
```

Required change:

```text
Add title={t.label} to each Today TabBar Link.
```

Expected final JSX shape:

```tsx
<Link
  href={t.href}
  data-testid={`today-tab-${t.key}`}
  title={t.label}
  aria-current={isActive ? "page" : undefined}
  ...
>
```

This is a small user-visible browser tooltip/accessibility-adjacent polish. It must not change layout, labels, hrefs, icons, routing, active-tab matching, styling, imports, package files, or app logic.

### W2 focused test coverage

Allowed changed file:

```text
__tests__/components/TabBar.test.tsx
```

Required test:

```text
Render <TabBar /> and assert every tab link exposes title equal to its visible label:
- today-tab-today title="Сегодня"
- today-tab-calendar title="Календарь"
- today-tab-readings title="Разборы"
- today-tab-chat title="Спросить"
- today-tab-profile title="Профиль"
```

The test must use existing `data-testid` selectors. Do not rewrite existing tests except for minimal local placement/formatting required by the new test.

## 8. Allowed file scope

Final allowed changed files:

```text
components/today/tab-bar.tsx
__tests__/components/TabBar.test.tsx
```

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

## 9. Hard constraints

Do not change:

```text
business logic
routing semantics
href values
visible tab labels
icons
active-tab rules
subscription/paywall logic
auth logic
payment/billing code
API contracts
database schema
feature flags
production config
visual layout
```

Do not add:

```text
new dependency
new eslint-disable
new broad ignore
large reformatting
snapshot update unrelated to TabBar
```

## 10. Required gates per coder packet

Run from the Solar Sage worktree.

T0 evidence:

```bash
git status --short
git diff --stat
git diff --name-only
python3 scripts/grace_front_lint.py components/today/tab-bar.tsx __tests__/components/TabBar.test.tsx
```

T1 evidence:

```bash
pnpm lint
pnpm typecheck
```

T2 evidence:

```bash
pnpm test:run
```

Expected:

```text
T0 frontend GRACE lint passes
pnpm lint: PASS, 0 errors
pnpm typecheck: PASS
pnpm test:run: PASS
changed files limited to packet allowed scope during each wave
final changed files limited to the two allowed files
```

## 11. Required reviewer/evidence checks

For W1 reviewer must verify:

```text
only components/today/tab-bar.tsx changed
Link receives title={t.label}
no labels/hrefs/icons/classes/routing/active matching changed
T0/T1/T2 pass
```

For W2 reviewer must verify:

```text
only __tests__/components/TabBar.test.tsx changed in W2
new title-attribute test exists
all five tab titles are asserted
T0/T1/T2 pass
```

Final reviewer/report must verify:

```text
context-builder ran once or more
architect used context bundle
two coder waves ran in order
W1 was accepted before W2 started
real_agent_runs >= 3 total if counting context-builder + two coder packets
watchdog_restarts = 0
failures = 0
final_state = accepted
```

## 12. Output report

Create final GRACE report:

```text
docs/work/REPORT_SOLARSAGE_PILOT_004_FRONTEND_MULTIWAVE_TOOLTIP_SMOKE.md
```

Report must include:

```text
GRACE commit tested
Solar Sage base SHA
Solar Sage W1 commit SHA
Solar Sage W2 commit SHA
Solar Sage final merge commit SHA if merged
context runs count
context_bundle_path
context_bundle_summary
selected_files
architect output summary
wave execution order
workspace mode
target repo root
changed files by wave
T0/T1/T2 command outputs by wave
reviewer verdict by wave
final pass/fail verdict
```

## 13. Pass criteria

Pilot 004 passes only if:

1. Solar Sage preflight baseline passes.
2. Context-builder runs and records a bounded bundle.
3. Architect receives the bundle pointer and emits at least two coder waves.
4. W1 changes only `components/today/tab-bar.tsx`.
5. W1 adds `title={t.label}` to the TabBar links.
6. W1 T0/T1/T2 and reviewer pass before W2 starts.
7. W2 changes only `__tests__/components/TabBar.test.tsx`.
8. W2 adds focused title assertions for all five tab links.
9. W2 T0/T1/T2 and reviewer pass.
10. Final changed files are limited to the two allowed files.
11. No package/lock/env/auth/payment/subscription/schema/deployment files change.
12. Final report exists in GRACE `docs/work`.

## 14. Fail criteria

Fail immediately if:

```text
context_runs = 0
context_bundle_path missing
architect collapses W1 and W2 into one coder packet
W2 starts before W1 accepted
changed files outside allowed scope
package.json or pnpm-lock.yaml changed
labels/hrefs/icons/classes/routing/active matching changed
business/auth/payment/subscription/schema/deployment files touched
new eslint-disable or broad ignore added
any required T0/T1/T2 gate fails
reviewer rejects either wave
API/watchdog restarts unexpectedly
OOM occurs
```

## 15. Next step after pass

If this passes, the next pilot can safely move from TabBar-only micro-polish to a tiny Today-screen content component change with the same two-wave production/test split.
