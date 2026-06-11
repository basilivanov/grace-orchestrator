# Worker handoff: Solar Sage meaningful GRACE contracts rework

**Status:** READY_FOR_WORKER
**Date:** 2026-06-12

## Goal

Improve the quality of GRACE canon markers after the full-repo baseline adoption.

Baseline adoption exists in Solar Sage `f2a6a39`, but many files still contain boilerplate contracts such as:

- `ROLE: Library module`
- `purpose: ... varies`
- `inputs: varies`
- `outputs: varies`
- `side_effects: varies`
- `emitted_logs: n/a` when the file actually logs or inherits logging context

This packet must replace those placeholders with meaningful, file-specific contracts.

## Target repo

- Repository: `basilivanov/solarsage-astro`
- Baseline: `f2a6a39`
- Suggested branch: `grace/meaningful-contracts-rework`

## Hard rule

Do not change runtime behavior.

Allowed changes are comments/contracts/GRACE markers only, plus final report.

Forbidden:

- logic changes
- UI copy changes
- API route changes
- payload/schema changes
- DB schema/migration changes
- generated contract edits
- dependency changes
- broad formatter churn

## Scope

All first-party files touched by `f2a6a39` that have low-value or placeholder GRACE markers.

Prioritize files that contain any of these placeholder patterns:

- `Library module`
- `varies`
- `TODO`
- `TBD`
- `n/a` used incorrectly
- `side_effects: varies`
- `inputs: varies`
- `outputs: varies`
- `purpose: varies`
- module/function contracts that only restate the filename
- block names that are generic and do not describe the code

Also inspect files that still lack meaningful `FUNCTION_CONTRACT` for exported/public/impure functions.

## Required workflow

### W0 — detect low-quality markers

Run a scanner to list files containing placeholder contract text.

Minimum grep:

```bash
grep -RIn \
  -e 'Library module' \
  -e 'varies' \
  -e 'TODO' \
  -e 'TBD' \
  -e 'purpose: .*file' \
  -e 'side_effects: varies' \
  -e 'inputs: varies' \
  -e 'outputs: varies' \
  app components hooks lib apps packages scripts __tests__ grace 2>/dev/null
```

Create a before inventory in the final report.

### W1 — frontend meaningful pass

Rewrite marker content in:

- `app/`
- `components/`
- `hooks/`
- `lib/`
- `__tests__/`

Make each contract answer:

- what the file actually owns;
- what data it consumes;
- what it returns/renders/exports;
- what side effects it has;
- what logs it emits or inherits;
- what invariants future agents must preserve.

### W2 — backend meaningful pass

Rewrite marker content in:

- `apps/api/app/api/`
- `apps/api/app/services/`
- `apps/api/app/core/`
- `apps/api/app/db/`
- `apps/api/app/schemas/`
- `apps/api/tests/`

Contracts must distinguish:

- routers vs services vs schemas vs DB/session/core helpers;
- pure schema/type files vs impure DB/network/logging code;
- actual emitted logs and inherited logging context;
- error behavior and state changes.

### W3 — sidecar/contracts/scripts/GRACE adapter

Rewrite marker content in:

- `apps/solarsage/`
- `packages/contracts/` non-generated files
- `scripts/`
- `grace/orchestrator/`
- live `grace/*` docs/configs

Do not edit generated files or historical archive files.

### W4 — final audit and report

Run final checks and create report.

## Meaningful contract standard

A contract is acceptable only if a future architect can understand file behavior without reading the entire implementation first.

Bad:

```text
purpose: Library module
inputs: varies
outputs: varies
side_effects: varies
```

Good:

```text
purpose: Normalize date keys used by Today and Calendar screens.
inputs: Date/string values from route params and API payloads.
outputs: ISO day keys and display labels.
side_effects: n/a (pure)
emitted_logs: n/a (pure)
invariants: Do not shift dates across timezone boundaries when converting display labels.
```

## Function contract standard

For each public/exported/impure function or component, the function contract must say:

- real purpose;
- real inputs;
- real return/rendered output;
- side effects;
- emitted logs or inherited logging;
- error behavior;
- key invariants.

Do not write `varies` or generic text.

Tiny pure helpers may be covered by a block contract, but skipped helpers must be listed in the report.

## Logging standard

Current v2 logging spine is accepted:

- frontend: `lib/log/index.ts`, `lib/log/shipper.ts`
- backend: `apps/api/app/core/logging.py`
- backend intake: `apps/api/app/api/_log.py`, `apps/api/app/services/log_intake.py`

Use:

- `emitted_logs: n/a (pure)` only for actually pure code;
- `emitted_logs: inherited from caller` when a helper has no direct log call but runs under caller log context;
- exact event names when the file/function calls logging APIs.

If `coverage_audit.py` still undercounts v2 logging, report it separately. Do not rewrite logging architecture here.

## Required gates

Run:

```bash
python3 scripts/grace/coverage_audit.py --check
pnpm test:run
```

If practical:

```bash
pnpm guardrails:docs
pnpm guardrails:orchestrator
pnpm guardrails:frontend
pnpm typecheck
```

## Required final report

Create in Solar Sage:

`docs/work/REPORT_SOLARSAGE_GRACE_MEANINGFUL_CONTRACTS_REWORK.md`

Report must include:

- base SHA and final SHA
- files inspected
- files changed
- placeholder count before/after
- list of remaining placeholder markers, if any
- meaningful contracts added/fixed count
- function contracts added/fixed count
- emitted_logs declarations corrected
- files skipped and why
- gates run and results
- confirmation that only comments/contracts/GRACE markers changed

## Acceptance criteria

PASS only if:

1. No in-scope file still contains `Library module`, `varies`, `TBD`, or placeholder contract content.
2. `purpose`, `inputs`, `outputs`, `side_effects`, `emitted_logs`, and `invariants` are file-specific where present.
3. Public/exported/impure functions have meaningful function contracts or documented skip reason.
4. Logging declarations match actual logging behavior or inherited context.
5. Generated/vendor/archive files are not edited.
6. Runtime behavior is unchanged.
7. `coverage_audit.py --check` passes.
8. `pnpm test:run` passes or failures are proven pre-existing.
9. Final report exists.

## Suggested commit message

`docs: replace boilerplate GRACE markers with meaningful contracts`
