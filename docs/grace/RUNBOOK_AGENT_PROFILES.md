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

## opencode example

See `coder_opencode` profile in `agent_profiles.yaml`.

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
