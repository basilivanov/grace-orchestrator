# CLI Deprecation Inventory

Date: 2026-06-05
Owner: W1 of `source/codex/tz-api-first-cleanup-waves-w0-w11.md`
Goal: enumerate every public CLI command, decide its migration path, and
prevent new CLI business logic from being introduced.

## Inventory

For each command the table records:

- **runtime/business logic?** — `yes` if the command mutates state, runs an
  executor, or does work that an agent would otherwise need an API for.
- **replacement API endpoint** — the OpenAPI endpoint that already covers
  the same surface, or `TBD` if the wave is supposed to add it.
- **migration action** — one of:
  - `delete` — pure CLI scaffolding, no replacement needed.
  - `convert-to-api` — move capability into a router endpoint, then delete.
  - `keep-as-dev-script` — keep the code as a script under `scripts/`
    for CI / dev use only; do not advertise as runtime CLI.
  - `temporary-thin-client` — keep a thin CLI that just calls the API
    over HTTP, as a transition aid; remove by W9.
- **risk** — what breaks if we delete it.
- **acceptance test** — the test that proves the migration is complete.

### `src/grace_control/cli/main.py`

| command | current behavior | runtime/business? | replacement API | migration action | risk | acceptance test |
|---------|------------------|-------------------|-----------------|------------------|------|-----------------|
| `up` | boots API server in a thread, runs a Worker loop, optionally auto-submits YAML from `grace/features/` | yes | `/api/architect/plan`, `/api/workers/register`, `/api/packets/claim`, deployment unit | `delete` (deployment is an ops concern, not a product CLI) | docs only; deployments move to systemd / k8s | `test_no_business_cli_in_runtime_package` (W2) |
| `init` | scaffolds `grace/{packets,features}` and writes a sample YAML | no | template repo / docs | `delete`; ship as `scripts/init_template.py` | none | none |
| `lint` | runs `GraceCanonChecker` over a path; prints text or JSON | yes | `POST /api/tools/grace-lint/run` (W4/W10) | `keep-as-dev-script` (`scripts/grace_lint.py`) + `convert-to-api` (W10) | CI must still call it | `test_grace_lint_script` |
| `eval run` | spawns workers, runs packets, optionally Playwright | yes | `POST /api/tools/smoke/run` (W4) | `delete` CLI; `keep-as-dev-script` (`scripts/local_smoke.py`) | smoke harness must move | `test_no_business_cli_in_runtime_package` |
| `eval report` | queries `/api/architect/features/...` for a report | no | `GET /api/trace/features/{id}` (W4) | `delete` | dashboard only | `test_openapi_has_trace_paths` |
| `architect plan` | POSTs to `/api/architect/plan` | no | `POST /api/architect/plan` | `temporary-thin-client` (or `delete`) | none | `test_architect_plan_via_api` |
| `packet list` | GETs `/api/packets/` and renders a Rich table | no | `GET /api/packets/` | `temporary-thin-client` (or `delete`); dashboard renders the same | UX loses terminal table | `test_openapi_has_packets_paths` |
| `packet get` | GETs `/api/packets/{id}` | no | `GET /api/packets/{id}` | `temporary-thin-client` (or `delete`) | UX | `test_openapi_has_packets_paths` |
| `worker start` | runs a worker loop calling claim/release | yes | `/api/packets/claim`, `/api/packets/{id}/release` | `delete` (deployment is ops) | deployment docs | `test_no_business_cli_in_runtime_package` |
| `api start` | runs `uvicorn.run(app, ...)` | yes | deployment | `delete` | deployment docs | `test_no_business_cli_in_runtime_package` |
| `health` | GETs `/health` | no | `GET /health` | `temporary-thin-client` (or `delete`) | UX | `test_openapi_has_health_path` |
| `golden` / `fixture run-one` | runs a golden fixture | yes | `POST /api/tools/golden/run/{fixture}` (future) | `keep-as-dev-script` (`scripts/run_golden.py`) | CI must still call it | `test_golden_smoke_runs_via_script` |

### `src/grace_control/cli/trace.py`

| command | current behavior | runtime/business? | replacement API | migration action | risk | acceptance test |
|---------|------------------|-------------------|-----------------|------------------|------|-----------------|
| `trace --packet/--feature/--wave` | queries DB directly, formats a timeline | yes (reads `events`/`packet_runs`) | `GET /api/trace/packets/{id}` (W4), `GET /api/trace/features/{id}` (W4), `GET /api/trace/search?q=...` (W4) | `delete` once W4 lands | agents lose a debug surface until W4 ships | `test_openapi_has_trace_paths` |

### Legacy entrypoints (in `pyproject.toml`)

| entrypoint | current behavior | runtime/business? | replacement API | migration action | risk | acceptance test |
|------------|------------------|-------------------|-----------------|------------------|------|-----------------|
| `grace-dev` (from `prefect_grace.devtools.cli:main`) | legacy dev CLI | yes | n/a (legacy) | `delete` from `[project.scripts]` in W2 | none (W8 removes the whole package) | `test_no_legacy_entrypoints_in_pyproject` |
| `prefect-grace` (from `prefect_grace.cli_compat:prefect_grace_main`) | legacy compat | yes | n/a (legacy) | `delete` from `[project.scripts]` in W2 | none | `test_no_legacy_entrypoints_in_pyproject` |
| `gracectl` (from `prefect_grace.cli_compat:gracectl_main`) | legacy compat | yes | n/a (legacy) | `delete` from `[project.scripts]` in W2 | none | `test_no_legacy_entrypoints_in_pyproject` |

## Migration status

This table is updated as waves W1..W11 land. A row is `done` only when
both the migration action is complete and the acceptance test passes.

| command | status | landed in |
|---------|--------|-----------|
| `up` | TODO | W2 |
| `init` | TODO | W2 |
| `lint` | TODO (script extracted) | W2 + W10 |
| `eval run` | TODO (script extracted) | W2 + W4 |
| `eval report` | TODO | W2 + W4 |
| `architect plan` | TODO | W2 |
| `packet list` | TODO | W2 |
| `packet get` | TODO | W2 |
| `worker start` | TODO | W2 |
| `api start` | TODO | W2 |
| `health` | TODO | W2 |
| `golden` / `fixture run-one` | TODO | W2 + W4 |
| `trace --packet/--feature/--wave` | TODO | W2 + W4 |
| `grace-dev` | TODO | W2 + W8 |
| `prefect-grace` | TODO | W2 + W8 |
| `gracectl` | TODO | W2 + W8 |

## Missing API capabilities (carry-overs to W4)

The following endpoints do not exist yet and must be added in W4 to
unblock the `delete` / `convert-to-api` actions above:

```text
GET  /api/trace/packets/{packet_id}
GET  /api/trace/features/{feature_id}
GET  /api/trace/runs/{run_id}
GET  /api/trace/search?q=...
GET  /api/events
GET  /api/diagnostics/state
POST /api/tools/grace-lint/run
POST /api/tools/smoke/run
POST /api/tools/docs/check
```

When each is shipped, the corresponding row above moves from
`convert-to-api` to `done` and the CLI command is deleted in the same PR.
