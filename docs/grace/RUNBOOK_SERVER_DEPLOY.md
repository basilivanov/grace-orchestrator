# Runbook: Server Deployment

## Environment variables

| Variable | Default | Description |
| --- | --- | --- |
| `GRACE_DB_URL` | `sqlite:///./grace.db` | Database connection string |
| `GRACE_STATE_ROOT` | `.grace/state` | Runtime state directory |
| `GRACE_WORKTREE_ROOT` | `.grace/worktrees` | Worktree directory |
| `GRACE_EXECUTION_BACKEND` | `cli` | Execution backend (`cli`, `mock`, `api`) |
| `GRACE_API_AUTH_ENABLED` | `false` | Enable Bearer token auth |
| `GRACE_API_TOKEN` | `""` | API auth token |
| `GRACE_API_HOST` | `127.0.0.1` | Bind address |
| `GRACE_API_PORT` | `8042` | Port |

## API Auth

To enable auth:

```bash
export GRACE_API_AUTH_ENABLED=true
export GRACE_API_TOKEN=your-secret-token
```

Then all API requests (except `/health`) require:

```http
Authorization: Bearer your-secret-token
```

## Process manager (systemd example)

```ini
[Unit]
Description=GRACE Control Plane
After=network.target

[Service]
Type=simple
User=grace
WorkingDirectory=/opt/grace
Environment=GRACE_DB_URL=sqlite:///opt/grace/grace.db
Environment=GRACE_API_AUTH_ENABLED=true
Environment=GRACE_API_TOKEN=...
ExecStart=/opt/grace/.venv/bin/uvicorn grace_control.api.main:app --host 0.0.0.0 --port 8042
Restart=on-failure

[Install]
WantedBy=multi-user.target
```

## Logs

All components emit structured JSONL to stderr:

```json
{"ts": "...", "level": "INFO", "component": "adapter", "msg": "adapter_execute_start", "ctx": {"packet_id": "..."}}
```

View with:

```bash
journalctl -u grace-control -f
# or redirect stderr to a file
```

## Database backup

```bash
# SQLite
cp grace.db grace.db.backup-$(date +%Y%m%d)
```
