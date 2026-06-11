# Review: Solar Sage GRACE slice coverage audit rework

**Review status:** NEEDS_REWORK_2
**Date:** 2026-06-11

## Reviewed refs

- Solar Sage base: `66ce0e8`
- Solar Sage reviewed head: `cfdf93d`

## Scope reviewed

Diff `66ce0e8..cfdf93d` changes only:

- `scripts/grace/coverage_audit.py`
- `docs/work/REPORT_SOLARSAGE_GRACE_SLICE_COVERAGE_AUDIT.md`
- `docs/work/solarsage_grace_slice_coverage.json`

No runtime product source was changed.

## Fixed from previous review

### Fixed: JSON timestamp removed

The JSON no longer includes `generated_at`, so the old obvious nondeterministic timestamp problem is gone.

### Fixed: report generated from same data object

The script now writes JSON and markdown from the same `output` object via `_generate_markdown(output)`. The report summary and JSON summary now agree.

### Fixed: required per-file fields added

The JSON now includes:

- `module_id`
- `pairing_status`
- `logging_declared_in_contract`
- `adoption_priority`
- `notes`

### Improved: backend classifier prefixes

The backend path prefixes now use actual repo paths such as:

- `apps/api/app/services/`
- `apps/api/app/api/`
- `apps/api/app/schemas/`
- `apps/api/app/core/`
- `apps/api/app/db/`

This fixes the previous broad `apps/api/app/` issue for most backend files.

## Remaining blocker

### 1. Frontend slice classifier still has a path-order bug

`components/today/` appears before `components/today/tab-bar.tsx` in `SLICE_MAP`.

Because the classifier returns the first matching prefix, `components/today/tab-bar.tsx` will still be classified as `SLICE-TODAY-CALENDAR` instead of `SLICE-SHELL-NAVIGATION`.

This contradicts the declared module family in `grace/README.md`, where TabBar is part of Shell/Navigation.

Required fix:

- Move `components/today/tab-bar.tsx` before `components/today/`, or
- explicitly document that TabBar belongs to Today/Calendar and update README/module-family docs accordingly.

Preferred fix: classify `components/today/tab-bar.tsx` as `SLICE-SHELL-NAVIGATION`.

### 2. Sentinel assertions are still missing

Previous review asked for sentinel classification checks. The script does not contain assertions/tests for sentinel files.

Required minimal sentinel checks:

- `components/today/tab-bar.tsx` -> `SLICE-SHELL-NAVIGATION`
- `apps/api/app/services/today_service.py` -> `SLICE-BACKEND-SERVICES`
- `apps/api/app/api/day.py` -> `SLICE-BACKEND-API-ROUTERS`
- `apps/api/app/db/models.py` -> `SLICE-DB-MODELS-MIGRATIONS`
- `lib/grace/log.ts` -> `SLICE-LOGGING-SPINE`

These can run under `--check` and fail fast.

## Non-blocking note

`--check` currently reads the already-written JSON twice and compares hashes. That checks hash stability, not scanner determinism. Since the timestamp has been removed and file ordering appears stable, this is no longer a hard blocker, but `--check` should eventually run the collector twice in memory and compare both objects.

## Final decision

**NEEDS_REWORK_2.**

The audit is now close, but the remaining TabBar classifier bug means slice-level adoption planning is still slightly wrong for Shell/Navigation. Fix classifier ordering and add sentinel checks, then regenerate JSON/report.

## Minimal rework

1. Move exact/specific frontend paths before broad prefixes.
2. Add sentinel classification assertions under `--check`.
3. Re-run `python3 scripts/grace/coverage_audit.py --check`.
4. Commit regenerated JSON/report.
