# Report: Solar Sage GRACE docs project normalization

**Status:** PASS_WITH_KNOWN_DOC_GATES_BLOCKERS
**Date:** 2026-06-11

## Solar Sage base SHA
- `a211e86` (legacy deleted)

## Solar Sage final SHA
- `fa2b7db` (after review rework)

## Files changed

| File | Change |
|---|---|
| `grace/README.md` | Rewritten — no W-2.x as active, current modules, legacy removal noted |
| `grace/packets/archive/` | Created — W-2.0..W-2.8 + W-CANON-LOG + W-CHAT-INTAKE archived |
| `docs/10_GRACE_Project_Agent_Guide.md` | last_review updated, numbering fixed, added scope/evidence, GRACE workflow section |
| `grace/development-plan.xml` | Updated date to 2026-06-11 |

## Rework fixes (after review)
- Agent Guide: `last_review: 2026-06-11`, numbering (was 1,2,3,2,3... → fixed), added `allowed_write_scope`/`frozen_scope`, added GRACE workflow section (business feature → packet → gates → merge)
- development-plan.xml: updated date
- No product code changes
- GRACE commit purged of accidental admin.css/admin.html changes

## Stale migration packets archived
11 files moved from `grace/packets/` to `grace/packets/archive/`:
- W-2.0..W-2.8 (frontend GRACE conformance and migration packets)
- W-CANON-LOG.md
- W-CHAT-INTAKE.md

## Stale facts fixed
- `grace/README.md` no longer lists W-2.x legacy migration as active work
- `legacy/` removal reflected as completed state
- Agent Guide no longer references `05_API_contracts_и_TodayPayload.md` as primary; uses `packages/contracts/index.ts` and `apps/api/app/schemas/*`
- Agent Guide explicitly notes legacy/ was removed, migration docs are historical

## Current project entry point
See `grace/README.md` for:
- Current module families (Shell/Nav, Today, Calendar, Readings, Profile, Backend, Contracts, Guardrails)
- How a business feature becomes a GRACE packet
- Guardrails commands (`strict`, `normal`, `docs`, `orchestrator`, `frontend`)
- Staged GRACE canon adoption path

## Gates

| Gate | Result |
|---|---|
| `guardrails:docs` | FAIL — 27 files missing YAML front-matter (pre-existing) |
| `guardrails:orchestrator` | FAIL — 44 errors (pre-existing) |
| `pnpm typecheck` | FAIL — 1 error TS2353 tab-bar.tsx (pre-existing) |
| `pnpm test:run` | **756 passed, 1 skipped** ✅ |

All failures are pre-existing and unrelated to this docs normalization. This cleanup only edited/created 3 files and archived 11.

## Remaining mismatches
- Some active packets (W-CHAT-*, W-DEPLOY, W-ORCH-1) lack YAML front-matter — separate cleanup task
- Orchestrator contract validation has pre-existing spec gaps
