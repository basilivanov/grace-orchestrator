# Review: Solar Sage meaningful GRACE contracts rework

**Review status:** NEEDS_REWORK
**Date:** 2026-06-12

## Reviewed refs

- Target repo: `basilivanov/solarsage-astro`
- Previous reviewed head: `66c64a5`
- Reviewed head: `336350d`

## Summary

Rework fixed part of the previously reported problems, but the packet is still not acceptable.

The most serious issue is that shell scripts now contain `//` comments, which are not valid shell comments and can break runtime script execution.

## Positive findings

- `lib/date.ts` now has a meaningful role and purpose for date utilities instead of being mislabeled as tests.
- `components/app-shell.tsx` now has a meaningful module contract for app shell layout, TabBar, render output, dependencies, and logging.
- The previous joined-marker issue is fixed in sampled TS files such as `lib/date.ts`, `components/app-shell.tsx`, and `__tests__/lib/date.test.ts`.

## Blocking findings

### 1. Shell scripts contain invalid `//` comments

Example: `scripts/alert.sh` contains TypeScript-style `//` marker comments inside a bash script. This is not a comment in bash. It is parsed as command/path text and can break execution.

Required fix:

- use `#` comments in all `.sh` files;
- fix all malformed shell marker joins;
- run at least `bash -n` for touched shell scripts.

### 2. Placeholder content still remains

Example: `lib/env/production-guard.mjs` still contains placeholder contract text:

- `purpose: Library module — lib/env/production-guard.mjs`
- `inputs: varies`
- `outputs: varies`
- `side_effects: varies`
- `invariants: n/a`

This directly violates the acceptance criterion that placeholder content must be removed from in-scope files.

Required fix:

- scan all in-scope files for `Library module`, `varies`, `TBD`, `purpose: Module`, `invariants: n/a`;
- replace with file-specific contracts or document a real skip reason.

### 3. Report is stale and does not represent `336350d`

`REPORT_SOLARSAGE_GRACE_MEANINGFUL_CONTRACTS_REWORK.md` still says final SHA `9049638` and tests `725 passed, 2 failed, 1 skipped`.

The user reports `336350d` and `756 passed, 1 skipped`, but the required final report was not updated to prove that.

Required fix:

- update final SHA to the actual head;
- include exact gate outputs for `336350d`;
- include exact before/after placeholder counts;
- list remaining placeholders or state zero with the grep command used.

### 4. Function contracts are still not fully closed

`lib/date.ts` has exported functions but no `START_FUNCTION_CONTRACT` blocks for them. The previous report already admitted function contracts still needed manual review. This is still not resolved for at least the sampled utility file.

Required fix:

- either add function contracts to exported/public/impure functions;
- or document why specific tiny helpers are covered by a block/module contract.

## Required rework

1. Fix shell scripts to use `#` comments and valid standalone markers.
2. Run a repository-wide placeholder scan and remove remaining `Library module`, `varies`, and wrong generic text.
3. Fix `lib/env/production-guard.mjs` and any similar files.
4. Add or explicitly justify missing function contracts for exported utilities/components/hooks.
5. Update the final report to match `336350d` or the new head.
6. Run and report `coverage_audit.py --check`, `pnpm test:run`, and `bash -n` on touched shell scripts.

## Final decision

**NEEDS_REWORK.**

The semantic quality improved in some sampled files, but the current head still contains runtime-breaking shell comment syntax, unresolved placeholders, stale report evidence, and incomplete function-contract coverage.
