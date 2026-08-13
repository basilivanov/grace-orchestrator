# Architecture

## Layers

```
HTTP/OpenAPI (FastAPI) → Routers → Services → DB / AgentBackend / Git
                    ↓
              AcceptancePipeline (T0/T1/T2)
                    ↓
              EvidenceVerifier / ReviewerGate
                    ↓
              MergeService → PacketService
```

## Key components

| Layer | Location | Role |
| --- | --- | --- |
| Routers | `api/routers/*.py` | HTTP binding, no DB aggregation |
| App factory | `api/app_factory.py` | `create_app()` builds FastAPI |
| Lifespan | `api/lifespan.py` | DB init, lease/wave_gate/feature_gate loops |
| Services | `services/*.py` | Business logic, own SQL |
| Execution backend | `agent/api_backend.py` | Provider-agnostic agent runner |
| Worktree helpers | `services/worktree_inspector.py` | Git read-only helpers |
| Agent commit | `services/agent_commit_service.py` | `git add -A` + `git commit` |

The HTTP/OpenAPI surface is the only public runtime/operator surface. The
control CLI and OpenCode runtime are removed. The internal mini-swe/generic
CLI/subprocess backend remains available only to execute packets selected by
the services layer.

Lifecycle and admin routes use explicit service composition and dependency
injection. Admin cross-project, Control Center and aggregation services are
constructed from explicit collaborators rather than reverse facade/private
setter coupling. Typed admin read models are the boundary returned by those
services; routers do not reach through a facade or perform their own
aggregation.

## CI ownership

The root `Makefile` is the single source of truth for `test`, `lint`,
`docs-check`, and `hygiene`; `make ci` composes those targets. The workflow
only installs dependencies and delegates to Make. `make lint` evaluates the
complete supported Python scope (`src/grace_control`, `tests`, and `scripts`)
with both Ruff and GraceLint. The baseline-aware gate keeps every diagnostic
visible and fails when the reviewed baseline changes; it is not a path
exclusion or a linter suppression. Tests requiring a running API, browser, or
external provider are marked `external`/`live` and are not silently presented
as deterministic CI coverage.

## Execution backends

`select_backend()` supports the following current backends:
- `cli` → `UniversalCliAgentBackend` (internal generic subprocess runtime for
  packet execution, including mini-swe-compatible declarative profiles)
- `api` → `ApiAgentBackend` (strategic, delegates to `AgentGatewayService`)
- `mock` → `MockBackend` (in-process, no subprocess, for tests/CI)

`legacy` was removed in W8 and is explicitly rejected; it is not a selectable
supported backend. The internal `cli` execution backend must not be confused
with the removed public/operator control CLI.

## File budgets

- `api/main.py` < 150 lines (currently 45)
- `adapters/packet_executor.py` < 300 lines (currently ~700, target for follow-up)
