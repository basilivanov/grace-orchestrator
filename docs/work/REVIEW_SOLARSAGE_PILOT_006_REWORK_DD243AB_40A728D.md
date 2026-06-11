# Review: Solar Sage Pilot 006 rework — dd243ab / 40a728d

**Review status:** NEEDS_REWORK
**Date:** 2026-06-11

## Reviewed refs

- `grace-orchestrator`: `dd243ab296fc582f509aadbe3f9ee44d0eea03fb`
- `solarsage-astro`: `40a728d`

## Scope

This review checks the claimed fixes for the 6 Pilot 006 blockers:

1. no-id `MODULE_CONTRACT` / `MODULE_MAP` marker grammar
2. `grace/canon.yaml` exclude handling
3. strict mode empty lint-file guard
4. false linter origins when no command is added
5. frontend linter exclusions in both discovery and explicit path expansion
6. unrelated `admin.html` changes removed from the report/policy commit

## Verdict

**NEEDS_REWORK.**

Several fixes are real, but two important problems remain:

1. `BLOCK` marker names are not enforced; the regex made ids optional for every marker kind.
2. `grace/canon.yaml` excludes are loaded, but treated as raw prefixes after `rstrip('/') + '/'`; glob-style excludes are not implemented correctly.
3. `grace-orchestrator` diff still includes unrelated UI/admin changes between `e1d4c78` and `dd243ab`.

## Findings by blocker

### 1. Marker grammar — partially fixed, but BLOCK names are not enforced

**Status:** NEEDS_REWORK

Good:

- `MODULE_CONTRACT` and `MODULE_MAP` no longer require `: ID`, which matches the project canon.

Problem:

- the frontend regex makes `id` optional for all marker kinds, including `BLOCK`:

```python
r"(?://|/\*|\*)\s*(?P<edge>START|END)_(?P<kind>MODULE_CONTRACT|MODULE_MAP|BLOCK)"
r"(?:\s*:\s*(?P<id>[^\s\*\/]+))?"
```

- the backend regex also makes `id` optional for all marker kinds, including `FUNCTION_CONTRACT` and `BLOCK`:

```python
r"^\s*#\s*(?P<edge>START|END)_(?P<kind>MODULE_CONTRACT|MODULE_MAP|"
r"FUNCTION_CONTRACT|BLOCK)(?:\s*:\s*(?P<id>\S+))?\s*$"
```

- both linters then default `ident` to `""` and pairing succeeds when both START and END have empty ids.

This means these would likely pass pairing even though they should not be canonical valid blocks:

```ts
// START_BLOCK
// END_BLOCK
```

```py
# START_BLOCK
# END_BLOCK
```

Required fix:

- `MODULE_CONTRACT` / `MODULE_MAP`: id optional / no-id canonical.
- `BLOCK`: name required, canonical format `START_BLOCK: NAME` / `END_BLOCK: NAME`.
- `FUNCTION_CONTRACT`: keep whatever the project canon says, but do not accidentally relax it without tests.
- Add explicit negative tests: unnamed `START_BLOCK` / `END_BLOCK` must fail.

### 2. `canon.yaml` exclude handling — partially fixed, but glob semantics are wrong

**Status:** NEEDS_REWORK

Good:

- `gate_resolver.py` now loads `grace/canon.yaml` through `_load_canon_config()`.
- `resolve_default_t0()` passes config-derived exclusions into `_path_is_excluded()`.

Problem:

The implementation converts every `exclude` string into a prefix using:

```python
p.rstrip("/") + "/"
```

This does not implement YAML glob semantics.

Examples:

- `components/ui/**/*.tsx` becomes `components/ui/**/*.tsx/`, which will never match a normal file path by `startswith()`.
- `package-lock.json` becomes `package-lock.json/`, which will not match the file `package-lock.json`.
- custom globs like `generated/**/*.ts` will not work.

The hardcoded exclusions still catch some current paths, but the config is misleading: it looks like glob config while behaving like a narrow prefix list.

Required fix:

- Either implement glob matching with `fnmatch` / `PurePath.match`, or document that `exclude` supports prefix-only values and change `grace/canon.yaml` examples accordingly.
- Add tests proving config exclude works for both directory prefixes and file/glob patterns.

### 3. Strict mode empty-file guard — fixed

**Status:** OK

`resolve_default_t0()` now only adds backend/frontend GRACE lint commands when `lint_py` / `lint_fe` are non-empty.

### 4. False origins when all files are excluded — fixed

**Status:** OK

Origins are now appended inside the same branch that requires non-empty `lint_py` / `lint_fe`. The added test `test_t0_changed_files_all_excluded_no_commands` checks that excluded-only changes produce no GRACE lint commands and no GRACE origins.

### 5. Frontend linter discovery exclusions — fixed for hardcoded exclusions

**Status:** MOSTLY_OK

Good:

- `_path_excluded()` is centralized in `scripts/grace_front_lint.py`.
- `discover_frontend_files()` calls `_path_excluded()`.
- `expand_paths()` also calls `_path_excluded()`.

Remaining limitation:

- this is only hardcoded exclusions inside the frontend linter script; it does not read `grace/canon.yaml` exclusions.

This is acceptable only if the design says frontend linter local exclusions are hardcoded and orchestrator policy owns config-based exclusions.

### 6. Unrelated `admin.html` changes — not fixed in the reviewed range

**Status:** NEEDS_REWORK / VERIFY_BRANCH_HISTORY

Comparing `grace-orchestrator` from `e1d4c78` to `dd243ab` still shows changes in:

- `src/grace_control/ui/static/admin.html`
- `src/grace_control/services/admin_aggregation_service.py`

These look unrelated to GRACE-canon linter policy unless they belong to another approved UI/admin feature.

Required fix:

- If intentional: split them into a separate feature/report.
- If accidental: revert them from the policy/rework branch.
- If already fixed locally but not in pushed `dd243ab`: push the corrected branch and re-review.

## Positive findings

- Linter mode structure remains correct: `strict`, `changed-files`, `disabled`.
- Empty-list guard and false-origin guard are fixed in `gate_resolver.py`.
- Frontend linter discovery/expansion now share hardcoded exclusion logic.
- Solar Sage rework commit is small and focused: only `scripts/grace_front_lint.py` and `scripts/grace_lint.py` changed from `2989f12` to `40a728d`.

## Required next rework

1. Enforce named `BLOCK` markers while keeping no-id `MODULE_CONTRACT` / `MODULE_MAP` canonical.
2. Decide and implement real `canon.yaml` exclude semantics: glob or prefix-only.
3. Add tests for unnamed block rejection.
4. Add tests for config excludes with realistic entries from `grace/canon.yaml`.
5. Remove/split unrelated admin UI/service changes from this policy review scope.

## Final decision

Do **not** mark Pilot 006 rework as clean PASS yet.

Recommended status:

**NEEDS_REWORK_2**
