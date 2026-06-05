# Architecture

## Layers

```
HTTP (FastAPI) → Routers → Services → DB / AgentBackend / Git
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

## Execution backends

`select_backend()` returns one of:
- `api` → `ApiAgentBackend` (strategic, delegates to `AgentGatewayService`)
- `mock` → `MockBackend` (in-process, no subprocess, for tests/CI)
- `legacy` → removed in W8

## File budgets

- `api/main.py` < 150 lines (currently 45)
- `adapters/packet_executor.py` < 300 lines (currently ~700, target for follow-up)
