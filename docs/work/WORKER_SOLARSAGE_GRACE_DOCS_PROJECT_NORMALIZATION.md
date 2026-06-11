# Worker handoff: Solar Sage GRACE docs project normalization

**Status:** READY_FOR_WORKER
**Date:** 2026-06-11

## Goal

Bring Solar Sage GRACE/project documentation to a clean current-state model.

The old `legacy/` migration is complete. Documentation must no longer describe the project as an unfinished migration from `legacy/`.

Normalize the docs into: current modules, current slices, current contracts, current gates, and future business-feature workflow.

## Target

- Repo: `basilivanov/solarsage-astro`
- Baseline: `a211e86`
- Suggested branch: `docs/normalize-grace-project-docs`

## Core rule

This is a docs/canon cleanup task only.

Do not change runtime product code.

## Must inspect

- `grace/README.md`
- `grace/requirements.xml`
- `grace/technology.xml`
- `grace/development-plan.xml`
- `grace/knowledge-graph.xml`
- `grace/verification-matrix.md`
- `grace/canon.yaml`
- `grace/packets/`
- `grace/orchestrator/`
- `docs/MANIFEST.md`
- `MANIFEST.md`
- `docs/10_GRACE_Project_Agent_Guide.md`
- `docs/18_GRACE_оркестратор_подключение_TZ.md`
- `docs/work/2026-06-09_grace_audit.md`
- current tree: `app/`, `components/`, `lib/`, `apps/api/app/`, `packages/contracts/`, `scripts/`

Also use the latest GRACE report:

- `grace-orchestrator/docs/work/REPORT_SOLARSAGE_LEGACY_DELETE_AUDIT.md`

## Known drift

- `grace/README.md` still lists old W-2.x migration packets as active/current.
- W-2.x legacy migration work is done and must not remain the active roadmap.
- `legacy/` has been physically removed from Solar Sage main.
- `docs/10_GRACE_Project_Agent_Guide.md` still points to superseded contract docs as primary guidance.
- `docs/18_GRACE_оркестратор_подключение_TZ.md` has stale stack facts.
- Any doc saying legacy migration is still pending is stale.

## Required changes

### 1. Rewrite `grace/README.md`

Make it the current GRACE project entry point.

It must include:

- current source-of-truth order
- legacy removal as completed state
- living doc list
- current module families
- future slice model
- how a business feature becomes a GRACE packet
- current guardrail commands
- old W-2.x migration packets marked historical/completed, not active backlog

### 2. Clean `grace/packets/`

Audit old packets.

Remove or archive stale migration-era packets that are no longer useful for future execution.

Do not leave old W-2.x migration packets as the active plan.

### 3. Update `grace/development-plan.xml`

Future work must be expressed as current slices, not legacy migration.

Expected slice families:

- frontend shell/navigation
- Today/Calendar
- Horary/Readings
- Profile/Onboarding
- backend API edge
- backend services
- contracts/generation
- logging spine
- tests/verification
- production orchestrator readiness

### 4. Update `grace/knowledge-graph.xml`

Map current modules to real current paths.

Include current frontend, backend, contracts, sidecar/calculation, tests, guardrails, and orchestrator adapter modules.

### 5. Update `grace/technology.xml`

Technology facts must match current repo state, including current package versions and guardrails scripts.

### 6. Update `grace/verification-matrix.md`

Map current use cases/modules to runnable gates.

Include docs, orchestrator, contracts, frontend, backend, strict/canon-sync gates as appropriate.

### 7. Update `docs/10_GRACE_Project_Agent_Guide.md`

Future agents must be told to:

- read `grace/README.md` first
- use `apps/api/app/schemas/*` as API source of truth
- use `packages/contracts/index.ts` and generated contracts for frontend types
- identify affected modules before editing
- define write scope and frozen scope
- define logging/evidence requirements
- not revive legacy migration docs

### 8. Update manifests if needed

If docs under `docs/` are added/removed/renamed, update `docs/MANIFEST.md`.

## Gates

Run in Solar Sage:

```bash
pnpm guardrails:docs
pnpm guardrails:orchestrator
pnpm typecheck
pnpm test:run
```

Also run if frontend/GRACE lint docs or policy changed:

```bash
pnpm guardrails:frontend
```

Known pre-existing failures may be reported, but must be isolated from this docs cleanup.

## Report

Create in `grace-orchestrator`:

`docs/work/REPORT_SOLARSAGE_GRACE_DOCS_PROJECT_NORMALIZATION.md`

Report must include:

- PASS/FAIL
- base and final Solar Sage SHA
- files changed
- files removed or archived
- stale facts fixed
- final living GRACE doc set
- final module/slice map summary
- gates and results
- remaining mismatches, if any

## PASS criteria

PASS only if:

1. `grace/README.md` no longer presents W-2.x legacy migration as active work.
2. `legacy/` removal is reflected as completed state.
3. stale migration-era docs are removed or clearly historical.
4. current modules and slices are explicit.
5. business features can be mapped to modules, write scope, and gates.
6. `docs/10_GRACE_Project_Agent_Guide.md` points to current sources of truth.
7. technology facts match current repo state.
8. no runtime product code is changed.

## Commit messages

Solar Sage:

`docs: normalize GRACE project docs after legacy migration`

GRACE report:

`docs: add Solar Sage GRACE docs normalization report`
