# TZ: Solar Sage pilot 003 — context-builder full smoke

Date: 2026-06-11
Status: ready
Priority: P0 context-builder flow validation
Scope: Solar Sage target repo via GRACE `target_repo_worktree`

Related:
- `docs/work/TZ_SOLARSAGE_PILOT_002_TABBAR_CONTRACT.md`
- `docs/work/REPORT_SOLARSAGE_PILOT_002_TABBAR_CONTRACT.md`
- `tests_live/scenarios/solarsage-pilot-002-tabbar-contract.yaml`
- `docs/work/TZ_ARCHITECT_UNIVERSAL_GRACE_PROMPT_V002.md`

## 1. Goal

Run a minimal Solar Sage pilot that proves the updated GRACE context-builder is actually used before architect/coder execution.

This pilot is intentionally tiny.

Main validation target:

```text
context-builder must run and produce a bounded context bundle
architect must receive/use the bundle pointer
coder must make a minimal allowed change in Solar Sage target worktree
```

## 2. Minimal product/test change

Add one focused unit test to the existing TabBar test coverage.

Target behavior:

```text
When pathname is /profile, Profile tab has aria-current="page" and the other tabs do not.
```

Expected changed file:

```text
__tests__/components/TabBar.test.tsx
```

No production code change is expected.

## 3. Why this is a good full context-builder smoke

Pilot 002 already added stable `data-testid` values to the TabBar and initial tests.

Pilot 003 should force the context-builder to collect the relevant context:

```text
components/today/tab-bar.tsx
__tests__/components/TabBar.test.tsx
```

The architect should then produce a tiny bounded packet from the context bundle.

## 4. Execution ownership

Correct flow:

```text
GRACE operator/scenario seed
  -> context-builder bounded bundle
  -> architect-premium v0.02
  -> coder in Solar Sage target_repo_worktree
  -> gates/evidence/report
  -> reviewer/acceptance
```

The architect should not be the first stage.

The context-builder is Stage 1/Wave 0 for this pilot.

## 5. Required preflight

Before run:

```bash
cd /opt/solarsage-astro

git checkout main
git pull --ff-only

git status --short
pnpm lint
pnpm typecheck
pnpm test:run
```

Required:

```text
git status --short is empty
pnpm lint: PASS, 0 errors
pnpm typecheck: PASS
pnpm test:run: PASS
```

Stop if baseline is not clean.

## 6. Workspace config

Target repo:

```text
/opt/solarsage-astro
```

Workspace mode:

```text
target_repo_worktree
```

Worktree root:

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
```

## 7. Context-builder requirements

This pilot is not accepted unless context-builder actually runs.

Required evidence:

```text
Context runs >= 1
context_builder.enabled=true
context_bundle_path present
context_bundle_url present or explicitly unavailable
context_bundle_summary present
selected_files include TabBar source/test context
bundle does not include GRACE source files
bundle does not include node_modules/.next/dist/build/coverage/.git/venv/site-packages
```

Context bundle should include short excerpts/contracts/snippets for:

```text
components/today/tab-bar.tsx
__tests__/components/TabBar.test.tsx
```

If contract markers are absent in Solar Sage frontend files, the bundle should still include short relevant snippets and note missing contracts. Missing contracts in Solar Sage frontend are not a failure for this pilot.

## 8. Architect requirements

Architect must consume the scenario seed and context bundle pointer.

Architect output must include:

```text
context_strategy.mode = contract_first
context_strategy.context_bundle_path != null
allowed_files = ["__tests__/components/TabBar.test.tsx"]
forbidden_files includes package/lock/env/auth/payment/subscription/schema/deployment zones
verification includes pnpm lint/typecheck/test:run
risk_level = low
```

## 9. Allowed files

Allowed changed files:

```text
__tests__/components/TabBar.test.tsx
```

Forbidden changed files:

```text
components/today/tab-bar.tsx
package.json
pnpm-lock.yaml
.env*
next.config.*
app/**
pages/**
lib/auth/**
lib/payments/**
lib/subscriptions/**
lib/billing/**
database/schema/migrations/**
production/deployment config
```

## 10. Coder packet intent

Coder should make only this minimal test change:

```text
Add a unit test that mocks pathname=/profile and asserts:
- today-tab-profile has aria-current="page"
- today-tab-today does not have aria-current="page"
- today-tab-calendar does not have aria-current="page"
- today-tab-readings does not have aria-current="page"
- today-tab-chat does not have aria-current="page"
```

No production code should be changed.

## 11. Required gates

Run from Solar Sage worktree:

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
only __tests__/components/TabBar.test.tsx changed
pnpm lint: 0 errors
pnpm typecheck: PASS
pnpm test:run: PASS
```

## 12. Report

Create GRACE report:

```text
docs/work/REPORT_SOLARSAGE_PILOT_003_CONTEXT_BUILDER_FULL_SMOKE.md
```

Report must include:

```text
GRACE commit tested
Solar Sage base SHA
Solar Sage agent commit SHA
Solar Sage merge commit SHA if merged
scenario path
context runs count
context_bundle_path
context_bundle_summary
selected_files
architect output summary
workspace mode
target repo root
changed files
gates and outputs
pass/fail verdict
```

## 13. Pass criteria

Pilot 003 passes only if:

1. Preflight baseline passes.
2. Context-builder actually runs (`Context runs >= 1`).
3. Context bundle path exists and is recorded.
4. Context bundle is bounded and includes relevant TabBar/test context.
5. Architect receives context bundle pointer and emits bounded packet.
6. Agent workspace is Solar Sage target repo worktree.
7. Only `__tests__/components/TabBar.test.tsx` changes.
8. New `/profile` active-tab test is added.
9. `pnpm lint` passes with 0 errors.
10. `pnpm typecheck` passes.
11. `pnpm test:run` passes.
12. No production code, package files, auth/payment/subscription/schema/deployment files change.
13. Final report exists.

## 14. Fail criteria

Fail if:

```text
Context runs = 0
context_bundle_path missing
context-builder reads outside cwd or includes excluded directories
architect ignores context bundle pointer
changed files outside allowed scope
production code changes
package/lock/env/auth/payment/subscription/schema/deployment touched
any required gate fails
```

## 15. Next step after pass

If this passes, the updated flow becomes acceptable for small production pilots:

```text
context-builder -> architect -> bounded coder packet -> verifier/reviewer
```

Next pilot can be a tiny user-visible Today-screen micro-polish.
