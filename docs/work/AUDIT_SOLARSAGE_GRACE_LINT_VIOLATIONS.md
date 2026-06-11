# Audit: Solar Sage GRACE lint violations

**Date:** 2026-06-11
**Target:** `/opt/solarsage-astro` (basilivanov/solarsage-astro)
**Tool:** `scripts/grace_front_lint.py` + `scripts/grace_lint.py`
**Total violations: 2714** (frontend 1505 + backend 1209)

---

## Frontend violations (grace_front_lint.py)

**Total: 1505 violations across 506 files**

| GRC code | Description | Count |
|----------|-------------|-------|
| GRC001 | Missing AI_HEADER banner in first 30 lines | 496 |
| GRC002 | START_MODULE_CONTRACT/END_MODULE_CONTRACT mismatch | 503 |
| GRC003 | START_MODULE_MAP/END_MODULE_MAP mismatch | 506 |

Every frontend file in Solar Sage lacks all three GRACE conventions.
These are **GRACE orchestrator-specific conventions** — Solar Sage is a product frontend that doesn't use the GRACE module system.

The most common files:
- `components/ui/*.tsx` (shadcn/ui components) — all 40+ files
- `components/today/*.tsx` (Today screen components) — 10+ files
- `app/**/*.tsx` (Next.js pages) — all files
- `lib/**/*.ts` (utility libraries) — all files
- `__tests__/**/*.tsx` (unit tests) — all files
- `packages/**/*.ts` (contracts) — all files

---

## Backend violations (grace_lint.py)

**Total: 1209 violations**

| GRC code | Description | Count |
|----------|-------------|-------|
| GRC010 | Public function missing START_FUNCTION_CONTRACT/END_FUNCTION_CONTRACT | 752 |
| GRC021 | Missing START_MODULE_MAP block | 155 |
| GRC020 | Missing START_MODULE_CONTRACT block | 135 |
| GRC001 | Missing AI_HEADER banner in first 30 lines | 135 |
| GRC003 | START_MODULE_MAP/END_MODULE_MAP mismatch | 14 |
| GRC002 | START_MODULE_CONTRACT/END_MODULE_CONTRACT mismatch | 12 |
| GRC011 | Private function missing START_FUNCTION_CONTRACT/END_FUNCTION_CONTRACT | 4 |
| GRC030 | Missing function return type annotation | 2 |

Affected areas:
- `apps/api/app/**/*.py` — all API route files and business logic
- `apps/api/alembic/**/*.py` — all migration files
- `apps/api/core/**/*.py` — all core modules
- `apps/solarsage/**/*.py` — all Solar Sage service files
- `packages/**/*.py` — all package files

---

## Conclusion

**None of the Solar Sage source files conform to GRACE conventions** because Solar Sage is a product project, not the GRACE orchestrator.

The `grace_front_lint.py` and `grace_lint.py` scripts enforce conventions that are specific to the GRACE orchestrator:
- `AI_HEADER` banners identify module roles in the orchestrator
- `START_MODULE_CONTRACT`/`END_MODULE_CONTRACT` define module interfaces
- `START_FUNCTION_CONTRACT`/`END_FUNCTION_CONTRACT` define function contracts

These conventions are not applicable to Solar Sage product code.

**Fix applied in `e275bba`:** `resolve_default_t0()` now only runs GRACE linters for the orchestrator repo (detected via `.grace/state` directory). For target repos like Solar Sage, these linters are skipped.
