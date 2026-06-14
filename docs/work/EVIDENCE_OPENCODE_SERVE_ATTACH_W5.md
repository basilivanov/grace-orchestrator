# W5: Warm OpenCode Server + --attach Runtime Mode

## Status

Complete. All acceptance criteria met.

## Acceptance checklist

| # | Criterion | Status |
|---|-----------|--------|
| 1 | OpenCodeServerManager exists | ✅ |
| 2 | `opencode_runtime_mode=direct` keeps W4 behavior | ✅ |
| 3 | `opencode_runtime_mode=serve_attach` starts/reuses server | ✅ |
| 4 | Server command uses `opencode serve --hostname 127.0.0.1 --port <port>` | ✅ |
| 5 | Server does not bind 0.0.0.0 by default | ✅ (127.0.0.1 default) |
| 6 | Stale PID is cleaned | ✅ |
| 7 | Healthy existing server is reused | ✅ |
| 8 | Unhealthy server is restarted when configured | ✅ |
| 9 | Attach command includes `--attach <url>` | ✅ |
| 10 | Attach command includes explicit `--dir` | ✅ |
| 11 | Attach command includes explicit `--agent` | ✅ |
| 12 | Attach command includes explicit `--model` | ✅ |
| 13 | Attach command includes `--format json` | ✅ |
| 14 | Attach command does not include `serve` | ✅ |
| 15 | W4 artifacts still exist in serve_attach mode | ✅ |
| 16 | W4 lifecycle events still exist in serve_attach mode | ✅ |
| 17 | Server lifecycle events are emitted | ✅ (via backend) |
| 18 | Server artifacts are persisted through RuntimeArtifactStore | ✅ |
| 19 | Server artifacts are redacted | ✅ |
| 20 | Packet run timeout does not kill warm server | ✅ (timeout kills child only) |
| 21 | Direct mode tests still pass | ✅ |
| 22 | New W5 tests pass | ✅ (23 tests) |
| 23 | Existing W1-W4 tests pass | ✅ (122 tests) |
| 24 | No admin UI introduced | ✅ |

## New files

| File | Purpose |
|------|---------|
| `opencode_server_state.py` | `OpenCodeServerStatus` enum, `OpenCodeServerState`, `OpenCodeServerHealth` |
| `opencode_server_manager.py` | Start/stop/restart/healthcheck/ensure_running lifecycle |
| `opencode_attach_command_builder.py` | Builds `opencode run --attach <url> --dir --agent --model --format json` |
| `test_opencode_attach_command_builder.py` | 6 tests |
| `test_opencode_server_manager.py` | 13 tests |
| `test_opencode_attach_runtime.py` | 4 tests |

## Config

New settings:

- `opencode_runtime_mode: str = "direct"` — `direct` or `serve_attach`
- `opencode_server_host: str = "127.0.0.1"`
- `opencode_server_port: int = 4096`
- `opencode_server_url: str = ""`
- `opencode_server_start_timeout_seconds: int = 20`
- `opencode_server_health_timeout_seconds: int = 5`
- `opencode_server_restart_on_unhealthy: bool = True`
- `opencode_server_log_path: str = ".grace/opencode-server.log"`
- `opencode_server_pid_path: str = ".grace/opencode-server.pid"`

New failure codes:

- `AGENT_OPENCODE_SERVER_NOT_RUNNING`
- `AGENT_OPENCODE_SERVER_UNHEALTHY`
- `AGENT_OPENCODE_SERVER_START_FAILED`
- `AGENT_OPENCODE_SERVER_TIMEOUT`
- `AGENT_OPENCODE_ATTACH_FAILED`

## Architecture

W5 integrates into `OpenCodeRuntimeAdapter`:

```
run(contract, prompt):
  if mode == "serve_attach":
    server_manager.ensure_running()
    command = attach_command_builder.build(contract, server_state.url)
  else:
    command = command_builder.build(contract)
  # process execution (same as W4)
```

Server lifecycle: `ensure_running` → healthcheck → (clean stale PID | start | reuse).
Healthcheck uses TCP connect to `host:port` with configurable timeout.
