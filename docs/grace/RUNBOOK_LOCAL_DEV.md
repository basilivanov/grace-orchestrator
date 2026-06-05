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

Default config works for local dev. Override via env vars:

```bash
export GRACE_DB_URL=sqlite:///./grace.db
export GRACE_EXECUTION_BACKEND=mock
```

See `docs/grace/CONFIGURATION.md` for full reference.

## Run API server

```bash
uvicorn grace_control.api.main:app --host 127.0.0.1 --port 8042
```

## Run a fake CLI profile

```bash
# Create a fake agent script
echo '#!/bin/sh
echo "{\"result\": \"ok\"}"' > /tmp/fake-agent.sh
chmod +x /tmp/fake-agent.sh
export PATH=/tmp:$PATH

# Run a packet through the API
curl -X POST http://localhost:8042/api/agents/run \
  -H "Content-Type: application/json" \
  -d '{"packet_id":"test-1","executor_id":"coder_opencode","worktree_path":"/tmp","packet_markdown":"# test","timeout_seconds":10}'
```

## Run tests / lint / docs-check

```bash
make test
make lint
make docs-check
make ci          # full CI gate suite
```

## Run GraceLint

```bash
python scripts/grace_lint.py src/grace_control/
```
