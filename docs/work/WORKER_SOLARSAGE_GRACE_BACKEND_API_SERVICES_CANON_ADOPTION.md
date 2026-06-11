# Worker handoff: Solar Sage backend GRACE canon adoption

**Status:** READY_FOR_WORKER
**Date:** 2026-06-12

## Goal

Adopt GRACE canon markers for the Solar Sage backend API/services slice.

This packet is not a product feature. It must not change runtime behavior. The goal is to make backend files readable and safe for autonomous GRACE packets:

- AI_HEADER in every in-scope backend file
- START/END_MODULE_CONTRACT in every in-scope backend file
- START/END_MODULE_MAP in every in-scope backend file
- START/END_BLOCK for meaningful route/service/core blocks
- START/END_FUNCTION_CONTRACT for public functions, route handlers, service methods, and impure/private helpers
- emitted_logs declarations aligned with the existing v2 logging spine

## Target repo

- Repository: `basilivanov/solarsage-astro`
- Current baseline: `main` after GRACE slice docs update
- Suggested branch: `grace/backend-api-services-canon-adoption`

## Recommended approach

Do not do a blind whole-repo rewrite.

Use this flow:

1. Run a local backend-only coverage pre-audit.
2. Patch the backend API/services/core files in small groups.
3. Keep behavior unchanged.
4. Run backend tests and GRACE coverage audit.
5. Produce a report.

## Scope

### In scope

Primary P0 backend scope:

- `apps/api/app/api/**/*.py`
- `apps/api/app/services/**/*.py`
- `apps/api/app/core/**/*.py`

Related tests only when needed to keep test snapshots/imports green:

- `apps/api/tests/**/*.py`

### Conditional scope

Use only if directly imported by touched API/services/core files:

- `apps/api/app/schemas/**/*.py`
- `apps/api/app/db/**/*.py`

### Out of scope

Do not touch unless separately approved:

- Alembic migration files
- package manager files
- generated contracts
- frontend files
- sidecar runtime files
- product behavior
- DB schema semantics

## Marker canon

Use the current project style.

Python module header:

```py
# ############################################################################
# AI_HEADER: MODULE_<STABLE_ID>
# ROLE: One-line role of this file.
# DEPENDENCIES: local imports / external services.
# GRACE_ANCHORS: [BLOCK_A, BLOCK_B]
# SLICE: SLICE-BACKEND-API-ROUTERS | SLICE-BACKEND-SERVICES
# ############################################################################
```

Module contract:

```py
# START_MODULE_CONTRACT
# purpose: ...
# owns:
#   - path/to/file.py
# inputs: ...
# outputs: ...
# dependencies: ...
# side_effects: ...
# emitted_logs: event.name, other.event OR n/a (pure) OR inherited from caller
# invariants:
#   - ...
# failure_policy: ...
# END_MODULE_CONTRACT
```

Module map:

```py
# START_MODULE_MAP
# mapping:
#   - function_or_class: Name
#     block: BLOCK_NAME
#     contract: short description
# END_MODULE_MAP
```

Named blocks:

```py
# START_BLOCK: ROUTES
...
# END_BLOCK: ROUTES
```

Function contract:

```py
# START_FUNCTION_CONTRACT
# name: function_name
# purpose: ...
# inputs: ...
# returns: ...
# side_effects: ...
# emitted_logs: ...
# error_behavior: ...
# END_FUNCTION_CONTRACT
```

## Function-contract rule

Add function contracts to:

- all FastAPI route handlers
- all public service methods
- class constructors when they bind dependencies or state
- background/job entrypoints
- impure helpers that read/write DB, network, cache, filesystem, env, auth/session, or logs
- private helpers when they encode important business decisions

Tiny pure helpers may be covered by the surrounding block if adding a contract would be noise, but the final report must list any skipped helpers.

## Logging rule

Do not rewrite the logging spine in this packet.

Current accepted logging implementation is v2:

- frontend: `lib/log/index.ts`, `lib/log/shipper.ts`
- backend: `apps/api/app/core/logging.py`
- backend API intake: `apps/api/app/api/_log.py`
- backend service intake: `apps/api/app/services/log_intake.py`

For touched backend files:

1. If a function already calls `log_event`, declare the exact event names in `emitted_logs`.
2. If logging context is bound with `bind_log_context` or `log_block`, document slice/module/block in contract notes.
3. If code uses deprecated stdlib `logger`/`logging.getLogger` for application events, either keep behavior unchanged and mark `non_canonical_logging_existing`, or migrate only if trivial and tests cover it.
4. Do not invent high-volume logs everywhere.
5. Do not add sensitive payload fields.

Important: the current `coverage_audit.py` may undercount v2 logging. If this packet touches the audit detector, do it in a separate small commit or explain clearly in the report.

## Slice mapping

Use these slices/modules:

- API routers: `SLICE-BACKEND-API-ROUTERS`, module `M-BACKEND-API`
- Services/core: `SLICE-BACKEND-SERVICES`, module `M-BACKEND-SERVICES`
- DB files, if touched: `SLICE-DB-MODELS-MIGRATIONS`, module `M-DB`
- Schemas, if touched: `SLICE-CONTRACTS`, module `M-CONTRACTS`
- Logging files, if touched: `SLICE-LOGGING-SPINE`, module `M-LOGGING-SPINE`

## Pre-audit commands

Run from Solar Sage root:

```bash
git status --short
git rev-parse --short HEAD
python3 scripts/grace/coverage_audit.py --check

python3 - <<'PY'
from pathlib import Path
roots = [Path('apps/api/app/api'), Path('apps/api/app/services'), Path('apps/api/app/core')]
for root in roots:
    if not root.exists():
        continue
    for p in sorted(root.rglob('*.py')):
        text = p.read_text(errors='ignore')
        print(p, 'AI_HEADER=', 'AI_HEADER:' in text, 'MODULE_CONTRACT=', 'START_MODULE_CONTRACT' in text, 'MODULE_MAP=', 'START_MODULE_MAP' in text, 'BLOCKS=', text.count('START_BLOCK'), 'FUNCTION_CONTRACTS=', text.count('START_FUNCTION_CONTRACT'))
PY
```

Save the before/after summary in the report.

## Required edits

For each in-scope file:

1. Add or correct AI_HEADER.
2. Add or correct MODULE_CONTRACT.
3. Add or correct MODULE_MAP.
4. Add named START_BLOCK/END_BLOCK around coherent groups:
   - ROUTES
   - SERVICE_METHODS
   - DTO_MAPPING
   - VALIDATION
   - AUTH_CONTEXT
   - LOG_CONTEXT
   - ERROR_HANDLING
   - BACKGROUND_TASKS
   - HELPERS
5. Add FUNCTION_CONTRACTS according to the function-contract rule.
6. Align emitted_logs declarations with actual calls.
7. Keep imports, logic, return values, schemas, routes, and DB behavior unchanged unless a syntax/lint fix is required.

## Required gates

Run:

```bash
python3 scripts/grace/coverage_audit.py --check
pnpm test:run
```

If available and not known-broken, also run:

```bash
pnpm guardrails:docs
pnpm guardrails:orchestrator
pnpm guardrails:frontend
```

If known pre-existing failures remain, report them separately and prove this packet did not introduce them.

## Required report

Create in Solar Sage:

`docs/work/REPORT_SOLARSAGE_GRACE_BACKEND_API_SERVICES_CANON_ADOPTION.md`

Report must include:

- PASS/FAIL
- base SHA and final SHA
- files changed
- exact backend files adopted
- before/after coverage summary for `apps/api/app/api`, `apps/api/app/services`, `apps/api/app/core`
- number of AI_HEADER added/fixed
- number of MODULE_CONTRACT added/fixed
- number of MODULE_MAP added/fixed
- number of START_BLOCK groups added/fixed
- number of FUNCTION_CONTRACTS added/fixed
- log events declared
- skipped helpers and why
- gates run and results
- remaining gaps

## Acceptance criteria

PASS only if:

1. Every in-scope backend router/service/core file has AI_HEADER.
2. Every in-scope backend router/service/core file has MODULE_CONTRACT.
3. Every in-scope backend router/service/core file has MODULE_MAP.
4. Major route/service/core sections have named START_BLOCK/END_BLOCK pairs.
5. Route handlers and public service methods have FUNCTION_CONTRACTS.
6. Existing log_event calls are reflected in emitted_logs declarations.
7. Runtime behavior is unchanged.
8. `python3 scripts/grace/coverage_audit.py --check` passes.
9. `pnpm test:run` passes or failures are proven pre-existing.

## Safety rules

- No product behavior changes.
- No DB schema changes.
- No route path changes.
- No payload shape changes.
- No generated contract edits.
- No migration edits.
- No frontend edits.
- No broad logging rewrite.
- No mass repo-wide canonization.

## Suggested commit message

Solar Sage:

`docs: adopt GRACE canon for backend API and services`

GRACE report/review later:

`docs: review Solar Sage backend GRACE canon adoption`
