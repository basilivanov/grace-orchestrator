# Runbook: Local Development

## Install

```bash
git clone <repo>
cd grace-orchestrator
python3 -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
```

## Configuration

Default config works for local development. Override via environment variables:

```bash
export GRACE_DB_URL=sqlite:///./grace.db
export GRACE_EXECUTION_BACKEND=mock
```

See `docs/grace/CONFIGURATION.md` for the full reference.

## Run API server

```bash
uvicorn grace_control.api.main:app --host 127.0.0.1 --port 8042
```

## Run a packet through the API

Use a live profile from `src/grace_control/config/agent_profiles.yaml`,
for example `coder-mini-swe`:

```bash
curl -X POST http://localhost:8042/api/agents/run \
  -H "Content-Type: application/json" \
  -d '{"packet_id":"test-1","executor_id":"coder-mini-swe","worktree_path":"/tmp","packet_markdown":"# test","timeout_seconds":10}'
```

## Run tests / lint / docs-check

```bash
make test
make lint
make docs-check
make hygiene
make ci
```

The root `Makefile` is the single CI source of truth. `make test` runs the
deterministic test scope and excludes tests marked `external` or `live`.
Those tests require a running API, browser, or external provider and are run
explicitly with `make test-live` when that environment is available; the target
also runs the standalone `tests/live/` scenarios.
`make lint` uses the explicit `CI_LINT_SCOPE` for the canon-compliant CI
control surface; legacy runtime lint debt remains visible in the broad audit
command recorded by the packet submission rather than being suppressed.

The public operator surface is HTTP/OpenAPI; the control CLI and OpenCode
runtime are removed. Lifecycle/admin behavior is composed through typed
services and explicit dependency injection, with typed admin read models at
the router boundary.

## Run GraceLint

```bash
python scripts/grace_lint.py src/grace_control tests scripts
```
