# GRACE Control Plane

**LLM-driven autonomous development orchestrator** — packet-based, agent-driven, SQLite-backed.

## Quick start

```bash
pip install grace-orchestrator
```

```bash
# Recommended: use the supervisor (API + worker, auto-restart, mtime watch)
scripts/live_supervisor.sh --target-dir /tmp/grace-live-wt --source-dir /tmp/grace-orchestrator-export

# Or start API-only (manual worker management):
uvicorn grace_control.api.main:app --host 127.0.0.1 --port 8042
```

## Documentation

See [`docs/README.md`](docs/README.md) for the full document index.

Key docs:
- [Architecture](docs/grace/ARCHITECTURE.md) — component layers
- [Supervisor](docs/SUPERVISOR.md) — process manager, lifecycle, auto-reload, CLI (`grace_ctl`)
- [API First Control Plane](docs/grace/API_FIRST_CONTROL_PLANE.md) — the canonical contract
- [Configuration](docs/grace/CONFIGURATION.md) — env / `.grace/config.yaml` / defaults
- [Execution Backends](docs/grace/EXECUTION_BACKENDS.md) — `cli` (default) / `mock` / `api` (legacy: removed in W8)
- [Execution Pipeline](docs/grace/EXECUTION_PIPELINE.md) — claim → execute → acceptance → merge
- [State Machine](docs/grace/STATE_MACHINE.md) — packet state transitions
- [Acceptance Pipeline](docs/grace/ACCEPTANCE_PIPELINE.md) — T0/T1/T2 + verifier + reviewer
- [Trace & Observability](docs/grace/TRACE_AND_OBSERVABILITY.md) — trace API
- [Testing Strategy](docs/grace/TESTING_STRATEGY.md) — test layers and conventions

## OpenAPI

```bash
curl http://127.0.0.1:8042/openapi.json
```

The OpenAPI document is the canonical runtime contract.

## License

MIT
