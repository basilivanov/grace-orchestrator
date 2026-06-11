# Worker handoff: Solar Sage Pilot 006 — GRACE canon linter policy and adoption

**Status:** READY_FOR_WORKER
**Date:** 2026-06-11

## Background

A full audit was run against `/opt/solarsage-astro` using GRACE linters:

- `scripts/grace_front_lint.py`
- `scripts/grace_lint.py`

The audit found thousands of violations because the current Solar Sage product codebase is not yet migrated to the GRACE source-code canon.

Recorded audit report:

- `docs/work/AUDIT_SOLARSAGE_GRACE_LINT_VIOLATIONS.md`

Observed totals from the audit:

- frontend: 1505 violations across 506 files
- backend: 1209 violations
- total: 2714 violations

The prior quick fix made `resolve_default_t0()` skip GRACE linters for target repos and run them only for the orchestrator repo detected through `.grace/state`.

That is directionally useful for avoiding noisy product-repo failures, but it is too coarse.

## Problem

We need a better policy for GRACE linters:

1. Full-repo GRACE lint should not be automatically forced on every arbitrary target repo.
2. Changed files touched by coder agents still need lint/canon checks when the target repo opts into GRACE canon or when a pilot explicitly asks for GRACE-canon adoption.
3. Audit mode and gate mode must be separated.
4. Generated/vendor/framework files must not create meaningless noise.
5. Product code such as Solar Sage frontend/backend should be migratable to GRACE canon in controlled slices.

## Key design decision

GRACE linter behavior must be scope-aware.

Recommended modes:

### 1. `gate-changed-files` mode

Used during normal coder waves.

Lint only files changed by the current wave/packet.

This should be the default for target repos that are GRACE-canon-enabled or for tasks that explicitly request GRACE canon checks.

### 2. `audit-full-repo` mode

Used only for explicit audit/migration tasks.

This mode may scan the whole repo and write a report, but it should not block ordinary product feature work unless a threshold/baseline policy says so.

### 3. `orchestrator-strict` mode

Used inside `grace-orchestrator` itself.

GRACE source-code conventions are mandatory and should remain gate-blocking.

### 4. `disabled-for-target` mode

Used for product repos that have not opted into GRACE canon and when the current task is unrelated to canon migration.

## Opt-in / detection proposal

Do not rely only on `.grace/state`.

Add an explicit canon config, for example one of:

- `grace/canon.yaml`
- `.grace/canon.yaml`
- `grace.toml`

The exact file name is up to the worker, but the policy must be explicit and documented.

The config should allow:

- enabling GRACE canon for a target repo
- listing included path globs
- listing excluded path globs
- selecting gate mode: changed-files / full-repo / disabled
- optionally allowing baseline files for staged migration

## Required exclusions

Exclude generated/vendor/framework/infrastructure noise from GRACE canon by default unless explicitly included.

At minimum exclude:

- `node_modules/**`
- `.next/**`
- `.venv/**`
- `__pycache__/**`
- generated build outputs
- package manager lockfiles
- `apps/api/alembic/**`
- migration files such as `**/migrations/**`
- shadcn/vendor UI components if classified as vendor scaffolding, for example `components/ui/**`, unless we decide to own and migrate them

Important: Alembic migration files should generally not require `AI_HEADER`, module contracts, or function contracts. They are generated/operational artifacts, not normal source modules.

## Changed-file gate requirement

Even if full target-repo lint is disabled, the worker must ensure the linter can validate the coder's changed files when one of these is true:

- the repo has GRACE canon opt-in config
- the task is explicitly a GRACE-canon adoption/migration task
- the changed file is already GRACE-canon-marked and should not regress
- the task modifies GRACE-owned source files

This prevents the system from silently skipping checks on product repos forever.

## Comment marker formatting decision

Use idiomatic comment spacing:

- Python: `# AI_HEADER: ...`
- Python: `# START_MODULE_CONTRACT: ...`
- TypeScript/JavaScript: `// AI_HEADER: ...`
- TypeScript/JavaScript: `// START_MODULE_CONTRACT: ...`

Do not require marker text to start immediately after the comment character.

`# START_BLOCK: X` is preferred over `#START_BLOCK: X`.

Rationale:

- more idiomatic in Python/JS/TS
- better readability for humans and LLMs
- GitHub search and grep handle both, but the spaced form is easier to scan
- formatters and linters are less likely to object

Parser requirement:

The GRACE linters should accept optional whitespace after the comment marker, for example:

- `# START_BLOCK: X`
- `#START_BLOCK: X`
- `// START_BLOCK: X`
- `//START_BLOCK: X`

But newly generated code and documentation must use the spaced canonical form.

## Business feature input for this pilot

Use this as the business-level request to the pipeline:

```md
Нужно привести GRACE lint policy и Solar Sage GRACE-canon adoption flow в рабочее состояние.

Сейчас GRACE linters при полном скане Solar Sage дают тысячи нарушений, включая Alembic migrations и другой шум. Это делает gate непригодным для product repo.

Нужно:

1. Разделить режимы линтера: strict для grace-orchestrator, changed-files gate для target repos, full-repo audit только по явной команде.
2. Добавить явную opt-in policy/config для target repo GRACE canon.
3. Исключить generated/vendor/migration noise, включая Alembic.
4. Сохранить возможность проверять файлы, которые реально менял coder, если repo opt-in или задача про GRACE canon.
5. Поддержать пробел после comment marker (`# START...`, `// START...`) как канонический стиль, но парсер должен быть tolerant к отсутствию пробела.
6. Подготовить staged adoption plan для Solar Sage: какие каталоги мигрировать первыми, какие исключить, как не ломать product work.
7. Добавить тесты на policy/detection/exclusion/changed-files behavior.
8. Обновить docs/work отчётом.
```

## Expected implementation areas

Likely files/areas to inspect and update:

- default T0 resolution code
- GRACE lint runner integration
- `scripts/grace_lint.py`
- `scripts/grace_front_lint.py`
- tests for linter policy and path exclusions
- docs/work report

The worker must find the exact files through architect/context, not assume all names above are exhaustive.

## Acceptance criteria

Pilot 006 is PASS only if all of these are true:

- business-level input was used, not a pre-baked implementation patch
- architect generated a plan
- context bundle ran
- linter modes are explicit and documented
- orchestrator strict mode still blocks violations in GRACE-owned code
- target repo default full-repo GRACE lint noise is not used as an ordinary feature gate
- changed-files GRACE lint can run for target repos when opted-in or explicitly requested
- Alembic/migrations are excluded from GRACE canon by default
- parser accepts optional whitespace after comment markers
- generated code/docs use spaced canonical marker style
- tests cover detection, exclusion, parser tolerance, and changed-file gate behavior
- no package/lock/env/auth/payment/subscription/deployment files are changed unless absolutely necessary and explained
- final report is written to `docs/work/REPORT_SOLARSAGE_PILOT_006_GRACE_CANON_LINTER_AND_ADOPTION.md`
- T0/T1/T2 pass
- verifier accepts the result
- watchdog_restarts is `0`
- failures is `[]`

## Solar Sage staged adoption recommendation

Do not migrate all 506 frontend files and all backend files in one wave.

Recommended staged order:

1. GRACE policy/config and linter behavior first.
2. One small owned frontend slice, for example `components/today/tab-bar.tsx` and its test.
3. One small owned backend/API slice, excluding Alembic and migrations.
4. Gradual package/core modules.
5. Vendor/scaffold directories only if we explicitly decide they are owned source.

## Report requirements

Create:

`docs/work/REPORT_SOLARSAGE_PILOT_006_GRACE_CANON_LINTER_AND_ADOPTION.md`

The report must include:

- status PASS/FAIL
- date
- GRACE commit tested
- business input
- architect summary
- context bundle path
- changed files
- linter policy before/after
- exclusion list
- tests added/updated
- T0/T1/T2 outputs
- verifier verdict
- final decision on Solar Sage staged adoption
- failures list

## Important note

Do not treat the current 2714 violations as a reason to mass-edit the whole product repo immediately.

The purpose of this pilot is to make the linter policy correct and to define a safe adoption path. Mass migration should be a later controlled campaign with small slices and reports.
