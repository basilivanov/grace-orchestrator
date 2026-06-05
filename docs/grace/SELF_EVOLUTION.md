# Self-Evolution

## Architecture (W11)

Self-evolution flows through the **same packet/acceptance/merge pipeline**
as user-created work. No side-channel mutations.

```
POST /api/self/evolve
  → SelfEvolutionService.create_session
    → classifies risk (low/medium/high)
    → stores rollback plan (base_commit, changed_files, merge_commit)
    → returns session_id (no worker spawn)

The session is then processed by:
  → Architect → normal PacketService lifecycle
  → Acceptance Pipeline
  → Evidence Verifier / Reviewer
  → MergeService
  → TraceService visibility
```

## Risk classification

| Risk | Scope | Requires approval |
| --- | --- | --- |
| `low` | `docs/*`, `*.md` only | No |
| `medium` | Code changes (`src/`, `tests/`) | Yes |
| `high` | `config/`, `security/`, `execution/` changes | Yes (manual) |

## Key changes in W11

1. **No subprocess in router** — `api/routers/self_evolution.py` no longer
   spawns worker processes. It creates a DB session and returns the ID.
2. **Explicit DTOs** — `SelfEvolutionJob`, `SelfEvolutionDecision`,
   `SelfEvolutionApproval`, `SelfEvolutionRollbackPlan` (service-level).
3. **Rollback metadata** — each session stores `base_commit`,
   `rollback_command`, `merge_commit`, `changed_files`.
4. **`SelfEvolutionService.commit_after_merge`** — records the merge
   commit SHA for traceability.
5. **GraceLint rule** — the router must not import `subprocess` (GRC102);
   verified by `test_w11_self_evolution.py::test_router_has_no_subprocess_spawn`.

## Files

| Component | Path |
| --- | --- |
| Router | `api/routers/self_evolution.py` |
| Service | `services/self_evolution_service.py` |
| Guard | `core/self_evolution_guard.py` |
| Schema | `db/schema.py` (SelfEvolutionSession) |
| Tests | `tests/grace_control/self_evolution/test_w11_self_evolution.py` |
