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
