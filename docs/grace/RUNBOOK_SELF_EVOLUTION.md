# Runbook: Self-Evolution

## What self-evolution can/cannot do

Self-evolution allows GRACE to modify its own source code through the same
packet pipeline as user-created work.

**Can do:**
- Modify `src/grace_control/`, `tests/`, `docs/grace/`, `.grace/`
- Add new features through the architect → coder → acceptance → merge flow

**Cannot do:**
- Modify `config/agent_profiles.yaml` or security-related config
- Spawn worker processes directly from the API
- Create hidden side-channel mutations

## Approval gates

| Risk class | Scope | Auto-merge |
| --- | --- | --- |
| low | `docs/*`, `*.md` only | Yes |
| medium | Code changes | Requires approval |
| high | `config/`, `security/`, `execution/` | Manual |

## Rollback metadata

Every self-evolution session stores:

```json
{
  "base_commit": "abc123...",
  "changed_files": ["src/x.py"],
  "merge_commit": "def456...",
  "rollback_command": "git revert --no-commit def456..."
}
```

## Create a session

```bash
curl -X POST http://localhost:8042/api/self/evolve \
  -H "Content-Type: application/json" \
  -d '{"title": "refactor trace service", "description": "improve observability"}'
```

Response:
```json
{"session_id": "se-...", "status": "session_created", "risk_class": "medium", "requires_approval": true}
```

## Inspect sessions

```bash
# List
curl http://localhost:8042/api/self/sessions

# Get with rollback metadata
curl http://localhost:8042/api/self/sessions/{session_id}
```

## Manual recovery

If a self-evolution session produces unwanted changes:

1. Find `rollback_plan.rollback_command` via `GET /api/self/sessions/{id}`
2. Execute the rollback command in the repo
3. Cancel the session: `POST /api/self/sessions/{id}/cancel`
