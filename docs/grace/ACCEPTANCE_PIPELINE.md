# Acceptance Pipeline

The deterministic acceptance pipeline (`core/acceptance_pipeline.py`) runs
three stages (`core/contracts.py:StageName`):

| Stage | Purpose | Command source |
| --- | --- | --- |
| `T0_SCOPE_AND_LINT` | Lint, format, compile check | `spec_json.verification.t0` |
| `T1_UNIT_TESTS` | Unit/integration tests | `spec_json.verification.t1` |
| `T2_E2E_OR_SMOKE` | End-to-end verification | `spec_json.verification.t2` |

If any stage fails, the report carries `blocking_issues` that feed the
trace API (`TraceService.last_failure.blocking_issues`).

After the deterministic pipeline:

1. **FAST** profile → skip evidence verifier + reviewer, wire accepted
2. **NORMAL** profile → run evidence verifier, skip reviewer if pass
3. **STRICT** profile → run evidence verifier + reviewer gate

Evidence verifier (`core/evidence_verifier.py`) reads
`core/prompts/evidence_verifier_prompt.md` for its prompt template. It
returns one of `PASS`, `REWORK_TO_CODER`, `RETURN_TO_ARCHITECT`.

Reviewer gate (`core/reviewer_gate.py`) reads
`core/prompts/reviewer_prompt.md`. Returns `PASS`, `REWORK_TO_CODER`,
`RETURN_TO_ARCHITECT`.

Recovery ladder (odd/even attempts) is evaluated via
`core/recovery_rules.evaluate_ladder()`:
- Odd attempts (1, 3, 5): skip verifier, fast path to coder
- Even attempts (2, 4, 6): run verifier, classify, switch coder or architect
- Attempt 7+: new architect with full context
