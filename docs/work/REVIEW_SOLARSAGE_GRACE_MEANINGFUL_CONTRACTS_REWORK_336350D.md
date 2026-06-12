# Review: Solar Sage meaningful GRACE contracts rework

**Review status:** NEEDS_REWORK
**Date:** 2026-06-12

## Reviewed refs

- Target repo: `basilivanov/solarsage-astro`
- Previous reviewed head: `66c64a5`
- Reviewed head: `336350d`

## Summary

The rework fixes some previously cited examples (`lib/date.ts`, `components/app-shell.tsx`) and reportedly restores green tests, but the packet still fails the meaningful-contract acceptance bar.

The main remaining issue is not cosmetic: shell scripts contain TypeScript-style `//` markers and malformed joined marker lines, and `lib/env/production-guard.mjs` still contains placeholder `Library module` / `varies` boilerplate.

## Positive findings

### `lib/date.ts` improved

The file now has a meaningful role and module contract for date serialization/parsing/formatting. It no longer claims to be tests, and the module contract describes pure Date/string utilities.

### `components/app-shell.tsx` improved

The file now describes app shell layout, `TabBar`, onboarding hook dependency, and render debug logging. This addresses the previous sampled blocker.

## Blocking findings

### 1. Shell scripts have invalid comment syntax and malformed markers

Example: `scripts/deploy.sh` starts with bash shebang, then contains TypeScript-style `//` comments:

```sh
// ############################################################################
// AI_HEADER: MODULE_SCRIPTS_DEPLOY
...
// #########################################// START_MODULE_CONTRACT
```

This is invalid shell-comment style and keeps the exact malformed marker pattern that the rework claimed to fix.

Required fix:

- For `.sh` files, use `#` comments only.
- Make `START_MODULE_CONTRACT` a standalone line.
- Do not put `//` markers into shell files.
- Scan all shell scripts, especially files returned by search for `#####// START_MODULE_CONTRACT`.

### 2. `production-guard.mjs` still contains placeholder boilerplate

`lib/env/production-guard.mjs` still has:

- `purpose: Library module — lib/env/production-guard.mjs`
- `inputs: varies`
- `outputs: varies`
- `side_effects: varies`
- `emitted_logs: n/a`
- `invariants: n/a`

This directly violates the meaningful contracts acceptance criteria.

It should describe the actual behavior: reads env vars, throws on unsafe preview/production demo-mode configurations, emits console warning when demo mode is enabled.

### 3. Report is stale and contradicts the submitted rework

`docs/work/REPORT_SOLARSAGE_GRACE_MEANINGFUL_CONTRACTS_REWORK.md` still says:

- final SHA: `9049638`, not `336350d`;
- tests: `725 passed, 2 failed, 1 skipped`, despite the user reporting `756 passed, 1 skipped`;
- function contracts still need manual review;
- placeholders removed from all in-scope files, which is false because `production-guard.mjs` still contains `varies` and `Library module`.

Required fix:

- Update report to the actual reviewed SHA.
- Include exact gate output for `grace_lint`, backend tests, frontend tests, and coverage audit.
- Include remaining placeholder scan output.
- Do not mark PASS while acceptance criteria remain open.

### 4. Function contracts are still not fully accepted

`lib/date.ts` has a meaningful module contract, but exported functions still have only ordinary comments, not `START_FUNCTION_CONTRACT` blocks. The original acceptance criteria required public/exported/impure function contracts or documented skip reasons.

This may be acceptable for tiny pure helpers only if explicitly documented, but the report does not document skipped helpers.

Required fix:

- Either add function contracts for exported public helpers, or explicitly list them as skipped and justify that the module/block contract covers tiny pure helpers.

## Required rework

1. Scan and fix all malformed marker joins:
   - `#####// START_MODULE_CONTRACT`
   - `#####// START_MODULE_MAP`
   - `END_MODULE_CONTRACTexport`
   - any `// START_` in `.sh` files.
2. Fix all shell files to use `#` comments only.
3. Fix `lib/env/production-guard.mjs` contract semantics.
4. Re-run placeholder scan and include output in report.
5. Update final report to the actual final SHA and actual gates.
6. Document skipped public helper function contracts or add them.
7. Re-run gates:
   - `python3 scripts/grace/coverage_audit.py --check`
   - `pnpm test:run`
   - backend tests
   - `grace_lint` / marker lint

## Final decision

**NEEDS_REWORK.**

The sampled runtime TS files improved, but the rework still leaves malformed markers, invalid shell comment syntax, placeholder contracts, and a stale report. It is not safe to mark this PASS yet.
