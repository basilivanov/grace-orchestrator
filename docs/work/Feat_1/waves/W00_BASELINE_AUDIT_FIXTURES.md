# W00 — Baseline Audit Fixtures and Safety Snapshots

Status: READY

Parent TZ: `docs/work/TZ_GRACE_ORCHESTRATOR_RUNTIME_SCOPE_CONTEXT_HARDENING.md`

## Goal

Before changing runtime behavior, capture the known unsafe scenarios as regression fixtures so every later wave has a clear safety target.

## Scope

- `tests/`
- `tests/services/`
- `tests/core/`
- `tests/worker/`
- `tests/api/`
- `docs/work/Feat_1/`

## Tasks

1. Add regression fixtures for:
   - plan with `scope: []`;
   - packet without `expected_evidence`;
   - evidence fields: `stage`, `owner`, `producer`, `profile`, `coder_blocking`, `artifact_patterns`;
   - lease expires during active execution;
   - stale worker releases after reclaim;
   - timeout agent run;
   - `coder_agy` without input;
   - process closes stdout/stderr but does not exit;
   - `scoped_copy + pytest`;
   - wrong target repo root vs orchestrator project root.
2. Mark known current failures as `xfail` with a wave reference.
3. Document the minimal regression matrix for Feat_1.

## Acceptance

- Regression tests exist for the listed safety scenarios.
- Expected failures are explicitly marked with wave links.
- No runtime behavior is changed in this wave.

## Verification

```bash
python3 -m pytest tests -q
```

If full suite is unstable, run the targeted regression subset and document why.

## Submission

Create `docs/work/Feat_1/exchange/inbox/W00_001_SUBMISSION.md` when done.
