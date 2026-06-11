# Review: Solar Sage Pilot 006 — GRACE canon linter policy and adoption

**Review status:** NEEDS_REWORK
**Date:** 2026-06-11
**Reviewed commits:**

- `grace-orchestrator`: `e1d4c78d63018d3609b8bc294d6d22f508929263`
- policy implementation under review: `4497f7559a26fa5387f37cb489e6144bb2382650`
- `solarsage-astro`: `2989f12`

## Summary

Pilot 006 moves in the right direction: it introduces explicit linter modes, target-repo opt-in through `grace/canon.yaml`, path exclusions, changed-files gate behavior, and tests around gate resolution.

However, the current result should not be treated as fully PASS yet. The implementation has several correctness gaps that will make the policy unreliable in real runs.

## Verdict

**NEEDS_REWORK** before this can be accepted as a stable GRACE-canon linter policy.

## Blockers

### 1. Adopted Solar Sage TS/TSX files do not match the current frontend linter marker grammar

`solarsage-astro/scripts/grace_front_lint.py` parses module/block markers with this grammar:

```python
r"(?://|/\*|\*)\s*(?P<edge>START|END)_(?P<kind>MODULE_CONTRACT|MODULE_MAP|BLOCK)\s*:\s*(?P<id>[^\s\*\/]+)"
```

That requires a colon and marker id, for example:

```ts
// START_MODULE_CONTRACT: TAB_BAR
// END_MODULE_CONTRACT: TAB_BAR
```

But the newly adopted files use markers without ids:

```ts
// START_MODULE_CONTRACT
// END_MODULE_CONTRACT
// START_MODULE_MAP
// END_MODULE_MAP
```

This means `parse_markers()` will not recognize those module markers, and `check_pairing()` will still report missing `MODULE_CONTRACT` / `MODULE_MAP` markers.

Affected examples:

- `components/today/tab-bar.tsx`
- `__tests__/components/TabBar.test.tsx`

Required fix:

Either update the files to canonical marker ids, or deliberately relax the linter grammar to allow no-id module markers. Prefer canonical ids for machine-friendly pairing.

### 2. `grace/canon.yaml` include/exclude/adopt_first are mostly inert in the orchestrator policy

`resolve_linter_mode()` reads only `gate_mode` from `grace/canon.yaml`. The path exclusions used by `resolve_default_t0()` are hard-coded in `gate_resolver.py`.

Current behavior:

- `gate_mode` is read.
- `include` is not applied.
- `exclude` is not applied from config.
- `adopt_first` is not applied.

This makes `grace/canon.yaml` look more powerful than it is. The report presents it as policy config, but in practice only `gate_mode` affects the orchestrator.

Required fix:

Implement config-backed include/exclude/adopt_first behavior or explicitly document that only `gate_mode` is currently active. If `adopt_first` is intended to lint files even without explicit coder changes, add tests for that behavior.

### 3. `strict` mode can invoke GRACE linters with an empty file list

In `resolve_default_t0()`, strict mode appends:

```python
["python3", "scripts/grace_lint.py"] + lint_py
["python3", "scripts/grace_front_lint.py"] + lint_fe
```

without checking whether `lint_py` / `lint_fe` are non-empty.

Depending on linter CLI behavior, this can accidentally become a full-repo scan or a misleading empty command when only one area changed.

Required fix:

Only append backend/frontend linter commands when the corresponding filtered file list is non-empty, unless the intended behavior is explicitly full-repo strict scan. If full-repo strict scan is intended, name it and test it directly.

### 4. Changed-files mode can record linter origins even when no linter command is added

In changed-files mode, if all files are excluded, no per-file command is added, but `origins.append("auto:t0:frontend_grace_lint")` / backend equivalent can still happen after the loop.

Required fix:

Append the origin only if at least one command was added for that origin. Add a test where all changed files are excluded.

## Major risks

### 5. Full discover path in `grace_front_lint.py` does not apply the new exclusions

`expand_paths()` excludes `node_modules`, `.next`, `.venv`, `alembic`, `migrations`, and `components/ui`, but `discover_frontend_files()` still returns all files matched by `grace/frontend.paths` without applying those exclusions.

This means explicit path mode may be cleaner, but full frontend audit mode can still include excluded/generated/vendor paths depending on `grace/frontend.paths`.

Required fix:

Centralize exclusion logic and apply it in both `discover_frontend_files()` and `expand_paths()`.

### 6. Report commit includes an unrelated UI change

Commit `e1d4c78` is titled as a docs/report commit, but it also modifies `src/grace_control/ui/static/admin.html` heavily.

This is outside the stated report-only scope and should be separated into its own UI commit/report, or reverted if accidental.

Required fix:

Split report-only docs commit from unrelated admin UI changes.

## Positive findings

- The direction is correct: strict / changed-files / disabled is the right high-level model.
- Alembic/migrations exclusion is the right default.
- `components/ui/` as vendor/shadcn exclusion is reasonable unless explicitly owned.
- Comment marker whitespace tolerance is the right parser behavior; canonical generated style should be spaced.
- Staged adoption plan is correct: policy first, then small owned frontend slice, then backend/API slice.

## Required follow-up task

Create a rework task for Pilot 006 instead of starting mass migration.

Suggested rework scope:

1. Fix frontend marker grammar mismatch.
2. Make `grace/canon.yaml` semantics honest: either implement include/exclude/adopt_first or document only `gate_mode` is active.
3. Avoid empty linter invocations.
4. Avoid false origins when all files are excluded.
5. Apply exclusions consistently in frontend linter discovery and explicit path expansion.
6. Split/revert unrelated `admin.html` changes from the report commit.
7. Add tests for the above cases.

## Final review decision

Do not treat Pilot 006 as stable PASS yet.

Recommended status:

**PASS_WITH_REWORK_REQUIRED** or **NEEDS_REWORK**.

The architecture direction is accepted, but the implementation needs one cleanup/rework pass before becoming the canonical policy baseline.
