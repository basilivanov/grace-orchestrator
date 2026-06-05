# GRACE Project Configuration

Date: 2026-06-05
Status: shipped (W3 of `source/codex/tz-api-first-cleanup-waves-w0-w11.md`)

## Overview

GRACE has a three-layer configuration model, with strict precedence:

```text
env (GRACE_*)   >   .grace/config.yaml   >   safe local defaults
```

The three layers and their owners:

| layer | location | owner |
|-------|----------|-------|
| env vars | `GRACE_*` shell env | deployment |
| project config | `<project>/.grace/config.yaml` | project repo |
| defaults | `src/grace_control/config/settings.py` | source tree |

A field set at a higher layer is **never overwritten** by a lower layer.
The merge is performed once, at `import` time, by
`src/grace_control/config/settings.py:_apply_project_fallbacks`. The rule
is: if the env-resolved value still equals the env-less default, the
project-config value takes its place; otherwise the env value wins.

## Schema

The typed schema lives in
`src/grace_control/config/project_config.py:ProjectConfig`. A complete
file looks like:

```yaml
project:
  name: grace-orchestrator
  key: default

api:
  host: 127.0.0.1
  port: 8042

database:
  url: sqlite:///./grace.db

git:
  remote: origin
  base_branch: main
  target_branch: main

execution:
  backend: legacy          # "legacy" | "api" | "mock"
  state_root: .grace/state
  worktree_root: .grace/worktrees
  timeout_seconds: 600

safety:
  sandbox_mode: danger-full-access
  allow_sandbox_bypass: false
```

All fields are optional. A missing file is treated as an empty config
and the safe local defaults take effect. Unknown keys are silently
ignored (Pydantic default).

## How to find the project root

`GRACE_PROJECT_ROOT` env var, falling back to the current working
directory. The loader looks for `<root>/.grace/config.yaml`.

## How to override

| I want to… | How |
|------------|-----|
| change a value for one process | set `GRACE_FOO=bar` in the shell |
| change a value for the project | put it in `.grace/config.yaml` |
| change a default for everyone | edit `src/grace_control/config/settings.py` |
| override `.grace/config.yaml` for one process | set the env var, it wins |

## New fields added in W3

W3 expands `GraceSettings` with the fields that were previously
duplicated as direct `os.environ.get("GRACE_...")` calls in
routers/services:

| field | type | replaces |
|-------|------|----------|
| `git_remote` | str | `os.environ.get("GRACE_GIT_REMOTE", "origin")` (future) |
| `architect_timeout_seconds` | int | `os.environ.get("GRACE_ARCHITECT_TIMEOUT", "120")` |
| `context_timeout_seconds` | int | `os.environ.get("GRACE_CONTEXT_TIMEOUT", "60")` |
| `worktree_root` | str | hardcoded `worktree_root` in `cli/main.py:up` |
| `allow_sandbox_bypass` | bool | `os.environ.get("GRACE_ALLOW_SANDBOX_BYPASS")` (W2) |
| `self_evolution_max_sessions` | int | `os.environ.get("GRACE_SELF_MAX_SESSIONS", "3")` |
| `recovery_controller_enabled` | bool | `os.environ.get("GRACE_RECOVERY_CONTROLLER_ENABLED")` |
| `telegram_token` | str | `os.environ.get("GRACE_TELEGRAM_TOKEN")` |
| `telegram_chat_id` | str | `os.environ.get("GRACE_TELEGRAM_CHAT_ID")` |
| `agent_profiles_path_override` | str | `os.environ.get("GRACE_AGENT_PROFILES_PATH")` |
| `context_model` | str | `os.environ.get("GRACE_CONTEXT_MODEL")` |
| `session_dir` | str | `os.environ.get("GRACE_SESSION_DIR")` |

Routers and services that still read these vars directly are doing so
via the `os.environ.get("GRACE_X", settings.x)` pattern, which is the
documented escape hatch for emergency overrides. GraceLint rule
GRC100 (W10) will mark any direct read that is NOT in the allowlist:

```text
src/grace_control/config/
src/grace_control/db/__init__.py       # init_db takes db_url explicitly
src/grace_control/agent/legacy_backend.py  # legacy boundary until W8
src/grace_control/worker/worker.py     # agent_timeout / recovery_controller
src/grace_control/api/routers/self_evolution.py   # MAX_SESSIONS
src/grace_control/api/routers/architect.py        # ARCHITECT_TIMEOUT
src/grace_control/api/routers/packets.py          # target_repo_root
src/grace_control/core/acceptance_pipeline.py     # base_ref
src/grace_control/core/llm_runner.py    # session_dir / state_root
src/grace_control/core/telegram_notify.py   # secrets, env-only
src/grace_control/core/context_collector.py  # context timeout / model
src/grace_control/core/executor_selector.py   # profiles path
src/grace_control/adapters/packet_executor.py  # env-overrides-settings pattern
```

The list will shrink wave by wave as more direct reads move to
`settings.X`. W11 removes `legacy_backend.py` from the allowlist.

## Tests

`tests/grace_control/config/test_w3_config_cleanup.py` covers:

1. `load_project_config` returns defaults when the file is missing.
2. YAML values override defaults.
3. Invalid YAML raises a clear `yaml.YAMLError`.
4. Env vars override project config.
5. `settings.py` no longer hardcodes `/tmp/grace-*` paths.
6. `GraceSettings` has all the new W3 fields.
7. Survey: `os.environ.get("GRACE_...")` outside the allowlist.

## Migration to a future Alembic layer

`_SQLITE_COLUMN_MIGRATIONS` in `src/grace_control/db/__init__.py` is the
interim solution for additive column changes. Once Alembic is introduced
(W12+), the precedence model stays the same — only the migration
mechanism changes.
