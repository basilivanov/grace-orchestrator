# GRACE Canon — Module Contracts

Every module in `src/grace_control/` follows a strict comment canon:

```
AI_HEADER         — One-line role description
START_MODULE_CONTRACT / END_MODULE_CONTRACT
                  — purpose, inputs, returns, side_effects, emitted_logs, error_behavior
START_MODULE_MAP / END_MODULE_MAP
                  — JSON-like listing of all public classes/functions
START_FUNCTION_CONTRACT / END_FUNCTION_CONTRACT
                  — per-function equivalent of the module contract
START_BLOCK_* / END_BLOCK_*
                  — DTO helpers, private blocks (< 20 lines)
```

All structured logs use `GraceLogger("component_name")` and emit JSONL to
stderr with keys `component`, `msg`, `trace_id`, and `ctx.reason`.

No module may import `prefect_grace` (enforced by GraceLint GRC100).

Convention: frozen dataclass DTOs (e.g. `ClaimResult`, `CancelResult`) for
ORM session safety. Routers never contain DB-aggregation loops.

The public runtime/operator surface is FastAPI/OpenAPI. The control/user CLI
and OpenCode runtime are removed; mini-swe and the generic CLI/subprocess
backend remain internal packet-execution infrastructure. Lifecycle routers
delegate through explicit service/port composition, and Admin
cross-project/Control Center/aggregation services use constructor injection;
typed Admin read models are bounded shared service boundaries.

Repository hygiene is owned by `scripts/ci_repo_hygiene.py`. The root
`Makefile` is the single source of truth for `make test`, `make lint`,
`make docs-check`, `make hygiene`, and aggregate `make ci`; GitHub Actions
delegates to those targets rather than copying their policy.
