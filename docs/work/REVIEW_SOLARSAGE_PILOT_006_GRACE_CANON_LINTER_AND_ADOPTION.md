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

## Corrected GRACE marker canon decision

Canonical source markers distinguish **module-level singleton markers** from **named inner blocks**.

### Module-level singleton markers: no id

A file has one module contract and one module map, so these markers do **not** need ids:

```python
# START_MODULE_CONTRACT
# END_MODULE_CONTRACT
# START_MODULE_MAP
# END_MODULE_MAP
```

```ts
// START_MODULE_CONTRACT
// END_MODULE_CONTRACT
// START_MODULE_MAP
// END_MODULE_MAP
```

### Inner START_BLOCK / END_BLOCK markers: named block required

A file may contain multiple logical blocks, so block markers need a stable block name.

Preferred Python style:

```python
# START_BLOCK: DISCOVERY
# END_BLOCK: DISCOVERY
```

Preferred TypeScript/JavaScript style:

```ts
// START_BLOCK: MOCKS
// END_BLOCK: MOCKS
```

The linter may also accept existing legacy variants such as `START_BLOCK_MOCKS`, but generated code should use the canonical `START_BLOCK: NAME` form.

The previous review incorrectly flattened this into “no-id module/map/block markers”. Correct rule:

- `MODULE_CONTRACT` and `MODULE_MAP`: no id.
- `BLOCK`: named id is required.

## Verdict

**NEEDS_REWORK** before this can be accepted as a stable GRACE-canon linter policy.

## Blockers

### 1. Frontend linter grammar is stale relative to the accepted marker canon

`solarsage-astro/scripts/grace_front_lint.py` currently parses module/block markers with this grammar:

```python
r"(?://|/\*|\*)\s*(?P<edge>START|END)_(?P<kind>MODULE_CONTRACT|MODULE_MAP|BLOCK)\s*:\s*(?P<id>[^\s\*\/]+)"
```

That requires a colon and marker id for every marker kind, including `MODULE_CONTRACT` and `MODULE_MAP`.

But the canonical project style is:

```ts
// START_MODULE_CONTRACT
// END_MODULE_CONTRACT
// START_MODULE_MAP
// END_MODULE_MAP
// START_BLOCK: COMPONENT
// END_BLOCK: COMPONENT
```

This means `parse_markers()` may not recognize correctly canonicalized Solar Sage files, and `check_pairing()` may still report missing `MODULE_CONTRACT` / `MODULE_MAP` markers.

Affected examples:

- `components/today/tab-bar.tsx`
- `__tests__/components/TabBar.test.tsx`

Required fix:

Update backend and frontend GRACE linters to support:

- no-id `MODULE_CONTRACT` markers as canonical
- no-id `MODULE_MAP` markers as canonical
- named `BLOCK` markers as canonical
- backward compatibility for legacy `MODULE_CONTRACT: ID`, `MODULE_MAP: ID`, and `START_BLOCK_NAME` forms if already present

Suggested parser behavior:

- Accept `# START_MODULE_CONTRACT`
- Accept `# START_MODULE_CONTRACT: OPTIONAL_ID` for backward compatibility
- Accept `// START_MODULE_CONTRACT`
- Accept `// START_MODULE_CONTRACT: OPTIONAL_ID` for backward compatibility
- Accept `# START_BLOCK: NAME`
- Accept `// START_BLOCK: NAME`
- Optionally accept legacy `# START_BLOCK_NAME` / `// START_BLOCK_NAME`
- Pair module markers by kind because they are singleton per file
- Pair block markers by name/stack order

Add tests for spaced/no-id module markers, named block markers, and legacy/id forms.

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
- Module/map no-id markers are the correct project canon and should remain the generated style.
- Named `START_BLOCK: NAME` / `END_BLOCK: NAME` markers are the correct inner-block canon.
- Staged adoption plan is correct: policy first, then small owned frontend slice, then backend/API slice.

## Required follow-up task

Create a rework task for Pilot 006 instead of starting mass migration.

Suggested rework scope:

1. Update backend/frontend linter marker parser to accept no-id module/map canonical markers.
2. Require/accept named block markers for `START_BLOCK` / `END_BLOCK`.
3. Keep backward compatibility for legacy `: ID` markers and legacy block-name variants.
4. Make `grace/canon.yaml` semantics honest: either implement include/exclude/adopt_first or document only `gate_mode` is active.
5. Avoid empty linter invocations.
6. Avoid false origins when all files are excluded.
7. Apply exclusions consistently in frontend linter discovery and explicit path expansion.
8. Split/revert unrelated `admin.html` changes from the report commit.
9. Add tests for the above cases.

## Final review decision

Do not treat Pilot 006 as stable PASS yet.

Recommended status:

**PASS_WITH_REWORK_REQUIRED** or **NEEDS_REWORK**.

The architecture direction is accepted, but the implementation needs one cleanup/rework pass before becoming the canonical policy baseline.
