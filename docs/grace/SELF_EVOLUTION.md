# Self-Evolution

Self-evolution sessions go through the same pipeline as regular packets.
The router at `api/routers/self_evolution.py` wraps the services:

1. `SelfEvolutionService` orchestrates the session lifecycle
2. `SelfEvolutionGuard` verifies that changed files are within allowed scope

## Guard rules

The guard (`core/self_evolution_guard.py`) checks:

- Changes must be inside `.grace/`, `src/grace_control/`, or `tests/`
- Changes must not touch `config/agent_profiles.yaml` or user credentials
- Each change must pass an internal review before being committed

## Pipeline flow

```
Self-evolution request
  → packet created with origin="self_evolution"
  → goes through normal packet execution (materialize → execute → acceptance → merge)
  → after acceptance, SelfEvolutionGuard runs
  → if guard passes → merged like a normal packet
  → if guard fails → rejected (changes discarded)
```

Self-evolution is not a side-channel. It uses the same claim/execute/review/
merge pipeline as any user-created packet.
