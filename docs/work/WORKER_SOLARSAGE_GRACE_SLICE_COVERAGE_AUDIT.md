# Worker handoff: Solar Sage GRACE slice coverage audit

**Status:** READY_FOR_WORKER
**Date:** 2026-06-11

## Goal

Audit actual GRACE coverage in `basilivanov/solarsage-astro`.

Do not add contracts or logs yet. First produce a reliable inventory:

- which slices/modules exist in code
- which files already have GRACE markers
- which files already have logs
- which slices are missing or only documented
- what adoption waves are needed before autonomous business-feature work

## Target

- Repo: `basilivanov/solarsage-astro`
- Current baseline: `06b2431`
- Suggested branch: `audit/grace-slice-coverage`

## Scope

Audit only. Runtime code must not be changed.

Allowed changes:

- add audit script if useful, preferably under `scripts/grace/`
- add report under `docs/work/`
- add machine-readable inventory JSON under `docs/work/`

Do not mass-edit source files.

## Inputs to inspect

Use these current source-of-truth docs:

- `grace/README.md`
- `grace/knowledge-graph.xml`
- `grace/development-plan.xml`
- `grace/verification-matrix.md`
- `grace/canon.yaml`
- `docs/10_GRACE_Project_Agent_Guide.md`

Audit these code areas:

- `app/**/*.ts`, `app/**/*.tsx`
- `components/**/*.ts`, `components/**/*.tsx`
- `lib/**/*.ts`, `lib/**/*.tsx`
- `packages/contracts/**/*.ts`
- `apps/api/app/**/*.py`
- `apps/solarsage/**/*.py`
- `scripts/**/*.py`, `scripts/**/*.ts`, `scripts/**/*.mjs`, `scripts/**/*.sh`
- tests under `__tests__/`, `apps/api/tests/`, `apps/solarsage/tests/`

Exclude generated/vendor/scaffold paths according to `grace/canon.yaml`, especially:

- `node_modules/**`
- `.next/**`
- `.venv/**`
- `components/ui/**`
- `alembic/**` / `**/alembic/**` unless explicitly auditing migrations as a DB slice
- lockfiles
- minified files

## Required slice registry

Create a current slice registry. At minimum classify files into these slices:

1. `SLICE-SHELL-NAVIGATION`
2. `SLICE-TODAY-CALENDAR`
3. `SLICE-HORARY-READINGS`
4. `SLICE-PROFILE-ONBOARDING`
5. `SLICE-FRONTEND-API-FACADES`
6. `SLICE-CONTRACTS`
7. `SLICE-BACKEND-API-ROUTERS`
8. `SLICE-BACKEND-SERVICES`
9. `SLICE-DB-MODELS-MIGRATIONS`
10. `SLICE-SIDECAR-CALCULATION`
11. `SLICE-SCORING-SEMANTIC-LLM`
12. `SLICE-LOGGING-SPINE`
13. `SLICE-TESTS`
14. `SLICE-GUARDRAILS-TOOLING`
15. `SLICE-ORCHESTRATOR-ADAPTER`

If a file does not fit, classify it as `SLICE-UNMAPPED` and explain why.

## Required per-file inventory

For every audited file, collect:

- path
- language
- slice
- module id if discoverable from `grace/knowledge-graph.xml` or marker text
- has `AI_HEADER`
- has `START_MODULE_CONTRACT`
- has `END_MODULE_CONTRACT`
- has `START_MODULE_MAP`
- has `END_MODULE_MAP`
- count of `START_BLOCK`
- count of `END_BLOCK`
- marker pairing status if existing linters can determine it
- has structured logging
- logging mechanism found, e.g. frontend `lib/grace/log`, backend logger/structlog, console, print
- whether logging is declared in module contract/map if markers exist
- adoption priority: P0/P1/P2/skip
- notes

## Logging detection

Detect at least:

Frontend:

- imports/usages of `lib/grace/log`
- `logger`, `logEvent`, `log_event`, `track`, `emit`
- `console.*` as non-canonical logging

Backend:

- `structlog`, `logging.getLogger`, project logger helpers
- `print(` as non-canonical logging
- correlation/request-id patterns if present

Classify logs as:

- canonical
- acceptable but undocumented
- non-canonical
- missing but needed
- not needed

## Required outputs

Create in Solar Sage:

1. `docs/work/REPORT_SOLARSAGE_GRACE_SLICE_COVERAGE_AUDIT.md`
2. `docs/work/solarsage_grace_slice_coverage.json`

The markdown report must include:

- PASS/FAIL audit status
- baseline SHA
- total files audited
- coverage summary table
- coverage by slice
- top unmapped files/directories
- files with partial/broken markers
- files with logs but no declared side effects
- files where logs are probably needed for autonomous agents
- missing slices
- recommended adoption waves
- exact command(s) used to generate the audit

The JSON must include:

```json
{
  "baseline_sha": "...",
  "summary": {},
  "slices": [],
  "files": []
}
```

## Recommended commands

Use local repo checkout if available:

```bash
cd /opt/solarsage-astro

git status --short
git rev-parse --short HEAD

python3 scripts/grace_front_lint.py --help || true
python3 scripts/grace_lint.py --help || true

rg -n "AI_HEADER|START_MODULE_CONTRACT|START_MODULE_MAP|START_BLOCK|END_BLOCK" \
  app components lib packages apps scripts __tests__ \
  --glob '!components/ui/**' --glob '!node_modules/**' --glob '!.next/**' || true

rg -n "lib/grace/log|logger|logEvent|log_event|structlog|logging.getLogger|console\.|print\(" \
  app components lib packages apps scripts __tests__ \
  --glob '!components/ui/**' --glob '!node_modules/**' --glob '!.next/**' || true
```

Prefer writing a small deterministic audit script so the result can be repeated.

## Required gates

Run:

```bash
pnpm test:run
```

If only docs/audit files changed, do not require full runtime gates. If an audit script is added, run its self-check or at least run it twice and confirm deterministic JSON output.

Also run if practical:

```bash
pnpm guardrails:docs
pnpm guardrails:orchestrator
```

Known pre-existing failures must be reported separately and not hidden.

## Acceptance criteria

PASS if:

1. Report and JSON inventory are created.
2. Every relevant source/test/tooling file is either mapped to a slice or explicitly listed as unmapped.
3. Coverage percentages are computed from current code, not copied from old 2026-06-09 audit.
4. Missing slices and adoption waves are explicit.
5. Logging coverage is summarized by slice.
6. No runtime product source is changed.
7. `pnpm test:run` remains green or any failure is proven pre-existing.

## Suggested next adoption waves

The report should propose follow-up worker packets, not implement them. Suggested wave names:

- `W-GRACE-SLICE-P0-TODAY-CALENDAR`
- `W-GRACE-SLICE-P0-BACKEND-API-SERVICES`
- `W-GRACE-SLICE-P0-CONTRACTS`
- `W-GRACE-SLICE-P1-HORARY-READINGS`
- `W-GRACE-SLICE-P1-PROFILE-ONBOARDING`
- `W-GRACE-SLICE-P1-LOGGING-SPINE`
- `W-GRACE-SLICE-P2-TESTS-TOOLING`

## Safety rules

- Do not add or modify product behavior.
- Do not mass-add markers.
- Do not mass-add logs.
- Do not change API schemas.
- Do not change migrations.
- Do not change package manager files.
- Do not edit generated contracts.

## Commit messages

Solar Sage:

`docs: add GRACE slice coverage audit`

GRACE report, if mirrored:

`docs: add Solar Sage GRACE slice coverage audit handoff`
