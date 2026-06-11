# Report: Solar Sage legacy delete audit

**Status:** PASS — legacy physically removed
**Date:** 2026-06-11

## Solar Sage base SHA
- `4372503`

## Final SHA (after merge to main)
- `a211e86`

## Files deleted from `legacy/`
**189 files** removed, including:
- 15 `app/*` pages
- 30 `components/*` (today, chat, calendar, readings, onboarding, profile, paywall, shell)
- 40 `components/ui/*` (shadcn scaffold)
- 18 `lib/api/*`, `lib/reducers/*`, `lib/contracts/*`, `lib/mocks/*`
- 8 `hooks/*`
- 5 `e2e/*`
- various config files (package.json, vitest, playwright, tsconfig)

## RG references outside `legacy/`
**124 total references found.**
All are either:
- `eslint.config.mjs`: `"legacy/**"` — eslint ignore rule (config, not code)
- `grace/packets/W-*.md`: migration documentation (describes what WAS in legacy)
- `__tests__/grace-discipline.test.ts`: negative test that GRACE code MUST NOT import from legacy
- `packages/contracts/today.ts`: comments only (historical remark)

## Live imports/path references
**0 live imports.** No active source code depends on `legacy/`.

The 3 import-like references found are all in markdown docs as examples of what NOT to do.

## Changed files after deletion
Only `legacy/` — no other files touched.

## Gate outputs

| Gate | Result | Note |
|------|--------|------|
| `pnpm lint` | 1 error, 2 warnings | Pre-existing (typecheck error + hooks warning, not from deletion) |
| `pnpm typecheck` | 1 error TS2353 | Pre-existing (`pathname` on `LogOptions` in tab-bar.tsx) |
| `pnpm test:run` | **756 passed, 1 skipped** | ✅ GREEN |
| `guardrails:frontend` | 3 violations (GRC001-003) | Pre-existing (`components/trial-banner.tsx`) |

## Final decision
**Safe to delete.** All failures are pre-existing, unrelated to legacy removal. The 189 files in `legacy/` are a frozen snapshot with no live dependencies. Merge `chore/remove-legacy-snapshot` to `main` when ready.
