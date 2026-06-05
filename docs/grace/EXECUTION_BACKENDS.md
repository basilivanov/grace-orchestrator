# Execution Backends

GRACE Control Plane supports three execution backends. The choice is driven
by `grace_control.config.settings.execution_backend` (env:
`GRACE_EXECUTION_BACKEND`) and read by `grace_control.agent.select_backend()`.

| Backend | Module | Use case |
| --- | --- | --- |
| `legacy` | `grace_control.agent.legacy_backend.LegacyPrefectBackend` | Wraps `prefect_grace.platform.e2e_packet_runner`. **Deprecated — removed in W8.** |
| `api` | `grace_control.agent.api_backend.ApiAgentBackend` | Provider-agnostic, delegates to `AgentGatewayService`. The strategic path. |
| `mock` | `grace_control.agent.mock_backend.MockBackend` | In-process, no subprocess, no LLM. Tests, CI, local smoke. |

The packet executor (`adapters.packet_executor.PacketExecutionAdapter`)
depends only on the `ExecutionBackend` Protocol. The backend is selected
once per process — never per packet.

## How a backend is selected

```python
from grace_control.agent import select_backend
backend = select_backend()  # reads settings.execution_backend
result = await backend.run(execution_request)
```

The factory accepts an explicit `backend_name` (used by tests) or, when
empty, reads the `execution_backend` field. `BACKEND_NEW` is retained as
an alias for `BACKEND_API` for back-compat with older test code.

## ApiAgentBackend

`ApiAgentBackend` is the strategic path. It does **not** import any
provider SDK directly. Instead, it delegates to
`services.agent_gateway_service.AgentGatewayService`, which owns:

- provider selection
- model selection
- prompt / request construction
- timeout policy
- retry policy
- response normalization
- artifact / log persistence

The MVP supports `provider="mock"` end-to-end. Real provider adapters for
`openai` / `anthropic` / `deepseek` / `gemini` / `cliproxy` are out of
scope for W7 but the architecture is in place — adding a new provider
means writing a new branch in
`services/agent_gateway_service._call_provider`.

### `/api/agents/run`

```http
POST /api/agents/run
Content-Type: application/json

{
  "packet_id": "pkt_001",
  "role": "coder",
  "model": "gpt-4o",
  "provider": "openai|anthropic|deepseek|gemini|cliproxy|mock",
  "worktree_path": "/path/to/worktree",
  "packet_markdown": "# ...",
  "timeout_seconds": 600,
  "max_retries": 0
}
```

Response:

```json
{
  "accepted": false,
  "domain_status": "rejected|accepted|blocked|failed",
  "stdout": "...",
  "stderr": "...",
  "messages": [],
  "changed_files": [],
  "reason": "...",
  "duration_ms": 123,
  "artifacts": [],
  "attempts": 0
}
```

The endpoint lives in `api/routers/agents.py` and is mounted under
`/api/agents` by `api/app_factory.py`.

## MockBackend

Returns success in ~0ms and writes a single `.mock_run.log` marker to
the worktree. Used by:

- the existing test suite (no API keys required)
- CI smoke runs
- local development when the user has no LLM credentials

## LegacyPrefectBackend

Wraps the historical `prefect_grace` E2E runner. **W8 will remove it.**
It is the only file in the new control plane allowed to import
`prefect_grace`. Until W8 lands, `execution_backend=legacy` remains the
default for backward compatibility with existing test fixtures.

## Agent profiles

`config/agent_profiles.yaml` is no longer legacy-specific. A top-level
`default_provider: openai` field is the canonical default; per-executor
`metadata.provider` may override. The `codex:` section retains the
existing `command:` / `kind:` fields for backward compat with the legacy
backend; ApiAgentBackend does not read them.

## Tests

W7 ships with two test files:

- `tests/grace_control/agent/test_select_backend.py` — `select_backend`
  factory coverage (`legacy` / `api` / `mock` / unknown / settings-driven).
- `tests/grace_control/agent/test_agent_gateway_service.py` — provider
  hook, retry, timeout, artifact persistence.
- `tests/grace_control/api/test_agents_api.py` — OpenAPI presence + happy
  path + 400 on unknown provider + log persistence.
