# Runbook: Agent Profiles

## Profile schema

Profiles live under `agents:` in `config/agent_profiles.yaml`.

```yaml
agents:
  <executor_id>:
    backend: cli                    # required, must be "cli"
    command:                         # required, list of strings
      - opencode
      - run
      - "--model"
      - "{model}"
      - "--effort"
      - "{effort}"
    extras:                          # optional, env-driven flags appended after `command`
      - "--attach"                   # tokens with ${VAR} are dropped when VAR is unset
      - "${OPENCODE_SERVER_URL}"     # so the profile works in both attach and standalone mode
      - "-p"
      - "${OPENCODE_SERVER_PASSWORD}"
    model: "codex-5.1"              # default model
    effort: "high"                  # default effort
    cwd: "{worktree_path}"          # cwd template
    timeout_seconds: 900
    env:                            # optional env overrides
      OPENAI_API_KEY: "${OPENAI_API_KEY}"
    input:
      mode: stdin|file|none          # default: none
      template: "{packet_markdown}"  # for stdin mode
```

## Extras (env-driven flags)

`extras` is an optional list of CLI arguments appended after the rendered
`command`. Each token is scanned for `${VAR}` placeholders; if the env var
is unset (or resolves to empty) the entire token is dropped. This makes a
profile gracefully adapt between:

- **With `opencode web` running** — orchestrator sets
  `OPENCODE_SERVER_URL=http://127.0.0.1:4096` and `OPENCODE_SERVER_PASSWORD`
  in the env, and the extras inject `--attach` + `-p <pw>` automatically.
- **Standalone** — neither env var is set, extras are silently skipped, the
  profile runs the plain `command` (the historical behavior).

Validation in `AgentProfile._validate` rejects string `extras` and
non-string tokens.

## opencode example

See `coder_opencode` profile in `agent_profiles.yaml`.

## Attaching to a running `opencode web`

opencode 1.15.x's standalone `opencode run` returns `Session not found`
when a separate `opencode web` server is running on the same machine —
the session is owned by the web server, not the standalone CLI. To make
agent profiles work in that setup, set the two env vars before launching
the orchestrator (or worker):

```bash
export OPENCODE_SERVER_URL=http://127.0.0.1:4096
export OPENCODE_SERVER_PASSWORD=...      # the password used by `opencode web`
```

The `opencode`, `coder_opencode`, `coder-deepseek-flash`, `coder-sonnet`,
and `architect-premium` profiles already declare the matching `extras:`,
so no profile edit is needed.

## Validation and dry-run

```bash
# List all profiles
curl http://localhost:8042/api/agents/profiles

# Get specific profile
curl http://localhost:8042/api/agents/profiles/coder_opencode

# Validate (checks command shape, timeouts, input mode)
curl -X POST http://localhost:8042/api/agents/profiles/coder_opencode/validate

# Validate with executable check
curl -X POST http://localhost:8042/api/agents/profiles/coder_opencode/validate \
  -H "Content-Type: application/json" \
  -d '{"check_executable": true}'

# Dry-run (renders command/env/cwd without spawning)
curl -X POST http://localhost:8042/api/agents/profiles/coder_opencode/dry-run \
  -H "Content-Type: application/json" \
  -d '{"worktree_path": "/tmp/test-wt"}'
```

## Common failures

| Symptom | Likely cause |
| --- | --- |
| `command must be a list` | String command found; use `[opencode, run, ...]` |
| `executable not found` | CLI tool not installed or not on `$PATH` |
| `timeout_seconds must be > 0` | Missing or zero timeout |
| Secrets in env preview | Redacted automatically for `API_KEY`, `TOKEN`, `SECRET`, `PASSWORD`, `CREDENTIAL` |
