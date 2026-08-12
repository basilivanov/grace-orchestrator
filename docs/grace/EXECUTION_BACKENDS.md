# Execution Backends

Date: 2026-08-12

GRACE Control Plane supports three execution backends. The choice is driven
by `grace_control.config.settings.execution_backend` and read by
`grace_control.agent.select_backend()`.

| Backend | Module | Use case |
| --- | --- | --- |
| `cli` | `grace_control.agent.universal_cli_backend.UniversalCliAgentBackend` | Default subprocess runtime driven by declarative profiles |
| `mock` | `grace_control.agent.mock_backend.MockBackend` | In-process tests, CI, and local smoke runs |
| `api` | `grace_control.agent.api_backend.ApiAgentBackend` | HTTP provider adapter; mock provider is available |

The old legacy backend was removed in W8 and now raises `ValueError`.
OpenCode is not a supported runtime backend. The control CLI is also removed;
the `cli` backend is an internal generic subprocess adapter driven by the
declarative mini-swe-compatible profiles, not a public operator surface.

## Backend selection

```python
from grace_control.agent import select_backend

backend = select_backend()
result = await backend.run(execution_request)
```

The factory accepts an explicit backend name for tests. With no name it reads
the `execution_backend` setting. The packet executor selects this generic
backend when no backend is injected.

## Universal CLI backend

`UniversalCliAgentBackend` delegates command execution to
`AgentRunService`. It does not hardcode tool names; it loads the selected
profile from `src/grace_control/config/agent_profiles.yaml`.

The execution stack is:

- `AgentRunService` renders commands, handles input, resume flags, and results.
- `CommandTemplateRenderer` expands the supported packet placeholders.
- `AgentEnvBuilder` expands profile environment values and redacts previews.
- `ProcessSupervisor` runs a bounded subprocess group.
- `AgentArtifactCollector` persists stdout/stderr evidence.

### Profile example

```yaml
agents:
  coder-mini-swe:
    backend: cli
    command:
      - "{python_executable}"
      - -m
      - grace_control.runtime.mini_swe_runner
      - --role
      - coder
      - --task-file
      - "{packet_path}"
      - --worktree
      - "{worktree_path}"
    model: "openai/gemini-3.6-flash-high"
    effort: medium
    cwd: "{worktree_path}"
    timeout_seconds: 600
    input:
      mode: file
```

## Worktree and API behavior

Before execution, `PacketExecutionAdapter._call_executor` validates that
the isolated worktree exists and is usable. The API route
`/api/agents/run` resolves an executor id from the live profile set and
returns command preview, status, output, and artifact paths.

## Profile sections

- `agents:` contains active declarative profiles used by the generic backend.
- `codex:` retains the unrelated agy compatibility entry and role policy.
- `verification:` contains acceptance command profiles.

## GraceLint

| Rule | Check |
| --- | --- |
| `GRC109` | Reject hardcoded CLI tool names in runtime execution code |
| `GRC100` | Restrict direct environment reads to approved boundaries |
| `GRC101` | Restrict subprocess usage to approved boundaries |

## Related tests

- `tests/grace_control/agent/test_select_backend.py`
- `tests/grace_control/api/test_agents_api.py`
- `tests/grace_control/runtime/test_agent_runtime_selftest.py`
