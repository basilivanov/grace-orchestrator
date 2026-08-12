# Runbook: Debug a Packet

## Find the packet by trace API

```bash
curl http://localhost:8042/api/trace/packets/{packet_id}
```

## Inspect run timeline

The trace response includes `runs[]` with status, executor_id, duration, and
`timeline[]` with the event sequence.

## Inspect artifacts

```bash
curl http://localhost:8042/api/packets/{packet_id}/runs/{run_id}/artifacts
curl "http://localhost:8042/api/packets/{packet_id}/runs/{run_id}/artifacts/file?path=agent_stdout.log"
curl "http://localhost:8042/api/packets/{packet_id}/runs/{run_id}/artifacts/file?path=agent_stderr.log&tail=50"
```

## Common failures

| Symptom | Likely cause |
| --- | --- |
| `domain_status=timeout` | Increase `timeout_seconds` in the selected profile |
| `no_changes_produced` | The agent did not modify an allowed path |
| `merge 409` | The packet was already merged or state transition conflicted |
| `executor_id not found` | The profile is missing from `agent_profiles.yaml` |
| `command not found` | The selected CLI tool is not installed or not on `PATH` |

## Rerun a packet

Packets can be retried through the recovery pipeline or by creating a new
packet with the same spec. Manual retry is not exposed via API for safety.
