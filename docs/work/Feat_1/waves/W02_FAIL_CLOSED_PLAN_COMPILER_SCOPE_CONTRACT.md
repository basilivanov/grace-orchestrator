# W02 — Fail-closed Plan Compiler and Scope Contract

Status: READY

Parent TZ: `docs/work/TZ_GRACE_ORCHESTRATOR_RUNTIME_SCOPE_CONTEXT_HARDENING.md`

## Goal

Forbid executable packets without strict, explicit, repo-relative write scope. Remove dangerous fallback defaults and silent scope mutation.

## Scope

- `src/grace_control/services/feature_planning_service.py`
- `src/grace_control/core/plan_compiler.py`
- `src/grace_control/core/contracts.py`
- `src/grace_control/services/packet_materializer.py`
- `src/grace_control/services/scope_path_canonicalizer.py`
- `tests/`

## Tasks

1. Plan compiler rejects missing/empty/non-list `scope` for coder packets.
2. Reject absolute paths, `..`, outside-repo paths, and Python import paths in `scope`.
3. Reject scope/frozen_scope overlap instead of silently removing overlap.
4. Remove `PacketMaterializer.DEFAULT_SCOPE` for executable packets.
5. Remove `build_packet_contract()` fallback to `src/grace_control/`.
6. Stop stripping absolute paths silently.
7. Stop `pkt.setdefault("scope", [])` from making invalid packets look valid.
8. Architect LLM failure must set `PLAN_FAILED`; it must not create executable empty-scope coder packets.
9. Persist `_plan_compiler.errors` and `_plan_compiler.warnings` for UI/API diagnostics.

## Acceptance

- Packet with missing/empty scope cannot be approved/materialized.
- Absolute and parent paths are rejected with clear compiler errors.
- Scope/frozen overlap is rejected.
- Architect fallback failure does not enqueue executable code work.
- Compiler errors are persisted in feature spec diagnostics.

## Required tests

- `test_plan_compiler_rejects_empty_scope`
- `test_build_packet_contract_does_not_default_empty_scope`
- `test_materializer_refuses_packet_without_scope`
- `test_absolute_scope_path_is_error_not_silently_stripped`
- `test_scope_frozen_overlap_is_error`
- `test_architect_fallback_does_not_enqueue_empty_scope_packet`

## Verification

```bash
python3 -m pytest tests -q
```

or targeted W02 tests with reason full suite was not run.

## Submission

Create `docs/work/Feat_1/exchange/inbox/W02_001_SUBMISSION.md` when done.
