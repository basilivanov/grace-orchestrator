# Review: Solar Sage Pilot 006 rework 3

**Review status:** NEEDS_REWORK_4
**Date:** 2026-06-11

## Reviewed refs

- `grace-orchestrator`: `a4ffa09`
- `solarsage-astro`: `4372503`

## Verdict

The two remaining technical linter blockers are fixed, but the admin UI/service artifact blocker is still not clean in the final orchestrator range.

Final status: **NEEDS_REWORK_4**.

## Checks

### 1. BLOCK without name now emits violation

**Status:** OK

Frontend linter:

- unnamed `BLOCK` is converted to `_unnamed_`
- `check_pairing()` emits `GRC004`
- message tells the user to use `// START_BLOCK: NAME`

Backend linter:

- unnamed `BLOCK` is converted to `_unnamed_`
- `check_pairing()` emits `GRC004`
- message tells the user to use `# START_BLOCK: NAME`

This matches the canon:

- `MODULE_CONTRACT` and `MODULE_MAP`: no-id canonical
- `BLOCK`: named marker required

### 2. Real canon.yaml glob test is now meaningful

**Status:** OK

The orchestrator test now uses:

- exclude pattern: `generated/**/*.ts`
- excluded file: `generated/api/types.ts`
- non-excluded file: `src/handlers/controller.ts`

This path is not covered by hardcoded exclusions, so the test now proves config-driven glob behavior.

### 3. Admin artifacts still appear in final orchestrator diff

**Status:** NEEDS_REWORK

`grace-orchestrator` compare from the intended clean baseline `e6f6947` to `a4ffa09` still includes:

- `src/grace_control/services/admin_aggregation_service.py`
- `src/grace_control/ui/static/admin.html`

This contradicts the claim that the admin artifacts were removed from the final policy scope.

The range `4a4d348..a4ffa09` also contains large admin UI/service changes. These are not part of the stated Rework 3 scope, which was only:

- unnamed BLOCK violation
- real glob test

Required fix:

- either revert/split the admin UI/service files out of this Pilot 006 policy line
- or provide a separate report proving these admin changes are intentional and already accepted as another feature

## Positive findings

- Solar Sage rework is narrow and clean: only `scripts/grace_front_lint.py` and `scripts/grace_lint.py` changed.
- BLOCK naming rule is now enforced through GRC004.
- The glob test no longer relies on hardcoded excluded paths.

## Final decision

Do not mark Pilot 006 as clean PASS yet.

Recommended next action: remove or formally split the admin UI/service changes, then re-review only final file list and acceptance report.
