# Runbook: Debug a Packet

## Find the packet by trace API

```bash
curl http://localhost:8042/api/trace/packets/{packet_id}
```

## Inspect run timeline

The trace response includes `runs[]` with status, executor_id, duration, and
`timeline[]` with event sequence.

## Inspect artifacts

```bash
# List artifacts
curl http://localhost:8042/api/packets/{packet_id}/runs/{run_id}/artifacts

# Read stdout
curl "http://localhost:8042/api/packets/{packet_id}/runs/{run_id}/artifacts/file?path=agent_stdout.log"

# Read stderr (tail)
curl "http://localhost:8042/api/packets/{packet_id}/runs/{run_id}/artifacts/file?path=agent_stderr.log&tail=50"
```

## Common failures

| Symptom | Likely cause |
| --- | --- |
| `domain_status=timeout` | Agent took too long; increase `timeout_seconds` in profile |
| `no_changes_produced` | Agent ran but did not modify any allowed files |
| `merge 409` | Packet already merged or state transition conflict |
| `executor_id not found` | Profile missing from `agent_profiles.yaml` |
| `Command not found: opencode` | CLI tool not installed or not on PATH |

## Rerun a packet

Packets can be retried through the recovery pipeline or by creating a new
packet with the same spec. Manual retry is not exposed via API for safety.
