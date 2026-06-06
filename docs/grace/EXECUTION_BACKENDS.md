# Execution Backends

Date: 2026-06-06 (updated: TZ_WORKTREE_ISOLATION_FIX)

GRACE Control Plane supports three execution backends. The choice is driven
by `grace_control.config.settings.execution_backend` (env:
`GRACE_EXECUTION_BACKEND`) and read by `grace_control.agent.select_backend()`.

| Backend | Module | Use case |
| --- | --- | --- |
| `cli` | `grace_control.agent.universal_cli_backend.UniversalCliAgentBackend` | **Default runtime backend.** Runs local CLI agents (`opencode`, `codex`, `agy`, etc.) by declarative profile. |
| `mock` | `grace_control.agent.mock_backend.MockBackend` | In-process, no subprocess, no LLM. Tests, CI, local smoke. |
| `api` | `grace_control.agent.api_backend.ApiAgentBackend` | HTTP provider adapter (mock provider only; real providers pending W7.1). |
| `legacy` | removed in W8 | Raises `ValueError` with migration hint. |

The packet executor (`adapters/packet_executor.PacketExecutionAdapter`)
depends only on the `ExecutionBackend` Protocol. The backend is selected
once per process — never per packet.

## How a backend is selected

```python
from grace_control.agent import select_backend
backend = select_backend()  # reads settings.execution_backend
result = await backend.run(execution_request)
```

The factory accepts an explicit `backend_name` (used by tests) or, when
empty, reads the `execution_backend` field. `BACKEND_CLI` is the default
and is aliased as `BACKEND_NEW` for back-compat with older test code.

## UniversalCliAgentBackend (strategic path)

`UniversalCliAgentBackend` is the strategic default. It does **not**
hardcode any CLI tool names (`opencode`, `codex`, `agy`, `gemini`,
`claude`). Instead, it reads agent profiles from `agent_profiles.yaml`
and renders command templates dynamically.

The implementation stack:

- `AgentRunService` — orchestrator
- `CommandTemplateRenderer` — `{model}`, `{effort}`, `{packet_id}`, `{worktree_path}`, `{packet_markdown}`, `{packet_path}`
- `AgentEnvBuilder` — `${ENV_VAR}` expansion, inherits parent `PATH`, redacts secrets
- `ProcessSupervisor` — subprocess with process group timeout kill, sets `PWD` to worktree
- `AgentArtifactCollector` — persists `agent_stdout.log` to canonical evidence dir

### Agent profile example (`agent_profiles.yaml`)

```yaml
agents:
  coder-deepseek-flash:
    backend: cli
    inject_dir: true      # inject --dir <worktree_path> after "run" for opencode
    command:
      - opencode
      - run
      - "--model"
      - "{model}"
      - "--variant"
      - "{effort}"
      - Read the task from {packet_path} and execute it.
    model: "deepseek/deepseek-v4-flash"
    effort: "medium"
    cwd: "{worktree_path}"
    timeout_seconds: 900
    input:
      mode: file
```

### `inject_dir` field

Because `opencode run` connects to a server that operates from the server's
own cwd (not the CLI's cwd), agents would write files to the project root
instead of the per-packet worktree without this flag.

When `inject_dir: true`:
- `AgentRunService` inserts `--dir <worktree_path>` immediately after the
  first `run` token in the command list.
- This works regardless of the full path to the binary (e.g. `/usr/bin/opencode`).
- For non-opencode tools (e.g. `agy`), omit `inject_dir` or set it to `false`.

Back-compat: if `inject_dir` is absent from the profile, `AgentRunService`
auto-detects by checking whether `command[0]` basename is `opencode`.

### Pre-flight worktree validation

Before handing control to the agent, `PacketExecutionAdapter._call_executor`
performs two checks:

1. **`git worktree add` must succeed** — if it fails for any reason other than
   "already exists", the packet is immediately moved to `FAILED`. The agent is
   never launched.
2. **Worktree path must exist** — even after a successful `worktree_add`, if
   the path is missing on disk (e.g. filesystem issue), the packet fails fast
   with a clear error message.

This prevents the silent bug where `cwd.mkdir()` created an empty directory
and the agent ran without any project files.

### `/api/agents/run`

```http
POST /api/agents/run
Content-Type: application/json

{
  "packet_id": "pkt_001",
  "executor_id": "coder-deepseek-flash",
  "role": "coder",
  "model": "optional override",
  "effort": "optional override",
  "worktree_path": "/path/to/worktree",
  "packet_markdown": "# ...",
  "timeout_seconds": 900
}
```

Response:

```json
{
  "accepted": false,
  "domain_status": "completed|rejected|blocked|failed|timeout",
  "executor_id": "coder-deepseek-flash",
  "command_preview": ["opencode", "run", "--dir", "/wt/...", "--model", "..."],
  "exit_code": 0,
  "stdout_path": "...",
  "stderr_path": "...",
  "stdout": "...",
  "stderr": "...",
  "worktree_path": "...",
  "branch_name": "",
  "duration_ms": 123456,
  "reason": "",
  "artifacts": []
}
```

The endpoint lives in `api/routers/agents.py` and is mounted under
`/api/agents` by `api/app_factory.py`.

## MockBackend

Returns success in ~0ms and writes a single `.mock_run.log` marker to
the worktree. Used by:

- the existing test suite (no API keys required)
- CI smoke runs
- local development when the user has no CLI agent installed

## ApiAgentBackend

Retained as an optional HTTP provider adapter. Currently only the `mock`
provider is implemented; real providers (OpenAI, Anthropic, DeepSeek,
Gemini) are pending W7.1. Not the strategic default.

## LegacyPrefectBackend (removed)

Removed in W8. `select_backend("legacy")` raises a clear `ValueError`.
The historical code is archived at `docs/archived/legacy_prefect_grace/`.

## Agent profiles

`config/agent_profiles.yaml` contains two profile sections:

1. **`agents:`** — W7 declarative profiles for `UniversalCliAgentBackend`.
   Each entry declares `backend: cli`, `inject_dir`, a `command` list,
   `model`, `effort`, `cwd`, `timeout_seconds`, `env`, and `input` mode.
2. **`codex:`** — legacy profiles for the old `executor_selector`.
   Retained for back-compat; new profiles should go under `agents:`.

## GraceLint rules

| Rule | Check |
| --- | --- |
| `GRC109` | No hardcoded `opencode`/`codex`/`agy`/`gemini`/`claude` in runtime execution code |
| `GRC100` | No `os.environ` outside config/W7 boundary |
| `GRC101` | No `subprocess` outside W7 boundary |

## Tests

Test files covering the execution backends:

- `tests/grace_control/agent/test_select_backend.py` — `select_backend()` factory
- `tests/grace_control/agent/test_agent_gateway_service.py` — ApiAgentBackend gateway
- `tests/grace_control/api/test_agents_api.py` — OpenAPI + `/api/agents/run`

| Backend | Module | Use case |
| --- | --- | --- |
| `cli` | `grace_control.agent.universal_cli_backend.UniversalCliAgentBackend` | **Default runtime backend.** Runs local CLI agents (`opencode`, `codex`, `agy`, etc.) by declarative profile. |
| `mock` | `grace_control.agent.mock_backend.MockBackend` | In-process, no subprocess, no LLM. Tests, CI, local smoke. |
| `api` | `grace_control.agent.api_backend.ApiAgentBackend` | HTTP provider adapter (mock provider only; real providers pending W7.1). |
| `legacy` | removed in W8 | Raises `ValueError` with migration hint. |

The packet executor (`adapters/packet_executor.PacketExecutionAdapter`)
depends only on the `ExecutionBackend` Protocol. The backend is selected
once per process — never per packet.

## How a backend is selected

```python
from grace_control.agent import select_backend
backend = select_backend()  # reads settings.execution_backend
result = await backend.run(execution_request)
```

The factory accepts an explicit `backend_name` (used by tests) or, when
empty, reads the `execution_backend` field. `BACKEND_CLI` is the default
and is aliased as `BACKEND_NEW` for back-compat with older test code.

## UniversalCliAgentBackend (strategic path)

`UniversalCliAgentBackend` is the strategic default. It does **not**
hardcode any CLI tool names (`opencode`, `codex`, `agy`, `gemini`,
`claude`). Instead, it reads agent profiles from `agent_profiles.yaml`
and renders command templates dynamically.

The implementation stack:

- `AgentRunService` — orchestrator
- `CommandTemplateRenderer` — `{model}`, `{effort}`, `{packet_id}`, `{worktree_path}`, `{packet_markdown}`
- `AgentEnvBuilder` — `${ENV_VAR}` expansion, inherits parent `PATH`, redacts secrets
- `ProcessSupervisor` — subprocess with process group timeout kill
- `AgentArtifactCollector` — persists `agent_stdout.log` to canonical evidence dir

### Agent profile example (`agent_profiles.yaml`)

```yaml
agents:
  coder_opencode:
    backend: cli
    command:
      - opencode
      - run
      - "--model"
      - "{model}"
      - "--effort"
      - "{effort}"
    model: "codex-5.1"
    effort: "high"
    cwd: "{worktree_path}"
    timeout_seconds: 900
    env:
      OPENAI_API_KEY: "${OPENAI_API_KEY}"
    input:
      mode: stdin
      template: "{packet_markdown}"
```

### `/api/agents/run`

```http
POST /api/agents/run
Content-Type: application/json

{
  "packet_id": "pkt_001",
  "executor_id": "coder_opencode",
  "role": "coder",
  "model": "optional override",
  "effort": "optional override",
  "worktree_path": "/path/to/worktree",
  "packet_markdown": "# ...",
  "timeout_seconds": 900
}
```

Response:

```json
{
  "accepted": false,
  "domain_status": "completed|rejected|blocked|failed|timeout",
  "executor_id": "coder_opencode",
  "command_preview": ["opencode", "run", "--model", "codex-5.1", "--effort", "high"],
  "exit_code": 0,
  "stdout_path": "...",
  "stderr_path": "...",
  "stdout": "...",
  "stderr": "...",
  "worktree_path": "...",
  "branch_name": "",
  "duration_ms": 123456,
  "reason": "",
  "artifacts": []
}
```

The endpoint lives in `api/routers/agents.py` and is mounted under
`/api/agents` by `api/app_factory.py`.

## MockBackend

Returns success in ~0ms and writes a single `.mock_run.log` marker to
the worktree. Used by:

- the existing test suite (no API keys required)
- CI smoke runs
- local development when the user has no CLI agent installed

## ApiAgentBackend

Retained as an optional HTTP provider adapter. Currently only the `mock`
provider is implemented; real providers (OpenAI, Anthropic, DeepSeek,
Gemini) are pending W7.1. Not the strategic default.

## LegacyPrefectBackend (removed)

Removed in W8. `select_backend("legacy")` raises a clear `ValueError`.
The historical code is archived at `docs/archived/legacy_prefect_grace/`.

## Agent profiles

`config/agent_profiles.yaml` contains two profile sections:

1. **`agents:`** — W7 declarative profiles for `UniversalCliAgentBackend`.
   Each entry declares `backend: cli`, a `command` list, `model`, `effort`,
   `cwd`, `timeout_seconds`, `env`, and `input` mode.
2. **`codex:`** — legacy profiles for the old `executor_selector`.
   Retained for back-compat; new profiles should go under `agents:`.

## GraceLint rules

| Rule | Check |
| --- | --- |
| `GRC109` | No hardcoded `opencode`/`codex`/`agy`/`gemini`/`claude` in runtime execution code |
| `GRC100` | No `os.environ` outside config/W7 boundary |
| `GRC101` | No `subprocess` outside W7 boundary |

## Tests

Test files covering the execution backends:

- `tests/grace_control/agent/test_select_backend.py` — `select_backend()` factory
- `tests/grace_control/agent/test_agent_gateway_service.py` — ApiAgentBackend gateway
- `tests/grace_control/api/test_agents_api.py` — OpenAPI + `/api/agents/run`

