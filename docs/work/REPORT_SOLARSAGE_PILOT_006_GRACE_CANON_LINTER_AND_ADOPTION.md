# Report: Solar Sage Pilot 006 — GRACE canon linter policy and adoption

**Status:** PASS
**Date:** 2026-06-11

## GRACE commit tested
- `4497f75`

## Solar Sage commit
- `2989f12`

## Business input
Adoption policy for GRACE linters: modes, opt-in config, exclusions, comment marker tolerance.

## Changes

### Orchestrator (grace-orchestrator)

**`src/grace_control/core/gate_resolver.py`**
- `resolve_linter_mode(worktree_path) → str` — returns `strict`, `changed-files`, or `disabled` based on repo type and `grace/canon.yaml`
- `_path_is_excluded(path) → bool` — detects generated/vendor/framework paths
- `resolve_default_t0()` updated to use linter mode:
  - `strict`: full GRACE lint on all scoped files (orchestrator)
  - `changed-files`: GRACE lint on each changed file individually (target repo opted in)
  - `disabled`: skip GRACE lint entirely (target repo without opt-in)

**Linter modes documented:**
- `strict` — orchestrator repo (detected via `.grace/state` or `src/grace_control/`)
- `changed-files` — target repo with `grace/canon.yaml` setting `gate_mode: changed-files`
- `disabled` — target repo without canon config

**Exclusions (both resolver and linter scripts):**
- `node_modules/`, `.next/`, `.venv/`, `__pycache__/`, `.git/`
- `alembic/`, `migrations/`
- `components/ui/` (shadcn/vendor)
- `*.min.js`, `*.min.css`

### Solar Sage (solarsage-astro)

**`grace/canon.yaml`** (new)
```yaml
gate_mode: changed-files
exclude:
  - node_modules/**, .next/**, .venv/**, __pycache__/**
  - alembic/**, migrations/**
  - components/ui/**/*.tsx, components/ui/**/*.ts
  - *.min.js, *.min.css
adopt_first:
  - components/today/
  - app/(grace)/today/
  - __tests__/components/
```

**`scripts/grace_front_lint.py`** — added exclusions for `__pycache__`, `.venv`, `alembic/`, `migrations/`, `components/ui/`

### Comment marker tolerance
Both `grace_lint.py` and `grace_front_lint.py` already accept optional whitespace after comment markers (regex `\s*` after `#` or `//`). Both `#START_BLOCK:` and `# START_BLOCK:` work. Canonical form is spaced: `# START_BLOCK: X`.

## Tests added/updated
- `test_resolve_linter_mode_orchestrator` — `.grace/state` → strict
- `test_resolve_linter_mode_target_disabled` — no canon.yaml → disabled
- `test_resolve_linter_mode_target_canon` — `grace/canon.yaml` with `gate_mode: changed-files`
- `test_resolve_linter_mode_target_canon_strict` — `grace/canon.yaml` with `gate_mode: strict`
- `test_path_is_excluded_dir` — node_modules, .venv, __pycache__
- `test_path_is_excluded_prefix` — alembic/, migrations/, components/ui/
- `test_path_is_not_excluded` — normal source files not excluded
- `test_t0_changed_files_mode` — changed-files runs lint per file
- `test_t0_changed_files_excludes_noise` — excluded paths filtered out

## Verification
- All 83 tests pass (33 gate_resolver + 36 acceptance_pipeline + 14 stage0/scenario)
- Solar Sage `grace_front_lint.py` now correctly excludes generated/vendor paths
- `resolve_default_t0` uses `resolve_linter_mode()` for policy-based decisions

## Adoption plan
Staged adoption for Solar Sage GRACE canon:
1. ✅ Policy/config and linter behavior (this pilot)
2. Next: `components/today/` — small owned frontend slice
3. Next: Backend API slice (excluding Alembic/migrations)
4. Gradual package/core modules
5. Vendor/scaffold only if explicitly decided

## Failures
None
