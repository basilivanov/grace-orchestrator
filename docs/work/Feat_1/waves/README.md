# Feat_1 Waves Index

Parent TZ: `docs/work/TZ_GRACE_ORCHESTRATOR_RUNTIME_SCOPE_CONTEXT_HARDENING.md`

This folder slices the Feat_1 hardening TZ into executable waves.

## Execution order

| Wave | File | Status |
|---|---|---|
| W00 | `W00_BASELINE_AUDIT_FIXTURES.md` | READY |
| W01 | `W01_RUNTIME_SAFETY_LEASE_FENCING.md` | APPROVED |
| W02 | `W02_FAIL_CLOSED_PLAN_COMPILER_SCOPE_CONTRACT.md` | READY / next |
| W03 | `W03_CANONICAL_ARCHITECT_PROMPT_PROFILE_UNIFICATION.md` | READY |
| W04 | `W04_EXECUTION_PACKET_CONTEXT_BUNDLE.md` | READY |
| W05 | `W05_EVIDENCE_CONTRACT_END_TO_END.md` | READY |
| W06 | `W06_PROCESS_SUPERVISOR_COMMAND_RUNNER_HARDENING.md` | READY |
| W07 | `W07_WORKER_ERROR_HANDLING_RETRY_SEMANTICS.md` | READY |
| W08 | `W08_RECOVERY_CONTROLLER_STUCK_SCANNER.md` | READY |
| W09 | `W09_PROFILE_CLEANUP_AGENT_INPUT_VALIDATION.md` | READY |
| W10 | `W10_REMOVE_LEGACY_DEFAULTS_DUPLICATES.md` | READY |
| W11 | `W11_UI_API_DIAGNOSTICS_PLAN_RUNTIME_FAILURES.md` | READY |
| W12 | `W12_END_TO_END_HARDENING_SCENARIOS.md` | READY |

## Exchange protocol

For each wave, executor submits:

```text
/docs/work/Feat_1/exchange/inbox/WXX_001_SUBMISSION.md
```

Reviewer writes:

```text
/docs/work/Feat_1/exchange/outbox/WXX_001_REVIEW.md
```

Decision values:

- `APPROVED`
- `REWORK_REQUIRED`
- `BLOCKED`
- `NEEDS_INFO`

## Current next wave

W02 — Fail-closed Plan Compiler and Scope Contract.
