# Review: Solar Sage GRACE slice coverage audit rework 2

**Review status:** PASS
**Date:** 2026-06-11

## Reviewed refs

- Solar Sage base: `cfdf93d`
- Solar Sage reviewed head: `9dedaf9`

## Scope reviewed

Diff `cfdf93d..9dedaf9` changes only:

- `scripts/grace/coverage_audit.py`
- `docs/work/REPORT_SOLARSAGE_GRACE_SLICE_COVERAGE_AUDIT.md`
- `docs/work/solarsage_grace_slice_coverage.json`

No runtime product source was changed.

## Findings

### PASS: exact paths are now before broad prefixes

`SLICE_MAP` now puts exact files before directory prefixes, including:

- `components/today/tab-bar.tsx` -> `SLICE-SHELL-NAVIGATION`
- `components/app-shell.tsx` -> `SLICE-SHELL-NAVIGATION`
- `lib/today.ts` -> `SLICE-TODAY-CALENDAR`
- frontend API facade exact files before broader `lib/`

This fixes the prior TabBar classifier bug.

### PASS: sentinel checks added

`--check` now validates 9 sentinel mappings, including:

- `components/today/tab-bar.tsx` -> `SLICE-SHELL-NAVIGATION`
- `apps/api/app/services/today_service.py` -> `SLICE-BACKEND-SERVICES`
- `apps/api/app/api/day.py` -> `SLICE-BACKEND-API-ROUTERS`
- `apps/api/app/db/models.py` -> `SLICE-DB-MODELS-MIGRATIONS`
- `lib/grace/log.ts` -> `SLICE-LOGGING-SPINE`
- `__tests__/components/TabBar.test.tsx` -> `SLICE-TESTS`
- `packages/contracts/today.ts` -> `SLICE-CONTRACTS`
- `scripts/grace/coverage_audit.py` -> `SLICE-GUARDRAILS-TOOLING`
- `grace/orchestrator/cli.py` -> `SLICE-ORCHESTRATOR-ADAPTER`

### PASS: regenerated report reflects corrected classification

The report now shows:

- `SLICE-SHELL-NAVIGATION`: 2 files, 1 full, 1 none, 50.0% coverage
- `SLICE-TODAY-CALENDAR`: 12 files, 1 full, 11 none, 8.3% coverage

This indicates `tab-bar.tsx` moved out of Today/Calendar into Shell/Navigation as intended.

### Non-blocking note

`--check` still reads the already-written JSON twice rather than running two independent scans in memory. This is not a blocker for this audit now that timestamp entropy is removed and sentinel checks are present, but a future hardening packet should make `--check` run `build_output()` twice and compare both objects.

## Final decision

**PASS.**

The slice coverage audit is now reliable enough to drive the next GRACE adoption waves.

## Recommended next packets

Use this audit as input for:

1. `W-GRACE-SLICE-P0-TODAY-CALENDAR`
2. `W-GRACE-SLICE-P0-BACKEND-API-SERVICES`
3. `W-GRACE-SLICE-P0-CONTRACTS`
4. `W-GRACE-SLICE-P1-LOGGING-SPINE`

Do not mass-apply all markers at once. Slice-by-slice adoption is safer.
