# TZ: GRACE orchestrator auto-gates matrix

## Goal

Make GRACE orchestrator automatically run mechanical acceptance gates based on packet profile and changed areas.

Architect and coder agents must not be responsible for remembering low-level bash commands such as ESLint, ruff, mypy, pytest, or target repo guardrails. They may request extra verification, but GRACE owns the default gate matrix.

## Scope

Repository: `basilivanov/grace-orchestrator`.

Expected areas to inspect/change:

- `src/grace_control/core/acceptance_pipeline.py`
- `src/grace_control/core/contracts.py`
- packet materialization / architect plan mapping if needed
- architect prompt/profile config if it currently asks for raw commands
- tests for acceptance pipeline profiles and default gate resolution
- docs under `docs/work/`

## Current behaviour

The pipeline already has deterministic stages:

```text
T0 -> T1 -> T2 -> T2_BROWSER -> T3_VISUAL
```

Current problems:

1. T0 is partly automatic but only knows backend-style `scripts/grace_lint.py` and ruff.
2. T0 does not automatically run frontend GRACE lint.
3. T1 commands come from `packet.verification.t1`.
4. T2 commands come from `packet.verification.t2`.
5. `NORMAL/STRICT` can fail because architect did not provide `verification.t1`.
6. `STRICT` can fail because architect did not provide `verification.t2`.
7. Mechanical checks are therefore partly prompt-dependent.

Target behaviour:

```text
Architect chooses intent/scope/profile.
GRACE resolves default mechanical gates.
Architect may add extra verification only.
Coder cannot bypass default gates.
Merge allowed only after required profile gates pass.
```

## Terminology

### Stage 0

Stage 0 remains the read-only context-builder stage.

It is not a lint/test stage.

### T0

Cheap deterministic mechanical gates after coder diff.

### T1

Targeted normal verification based on touched areas.

### T2

Full/strict merge-level verification.

## Required profile matrix

### FAST

Purpose: quick feedback, cheap checks only.

Must run:

- scope guard;
- packet contract validation;
- backend GRACE lint for changed/allowed Python files when target repo provides `scripts/grace_lint.py`;
- frontend GRACE lint for changed/allowed frontend files when target repo provides `scripts/grace_front_lint.py`;
- Python ruff for changed/allowed Python files when available;
- no evidence verifier;
- no reviewer;
- no T2 full checks.

### NORMAL

Purpose: normal acceptance for most product packets.

Must run:

- everything from FAST;
- default T1 commands resolved from touched areas;
- evidence verifier;
- no reviewer by default.

T1 defaults:

- frontend touched -> target repo frontend guardrails or equivalent;
- backend touched -> target repo backend guardrails or equivalent;
- contracts touched -> target repo contracts/drift gate if available;
- db/migrations touched -> migration round-trip if available;
- docs only -> docs guardrails if available.

### STRICT

Purpose: merge-grade acceptance for broad, risky, frontend+backend, infra, contract, or self-evolution changes.

Must run:

- everything from NORMAL;
- default T2 full/strict target repo guardrails;
- evidence verifier;
- reviewer gate.

T2 defaults:

- if target repo has `bash scripts/guardrails.sh strict`, run it;
- otherwise fall back to `bash scripts/guardrails.sh full` if available;
- otherwise fail with explicit missing strict gate issue.

## Touched area detection

Add a deterministic resolver from changed files and allowed scope:

```text
frontend: .js, .jsx, .ts, .tsx, app/, components/, lib/ frontend paths, eslint config, tsconfig, package frontend-related files
backend: .py under apps/api/, backend service paths
contracts: packages/contracts/, openapi, generated contract files, contract generation scripts
db: alembic/, migrations, SQLAlchemy model/schema files
docs: docs/, grace/, *.md
domain: project-specific domain guard files, if configured
```

Resolver output should be stored in acceptance report metadata or stage summary when possible.

Architect may provide `touched_areas`, but GRACE must recompute and verify from actual changed files. Architect-provided areas are hints, not source of truth.

## Default command resolution

Implement a function or service similar to:

```python
resolve_default_gates(packet, changed_files, profile, worktree_path) -> dict[str, list[list[str]]]
```

It should return default commands for T0/T1/T2.

Commands must be target-repo based. Prefer stable target repo interface:

```bash
bash scripts/guardrails.sh fast
bash scripts/guardrails.sh normal
bash scripts/guardrails.sh strict
```

Do not hard-code SolarSage-only internals in orchestrator except as optional detection fallbacks.

## T0 requirements

T0 should always be automatic.

For changed Python files:

- run `python3 scripts/grace_lint.py <scope paths>` if present;
- run ruff on changed Python files if available.

For changed frontend files:

- run `python3 scripts/grace_front_lint.py <scope paths>` if present;
- if only legacy `scripts/grace/check-markers.sh` exists, run it as fallback;
- if frontend files are changed and no frontend GRACE lint exists, fail in NORMAL/STRICT and warn in FAST.

T0 must continue to enforce scope guard and packet contract validation.

## T1 requirements

T1 should merge default commands with architect-provided extra commands.

New rule:

```text
NORMAL/STRICT require T1 to run, but T1 may be satisfied by auto-resolved defaults.
```

Do not fail merely because `packet.verification.t1` is absent if auto defaults exist.

If no auto defaults and no explicit T1 exist for NORMAL/STRICT, fail with a clear message.

## T2 requirements

T2 should merge default commands with architect-provided extra commands.

New rule:

```text
STRICT requires T2 to run, but T2 may be satisfied by auto-resolved defaults.
```

Do not fail merely because `packet.verification.t2` is absent if auto strict defaults exist.

If no target repo strict/full guardrails exist for STRICT, fail with a clear message.

## Architect prompt / packet contract changes

Architect should not be prompted to list mechanical commands.

Architect should output or preserve only high-level fields:

```json
{
  "acceptance_profile": "FAST|NORMAL|STRICT",
  "touched_areas": ["frontend", "backend", "contracts", "db", "docs", "domain"],
  "extra_verification": {
    "t1": [],
    "t2": [],
    "t2_browser": [],
    "t3_visual": []
  }
}
```

`extra_verification` is optional and additive. It must not replace default gates.

If the existing packet contract already has `verification`, keep backward compatibility:

- `verification.t1` means extra T1 commands;
- `verification.t2` means extra T2 commands;
- auto defaults are prepended or appended deterministically.

## Evidence and reports

Acceptance report must show which commands came from:

- `auto:t0`
- `auto:t1`
- `auto:t2`
- `architect:extra_verification`

Reports should include:

- profile;
- touched areas detected;
- commands run;
- exit codes;
- stdout/stderr artifact paths;
- skipped gates and reasons.

## Backward compatibility

Existing scenarios with explicit `verification.t1/t2` must still work.

Existing FAST behaviour may still skip T1/T2, but FAST must not skip T0 mechanical checks.

Existing Stage 0 context-builder logic must not be changed except where needed to pass context into packet planning.

## Tests required

Add or update tests covering:

1. FAST with frontend change runs frontend GRACE lint in T0.
2. FAST with backend change runs backend GRACE lint/ruff in T0.
3. NORMAL without explicit `verification.t1` passes contract validation when auto T1 defaults exist.
4. NORMAL without explicit `verification.t1` fails clearly when no auto defaults exist.
5. STRICT without explicit `verification.t2` uses target repo strict/full guardrails when present.
6. STRICT without explicit `verification.t2` fails clearly when no target repo strict/full guardrails exist.
7. Frontend+backend change resolves both areas.
8. Explicit architect verification commands are additive, not replacing defaults.
9. Stage 0 context-builder remains separate from T0/T1/T2.
10. Acceptance report records auto vs explicit command origins.

## Acceptance criteria

Implementation is accepted only if:

- architect/coder no longer need to know mechanical bash commands;
- default T0/T1/T2 gate matrix works from changed files and profile;
- target repo guardrails are used through stable `scripts/guardrails.sh` interface where available;
- backend and frontend GRACE lint are auto-run when relevant;
- NORMAL/STRICT no longer fail just because architect omitted `verification.t1/t2` when auto defaults exist;
- STRICT still blocks merge when strict/full target repo guardrails are missing;
- tests pass;
- Pilot after this change can run a frontend+backend packet with `acceptance_profile=STRICT` and no manual mechanical commands in architect output.

## Non-goals

- Do not move target repo guardrails implementation into orchestrator runtime.
- Do not remove Stage 0 context-builder.
- Do not make architect responsible for command names.
- Do not add GitHub Actions as a requirement.
