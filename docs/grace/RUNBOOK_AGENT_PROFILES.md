# Runbook: Agent Profiles

## Profile schema

Profiles live under `agents:` in `config/agent_profiles.yaml`. The live
repository ships mini-swe profiles for architect, coder, reviewer, and
verifier roles, plus the supported agy coder profile.

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
    effort: "medium"
    cwd: "{worktree_path}"
    timeout_seconds: 600
    input:
      mode: file
```

Required fields:

- `command` is a list of strings.
- `cwd` resolves inside the packet worktree.
- coder profiles use explicit `input.mode` of `file` or `stdin`.
- `timeout_seconds` bounds the subprocess.
- `extras` is optional and is rendered against the final subprocess
  environment.

## Validation and dry-run

```bash
# List all profiles
curl http://localhost:8042/api/agents/profiles

# Inspect one profile
curl http://localhost:8042/api/agents/profiles/coder-mini-swe

# Validate command shape and timeout
curl -X POST http://localhost:8042/api/agents/profiles/coder-mini-swe/validate

# Render without spawning
curl -X POST http://localhost:8042/api/agents/profiles/coder-mini-swe/dry-run \
  -H "Content-Type: application/json" \
  -d '{"worktree_path": "/tmp/test-wt"}'
```

## Common failures

| Symptom | Likely cause |
| --- | --- |
| `command must be a list` | A string command was configured; use a YAML list |
| `executable not found` | The selected tool is not on `$PATH` |
| `timeout_seconds must be > 0` | The profile is missing a positive timeout |
| Secrets in env preview | Values are redacted for common secret-key names |
