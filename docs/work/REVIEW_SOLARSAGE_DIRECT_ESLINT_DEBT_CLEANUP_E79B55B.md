# Review: Solar Sage direct ESLint debt cleanup — e79b55b

Date: 2026-06-11
Solar Sage repo: `basilivanov/solarsage-astro`
Branch reviewed: `chore/eslint-debt-cleanup`
Reviewed commit: `e79b55b78ee09eb1eedd10d2bfaf2a86834d3e1a`
Base commit: `e8e9a7bd0393a6626c1e7dab5f621e71359f8bcc`
TZ: `docs/work/TZ_SOLARSAGE_DIRECT_ESLINT_DEBT_CLEANUP.md`
Verdict: **PARTIAL ACCEPT — CODE CLEANUP LOOKS GOOD, BLOCKED UNTIL REPORT IS COMMITTED / VERIFIED**

## 1. Summary

The branch is one commit ahead of Solar Sage `main` and changes 35 files. The diff is mostly mechanical ESLint cleanup:

```text
unused imports removed
unused function parameters renamed to _param
unused locals removed or renamed
empty catches documented with noop
ESLint browser/global config added
```

This matches the intended direct-coder cleanup style.

However, the required report file declared by the TZ is not present in the reviewed branch:

```text
docs/grace/eslint-debt-cleanup-report.md
```

Attempting to fetch it from `chore/eslint-debt-cleanup` returned `404 Not Found`.

Because the TZ explicitly requires the final report, this review cannot mark the branch fully accepted yet.

## 2. What is accepted

### 2.1 Direct coder mode

Accepted.

This cleanup was done in Solar Sage branch `chore/eslint-debt-cleanup`, not through GRACE target worktree. That matches the TZ.

### 2.2 Scope and size

Accepted with caution.

The branch is one commit ahead of `main`, with 35 modified files. No package files were changed in the compare result, so there is no apparent dependency/lockfile churn.

### 2.3 Package scripts/gates exist

Accepted.

Solar Sage has the expected scripts:

```text
pnpm lint      -> eslint .
pnpm typecheck -> tsc --noEmit
pnpm test:run -> vitest run
```

### 2.4 ESLint config change is understandable

Accepted with caution.

The config now defines browser/DOM/React globals and keeps React Hooks rules enabled for TSX/JSX files. This is a legitimate way to remove `no-undef` false positives in a browser/React app.

The config also still runs `react-hooks/rules-of-hooks` as error and `react-hooks/exhaustive-deps` as warning on TSX/JSX files.

## 3. Blocker

### B1. Required final report is missing from branch

The TZ required:

```text
docs/grace/eslint-debt-cleanup-report.md
```

But the file is not present in the branch I reviewed.

Required fix:

```text
1. Add docs/grace/eslint-debt-cleanup-report.md to Solar Sage branch.
2. Include baseline count: 298 errors.
3. Include final count: 0 errors.
4. Include affected file count before/after.
5. Include exact commands run:
   - pnpm lint
   - pnpm typecheck
   - pnpm test:run
6. Include final command results.
7. Include any ESLint disables or config ignores added and why.
8. Push branch again.
```

Until this file exists, the TZ pass criterion #8 is not satisfied.

## 4. Major caution

### M1. `eslint.config.mjs` ignores `apps/solarsage/**`

The branch adds/contains an ignore entry:

```text
apps/solarsage/**
```

This may be harmless if `apps/solarsage/**` is a legacy or irrelevant tree. But because the goal was to eliminate lint debt, not hide active code, the report must explicitly justify this ignore.

Required in report:

```text
Why apps/solarsage/** is ignored.
Whether it contains active production code.
Whether any of the 298 baseline errors were removed only by ignoring this path.
```

If active code is hidden by this ignore, the branch should not be accepted.

### M2. Some changes are mechanical but still behavior-adjacent

Examples:

```text
telegram-init.tsx: empty catch blocks changed/commented
horary-screen.tsx: commented-out useCallback block adjusted
avatar.tsx: eslint-disable removed around img element
```

These are probably safe, but the final report should call out any non-trivial manual fixes.

## 5. Required verification before full acceptance

After adding the missing report, run and record:

```bash
cd /opt/solarsage-astro

git status --short
pnpm lint
pnpm typecheck
pnpm test:run
```

Expected:

```text
pnpm lint: PASS, 0 errors
pnpm typecheck: PASS
pnpm test:run: PASS
git status clean after commit
```

## 6. Decision

Current decision:

```text
PARTIAL ACCEPT
```

Reason:

```text
Code cleanup direction looks good, but final report required by TZ is missing from the reviewed branch.
```

After the report is committed and verification results are included, this can move to:

```text
ACCEPTED — ESLint debt cleanup complete
```

## 7. Next action

Push one follow-up commit to `chore/eslint-debt-cleanup`:

```text
docs: add ESLint debt cleanup report
```

Then request a quick re-review.
