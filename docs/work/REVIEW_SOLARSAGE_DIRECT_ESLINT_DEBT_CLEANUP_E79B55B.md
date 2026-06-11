# Review: Solar Sage direct ESLint debt cleanup — e79b55b

Date: 2026-06-11 (updated 2026-06-11 — blocker resolved)
Reviewed commits:
- `e79b55b78ee09eb1eedd10d2bfaf2a86834d3e1a` (cleanup)
- `1285fae972c5b6cc6638e7301f1aff5dbe70f8d8` (report)
Solar Sage repo: `basilivanov/solarsage-astro`
Branch reviewed: `chore/eslint-debt-cleanup`
Base commit: `e8e9a7bd0393a6626c1e7dab5f621e71359f8bcc`
TZ: `docs/work/TZ_SOLARSAGE_DIRECT_ESLINT_DEBT_CLEANUP.md`
Report: `docs/grace/eslint-debt-cleanup-report.md` (in Solar Sage repo at commit `1285fae`)
Verdict: **ACCEPTED — all pass criteria met**

> **Revision note:** Initial review placed a `PARTIAL ACCEPT` blocker because the report `docs/grace/eslint-debt-cleanup-report.md` was not yet committed. The report was subsequently committed at `1285fae` and pushed to `origin/chore/eslint-debt-cleanup`. All 8 criteria are now satisfied.

## 1. Summary

Direct coder session eliminated **298→0 ESLint errors** in Solar Sage across 35 files. Three verification gates all pass.

## 2. Pass criteria evaluation

### C1: `pnpm lint` passes ✅

```
0 errors, 2 warnings (pre-existing react-hooks/exhaustive-deps)
```

### C2: `pnpm typecheck` passes ✅

`tsc --noEmit` exits 0.

### C3: `pnpm test:run` passes ✅

```
66 files passed, 746 passed, 1 skipped
```

1 skipped test (`natal-component-states` — pre-existing, unrelated).

### C4: No new dependencies added ✅

No changes to `package.json` or `pnpm-lock.yaml`. Only `eslint.config.mjs` modified.

### C5: No auth/payment/subscription/schema/deployment behavior changed ✅

No files in those areas modified.

### C6: No broad ESLint-disable workaround introduced ✅

No `/* eslint-disable */` or `// eslint-disable-next-line` added. The `no-unused-vars` rule is configured with standard `argsIgnorePattern`/`varsIgnorePattern: "^_"` — this is correct ESLint configuration, not a rule disablement. The three ESLint directives that were *removed* (stale `no-undef` and `@next/next/no-img-element`) were already unnecessary.

### C7: Changes are understandable ✅

Single commit with a clear message; 35 files with mechanical fixes (unused imports removed, unused params renamed, empty blocks documented, broken comment fixed).

### C8: Final report exists ✅

`docs/grace/eslint-debt-cleanup-report.md` in Solar Sage repo at commit `1285fae`.

## 3. What was done

### `eslint.config.mjs` — 3 changes

1. **`languageOptions.globals`** block with 30 browser/DOM/React globals → eliminated 227 `no-undef` false positives (the flat config does not automatically inherit `env` from `.eslintrc`)
2. **`no-unused-vars`** configured with `argsIgnorePattern: "^_"` and `varsIgnorePattern: "^_"` — standard TypeScript convention
3. **`apps/solarsage/**`** added to ignores (Python venv JS files)

### 32 source files batch-fixed

| Pattern | Files | Errors |
|---------|-------|--------|
| Unused imports removed | 6 | ~12 |
| Unused callback params renamed with `_` | 15 | ~28 |
| Unused destructured vars removed | 3 | ~5 |
| Unused consts removed/commented | 3 | ~4 |
| Unused type params renamed with `_` | 3 | ~6 |
| Broken commented-out `useCallback` body properly commented | 1 | 1 parse |
| `catch {}` → `catch { /* noop */ }` | 10 blocks in 1 file | 10 |
| Stale `eslint-disable` directives removed | 2 files | 1 |

## 4. Specific findings

### 4.1 `eslint.config.mjs` globals — correct approach

The `languageOptions.globals` block uses exact `"readonly"` access for each global. This is the correct ESLint flat-config equivalent of `env: { browser: true }`.

### 4.2 `no-unused-vars` with `_` prefix — standard pattern

The `no-unused-vars` configuration with `argsIgnorePattern`/`varsIgnorePattern: "^_"` is the standard ESLint approach for TypeScript projects. This is not a rule disablement — the rule still fires on any genuinely unused variable that does not start with `_`.

### 4.3 `hero-section.tsx` — `name` prop removed from destructuring

The `name` prop was unused in the function body. Removing it from destructuring is safe — `Props` type still declares it, so callers pass it fine.

### 4.4 `horary-screen.tsx` — broken commented-out `useCallback`

Lines 293-300 had a partially commented `useCallback`:
```tsx
// const pollStatus = useCallback((id: string) => {
    setActiveQuestionId(id)
    ...
  }, [pollAllProcessing])
```
This caused a parsing error (`Declaration or statement expected`). All lines are now properly commented.

### 4.5 `apps/solarsage/**` ignored — not hiding active code

`apps/solarsage/` is a **separate Python data-processing project** in the monorepo (Dockerfile, `pyproject.toml`, Makefile, Python scripts, `venv/`). The `venv/` contains Node/pip wrapper JS files that ESLint was flagging as `no-undef`. These are not Solar Sage frontend source files.

Before adding the ignore, ESLint reported errors from:
```
apps/solarsage/venv/bin/pip                      # JS vendor wrappers
apps/solarsage/venv/bin/pip3                     # JS vendor wrappers
apps/solarsage/venv/lib/python3.12/site-packages/...  # Python site-packages
```

No active frontend code is hidden. The `.gitignore` in that directory already excludes `venv/` from git — the ESLint ignore is consistent.

**Check:** `rg "export|function|const" apps/solarsage/ -g "*.{ts,tsx,js,jsx}"` returns no results — there are no frontend source files in this directory.

### 4.6 Two pre-existing warnings left as-is

```text
react-hooks/exhaustive-deps — 2 warnings
```
These are `useEffect` missing-dependency warnings in production code. Fixing them requires semantic judgement and is outside the mechanical-cleanup scope.

## 5. Hard-constraint check (TZ §7)

| Constraint | Status |
|-----------|--------|
| auth | not touched ✅ |
| payments | not touched ✅ |
| subscriptions | not touched ✅ |
| billing | not touched ✅ |
| API contracts | not touched ✅ |
| database/schema/migrations | not touched ✅ |
| production deployment config | not touched ✅ |
| .env files | not touched ✅ |
| package manager lockfile | not touched ✅ |
| No new dependencies | ✅ |
| No global reformatting | ✅ (only targeted mechanical fixes) |
| No broad ESLint disable | ✅ (globals config + `_` pattern are standard configuration) |

## 6. Forbidden-check (TZ §8)

| Forbidden | Status |
|-----------|--------|
| New business logic | not introduced ✅ |
| New API calls | not introduced ✅ |
| New package dependencies | not introduced ✅ |
| Large component rewrites | not done ✅ |
| State machine changes | not done ✅ |
| Data model changes | not done ✅ |

## 7. Exception report

No `eslint-disable` or `eslint-disable-next-line` comments were added. Two stale ones were removed:

- `components/profile/avatar.tsx`: `// eslint-disable-next-line @next/next/no-img-element` — was already unnecessary (the rule is not enabled in the config)
- `lib/env/production-guard.mjs`: `/* eslint-disable no-undef */` — became unnecessary after the globals config

## 8. Decision

```text
ACCEPTED
```

Solar Sage ESLint debt cleanup passes all 8 TZ criteria. The repo now has 0 ESLint errors vs 298 before.

**Blocker resolution:** The mandatory report `docs/grace/eslint-debt-cleanup-report.md` was committed at `1285fae` and pushed to `origin/chore/eslint-debt-cleanup`. Criterion #8 is now satisfied.

## 9. Next steps

1. Create a PR from `chore/eslint-debt-cleanup` targeting Solar Sage `main`
2. Merge after review
3. Re-run pilot 002 baseline compare to confirm changed-file lint still passes
4. Proceed to production pilots (W-2.x) with zero-lint baseline
