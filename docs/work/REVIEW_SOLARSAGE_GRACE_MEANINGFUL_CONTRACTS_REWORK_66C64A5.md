# Review: Solar Sage meaningful GRACE contracts rework

**Review status:** NEEDS_REWORK
**Date:** 2026-06-12

## Reviewed refs

- Target repo: `basilivanov/solarsage-astro`
- Base: `f2a6a39`
- Reviewed head: `66c64a5`

## Review scope

The worker was asked to replace baseline boilerplate GRACE markers with meaningful file-specific contracts.

The intended acceptance criteria required:

1. no placeholder markers like `Library module`, `varies`, `TBD`, or generic contract content in in-scope files;
2. meaningful file-specific purpose/inputs/outputs/side_effects/emitted_logs/invariants;
3. function contracts for public/exported/impure functions or documented skip reasons;
4. runtime behavior unchanged;
5. `coverage_audit.py --check` and `pnpm test:run` green or failures proven pre-existing.

## Positive findings

Some pre-existing partially marked files remain meaningful. Example: `apps/api/app/api/day.py` still has a real route-level module contract, real inputs/outputs, route block, and function contract around `get_day`.

## Blocking findings

### 1. Many contracts are still not meaningful

Example: `lib/date.ts` is a runtime date utility file, but the generated header says:

- `ROLE: Tests — date.ts`
- `SLICE: SLICE-UNMAPPED`
- `purpose: Tests for date.ts behavior`
- `inputs: Component props / hook params`
- `outputs: TSX render / values`
- `side_effects: n/a (tests)`

This is factually wrong for a pure runtime date utility. It should describe date serialization/parsing/formatting helpers, local Date semantics, Russian month labels, week-range formatting, and `n/a (pure)` side effects/logs.

### 2. Marker structure is broken in multiple files

Example line pattern:

```ts
// #########################################// START_MODULE_CONTRACT
```

That is not a clean standalone `START_MODULE_CONTRACT` marker. It appears in `lib/date.ts`, `components/app-shell.tsx`, and `__tests__/lib/date.test.ts` samples.

This likely means the linter/audit will not reliably pair module contracts, and it makes the file unreadable to humans and agents.

Required marker shape must be standalone:

```ts
// ############################################################################
// AI_HEADER: ...
// ...
// ############################################################################

// START_MODULE_CONTRACT
...
// END_MODULE_CONTRACT
```

### 3. Frontend contracts are still generic placeholders

Example: `components/app-shell.tsx` says:

- `ROLE: UI component`
- `purpose: Module: app-shell.tsx`
- `inputs: Function args`
- `outputs: Return values`
- `invariants: n/a`

But the file actually owns app shell layout, children rendering, onboarding-aware navigation shell, `TabBar`, and logs render/debug state. That must be explicit.

### 4. Function contracts are still missing for exported runtime functions/components

Examples:

- `lib/date.ts` exports multiple public date helpers (`toDateParam`, `fromDateParam`, `formatDayMonth`, `formatLong`, `mondayFirstIndex`, `startOfWeek`, `formatWeekRange`) without function contracts.
- `components/app-shell.tsx` exports `AppShell` without a function/component contract.

The worker report itself admits: “Function contracts still need manual review for exported functions”. That violates the acceptance criteria rather than being a post-pass nicety.

### 5. Tests are red, not accepted

The report says `pnpm test:run` produced `725 passed, 2 failed, 1 skipped` and claims the two failures are pre-existing. But the previous user-provided baseline had tests green (`756 passed`), and the report does not prove the failures are pre-existing with a before/after run.

A red test gate is a blocker until proven unrelated.

### 6. Final SHA in report is stale/wrong

The report says final SHA is `9049638`, while the user pushed `66c64a5`. The reviewed diff shows additional commits after `9049638`, including backend/service changes and a large `scripts/grace_lint.py` change.

The report must reflect the actual final SHA under review.

### 7. Scope/report mismatch

The user reported “46 files”, but compare from `f2a6a39` to `66c64a5` shows far more files changed. The report also claims `~250` files changed. This inconsistency makes the evidence unreliable.

## Required rework

### A. Fix structural marker breakage first

Find and fix all occurrences of malformed marker joins such as:

```text
#########################################// START_MODULE_CONTRACT
#########################################// START_MODULE_MAP
END_MODULE_CONTRACTexport
```

Markers must be standalone lines.

### B. Replace wrong generated semantics

At minimum, scan all files for wrong generic/generated phrases:

- `ROLE: Tests —` in non-test files
- `purpose: Tests for` in non-test files
- `inputs: Function args`
- `outputs: Return values`
- `inputs: Component props / hook params` in non-component utility files
- `outputs: TSX render / values` in non-TSX utility files
- `invariants: n/a`
- `purpose: Module:`
- `SLICE: SLICE-UNMAPPED` where knowledge graph clearly maps the file

### C. Add meaningful function contracts

Do not punt function contracts to “manual review”. For this task, they are required for public/exported/impure functions.

At minimum fix:

- `lib/date.ts`
- `components/app-shell.tsx`
- all files where exported functions/components/hooks are present and currently lack `START_FUNCTION_CONTRACT`.

### D. Re-run and prove gates

Required:

```bash
python3 scripts/grace/coverage_audit.py --check
pnpm test:run
```

If tests fail, include a before/after proof that they failed before this commit. Otherwise fix them.

### E. Update report

Report must include actual final SHA `66c64a5` or the new rework SHA, exact file counts, exact gates, exact remaining placeholders, and exact skipped helpers.

## Suggested minimal strategy

Do not try another blind full-repo generator pass.

Instead:

1. Run a targeted scanner for malformed markers and wrong generic phrases.
2. Fix structural marker breakage globally.
3. Fix top-priority runtime files first: `lib/`, `components/`, `app/`, `apps/api/app/`.
4. Fix tests separately with meaningful “behavior proven” contracts.
5. Add function contracts to exported public functions in utility/runtime files.
6. Run gates and regenerate report.

## Final decision

**NEEDS_REWORK.**

The pass removed some literal placeholders, but it replaced many with new generic or wrong boilerplate and introduced malformed marker lines. This does not meet the “meaningful contracts” acceptance standard.
