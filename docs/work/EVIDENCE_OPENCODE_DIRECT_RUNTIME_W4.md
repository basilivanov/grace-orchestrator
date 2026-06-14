# W4: OpenCode Direct Runtime Adapter

## Status

Complete. All acceptance criteria met.

## Acceptance checklist

| # | Criterion | Status |
|---|-----------|--------|
| 1 | AgentExecutionAdapter protocol exists | ✅ |
| 2 | OpenCodeRuntimeAdapter exists | ✅ |
| 3 | OpenCodeCommandBuilder exists | ✅ |
| 4 | Command has explicit --dir | ✅ |
| 5 | Command has explicit --agent | ✅ |
| 6 | Command has explicit --model | ✅ |
| 7 | Command has --format json | ✅ |
| 8 | Command does not use --attach | ✅ |
| 9 | Subprocess cwd equals runtime contract worktree_root | ✅ |
| 10 | Prompt is delivered explicitly via stdin | ✅ |
| 11 | stdout/stderr are persisted as artifacts | ✅ |
| 12 | raw OpenCode JSON events are persisted as JSONL | ✅ |
| 13 | adapter_result.json is persisted | ✅ |
| 14 | JSON events are parsed into raw_events | ✅ |
| 15 | No events/no stdout becomes AGENT_NO_EVENT_OUTPUT | ✅ |
| 16 | Timeout becomes AGENT_COMMAND_TIMEOUT | ✅ |
| 17 | Auth/model/tool-block failures classified distinctly | ✅ |
| 18 | PacketExecutionAdapter uses OpenCode adapter when enabled | ✅ |
| 19 | Legacy backend remains available when disabled | ✅ |
| 20 | Existing W1/W2/W3 tests pass | ✅ (71 tests) |
| 21 | New W4 tests pass | ✅ (31 tests) |
| 22 | No warm OpenCode server manager introduced | ✅ |

## Files

| File | Purpose |
|------|---------|
| `src/grace_control/runtime/agent_execution_adapter.py` | AgentExecutionAdapter protocol + result model |
| `src/grace_control/runtime/opencode_command_builder.py` | Builds `opencode run --dir --agent --model --format json` |
| `src/grace_control/runtime/opencode_event_collector.py` | Line-by-line JSON event parser from stdout |
| `src/grace_control/runtime/opencode_failure_classifier.py` | Classifies failures distinctly |
| `src/grace_control/runtime/opencode_runtime_adapter.py` | Adapter tying builder/collector/classifier, runs subprocess, persists artifacts |
| `tests/grace_control/runtime/test_opencode_command_builder.py` | 4 tests |
| `tests/grace_control/runtime/test_opencode_event_collector.py` | 8 tests |
| `tests/grace_control/runtime/test_opencode_runtime_adapter.py` | 19 tests |
| `tests/grace_control/adapters/test_packet_executor_observability.py` | 2 integration tests |

## Config

New settings added to `GraceSettings`:

- `agent_runtime_use_opencode_adapter: bool = False`
- `opencode_binary: str = "opencode"`
- `opencode_direct_timeout_seconds: int = 1800`
- `opencode_process_kill_grace_seconds: int = 5`
- `opencode_json_events_required: bool = True`
- `opencode_capture_raw_events: bool = True`

## Events

New packet events emitted by `OpenCodeRuntimeAdapter.run_with_artifacts`:

- `packet.opencode_command_built` (command.txt artifact)
- `packet.opencode_process_started`
- `packet.opencode_event_received`
- `packet.opencode_stdout_captured` (agent_stdout.txt artifact)
- `packet.opencode_stderr_captured` (agent_stderr.txt artifact)
- `packet.opencode_process_completed`
- `packet.opencode_process_failed`
- `packet.opencode_adapter_result_mapped` (adapter_result.json artifact)
