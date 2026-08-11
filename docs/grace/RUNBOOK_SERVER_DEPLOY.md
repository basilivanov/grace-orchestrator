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

## Admin Control Center v3

The Hub is a read/control facade over independent project runtimes. It does
not switch a process-global database or filesystem root per request and must
not open another project's SQLite file directly. Run one project API per
project, with a distinct Unix user, root, database, state directory,
worktree directory and target Git repository. The Hub process only needs the
registry and network or Unix-socket access to those APIs.

### Register projects

Set `GRACE_PROJECTS_CONFIG` (aliases `GRACE_PROJECT_REGISTRY` and
`GRACE_PROJECTS_FILE` are also accepted) to a YAML file such as:

```yaml
projects:
  - key: alpha
    name: Alpha
    enabled: true
    unix_user: grace-alpha
    project_root: /srv/grace/alpha
    api_url: http://127.0.0.1:8101
    description: Alpha production runtime
    tags: [prod, payments]
  - key: beta
    name: Beta
    enabled: true
    unix_user: grace-beta
    project_root: /srv/grace/beta
    api_socket: /run/grace/beta.sock
    tags: [prod]
```

Each entry has a unique safe `key`, an absolute `project_root`, and exactly
one of `api_url` or `api_socket`. Keep the registry readable only by the Hub
operator; never put transport tokens or passwords in browser URLs or rendered
HTML. A disabled project remains visible with an explicit disabled state and
is not queried.

Run project APIs under separate systemd units/users. A project unit should set
its own `GRACE_DB_URL`, `GRACE_PROJECT_ROOT`, `GRACE_TARGET_REPO_ROOT`,
`GRACE_STATE_ROOT`, `GRACE_WORKTREE_ROOT`, `GRACE_RUNTIME_ARTIFACTS_ROOT` and
`GRACE_PLANNING_LOGS_ROOT`. The Hub unit sets only its registry and Hub API
bind/auth settings. Unix-socket permissions should allow the Hub user to
connect while denying other project users.

### Operator URLs and behavior

With the Hub listening on `http://127.0.0.1:8042`:

```text
/admin/projects                         all project cards and health
/admin/p/<key>                          project Feature → Wave → Packet tree
/admin/p/<key>/packet/<packet-id>       packet detail and tabs
/admin/events, /admin/logs, /admin/search cross-project read surfaces
/admin/p/<key>/api                      discovered OpenAPI GET explorer
/admin/p/<key>/system                   diagnostics and capabilities
```

Every project switch is represented in the URL. Offline, timeout, malformed
and identity-mismatch results remain on the selected card as unavailable or
degraded data; healthy projects are not replaced with another project's stale
data. Event payloads, raw result JSON, StageRun data, session availability,
bounded log tails, evidence/artifacts, leases, stale-base metadata and Git
diffs are read through the selected project API.

The default UI is read-only. Supported controls require server-side
capability/state checks, explicit confirmation and an audit event in the
selected project. A failed or timed-out mutation is reported as unknown and
is never automatically retried. The API Explorer discovers paths from the
selected project's `/openapi.json`; only discovered GETs execute in read
mode. Mutations require the separate control mode, confirmation and the
server-side action policy; arbitrary URLs, shell commands and arbitrary file
paths are not accepted.

### Filesystem, Git and maintenance safety

Filesystem reads use named roots (`state`, `worktrees`, `runs`, `logs`) and
relative POSIX paths only. Parent traversal, absolute paths, symlink escapes,
`.env`, credentials/private-key names and unbounded text, tail or binary
previews are rejected or capped. Project-local system logs are selected from
the configured logs root; the Hub must not read a shared `/tmp` log glob.

Git reads use the server-configured repository and validated refs/paths. Use
the project Git and packet tabs for tracked files, worktrees, base/integration
SHAs, diff/stat and bounded large diffs. Maintenance cleanup is project-local
and must not remove a live or uncertain worktree; investigate lease and
heartbeat state before any manual cleanup.

### Troubleshooting

1. Check the Hub `/admin/projects` card and `/api/admin-hub/projects` response
   for the project key, transport error class and last attempt time.
2. From the project unit, verify readiness, database migrations and the
   project identity endpoint before checking the Hub registry path/root.
3. For an identity mismatch, compare registry `key`, `name`, `project_root`
   with the runtime identity; do not work around it by changing a request
   parameter.
4. For missing logs/evidence, verify the project service's named root and
   permissions, then use bounded API tails/previews. Do not use SSH or a
   direct SQLite query as the normal diagnosis path.
5. For controls, verify authorization, confirmation, capability/state,
   request ID and the project-local audit event. Unknown outcomes require
   operator review rather than a second blind submission.
